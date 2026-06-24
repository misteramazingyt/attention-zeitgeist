"""Build the composite ``attention_index_daily`` table.

Implements the conservative first-pass index described in the spec:

1. aggregate metric by domain/topic (done in ``domain_daily``/``topic_daily``);
2. log-transform values (``log1p``);
3. convert to a percentile rank within (source, date) -> ``normalized_value``;
4. store per-signal scores (one column per attention signal);
5. composite score = mean of the *available* signal scores;
6. record how many signals contributed (``source_coverage_count``).

Different signals are never collapsed before scoring: each keeps its own
column so the heterogeneity stays inspectable.
"""

from __future__ import annotations

import math

from ..storage import Storage
from ..utils.logging import get_logger

logger = get_logger(__name__)


def percentile_scores(values: list[float]) -> list[float]:
    """Return within-group percentile ranks of ``log1p(value)``.

    This is the pure-Python mirror of the SQL normalization, exposed for unit
    testing the score normalization step. Uses the same definition as SQL
    ``percent_rank``: ``(rank - 1) / (n - 1)`` over ascending log-values, with
    ties sharing the minimum rank. A single value scores 0.0.

    Args:
        values: Raw non-negative metric values.

    Returns:
        A list of percentile ranks in [0, 1], aligned to ``values``.
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0.0]
    logged = [math.log1p(max(0.0, v)) for v in values]
    order = sorted(range(n), key=lambda i: logged[i])
    # Assign min-rank to ties.
    ranks = [0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and logged[order[j + 1]] == logged[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = i  # zero-based min rank
        i = j + 1
    return [r / (n - 1) for r in ranks]


# Pivot domain_daily / topic_daily normalized values into per-signal score
# columns and compute the composite. We aggregate normalized_value with avg()
# so multiple sources sharing a signal (e.g. Tranco + Cloudflare -> rank) are
# averaged rather than duplicated.
def _index_sql(table: str, key_col: str, level: str) -> str:
    return f"""
INSERT INTO attention_index_daily
    (date, domain_or_topic, level, pageview_score, discursive_score,
     news_score, rank_score, structural_score, composite_attention_score,
     source_coverage_count, notes)
WITH pivoted AS (
    SELECT
        date,
        {key_col} AS key,
        avg(CASE WHEN attention_signal = 'pageview_attention'  THEN normalized_value END) AS pageview_score,
        avg(CASE WHEN attention_signal = 'discursive_attention' THEN normalized_value END) AS discursive_score,
        avg(CASE WHEN attention_signal = 'news_attention'       THEN normalized_value END) AS news_score,
        avg(CASE WHEN attention_signal = 'rank_attention'       THEN normalized_value END) AS rank_score,
        avg(CASE WHEN attention_signal = 'structural_attention' THEN normalized_value END) AS structural_score
    FROM {table}
    GROUP BY date, {key_col}
)
SELECT
    date,
    key AS domain_or_topic,
    '{level}' AS level,
    pageview_score,
    discursive_score,
    news_score,
    rank_score,
    structural_score,
    (
        coalesce(pageview_score, 0) + coalesce(discursive_score, 0)
        + coalesce(news_score, 0) + coalesce(rank_score, 0)
        + coalesce(structural_score, 0)
    ) / nullif(
        (pageview_score IS NOT NULL)::INT + (discursive_score IS NOT NULL)::INT
        + (news_score IS NOT NULL)::INT + (rank_score IS NOT NULL)::INT
        + (structural_score IS NOT NULL)::INT, 0
    ) AS composite_attention_score,
    (
        (pageview_score IS NOT NULL)::INT + (discursive_score IS NOT NULL)::INT
        + (news_score IS NOT NULL)::INT + (rank_score IS NOT NULL)::INT
        + (structural_score IS NOT NULL)::INT
    ) AS source_coverage_count,
    'composite = mean of available signal percentile scores' AS notes
FROM pivoted;
"""


def build_attention_index(storage: Storage) -> int:
    """Rebuild ``attention_index_daily`` for both domain and topic levels.

    Returns:
        The total number of index rows written.
    """
    storage.con.execute("DELETE FROM attention_index_daily")
    storage.con.execute(_index_sql("domain_daily", "domain", "domain"))
    storage.con.execute(_index_sql("topic_daily", "topic", "topic"))
    n = storage.table_count("attention_index_daily")
    logger.info("Built attention_index_daily: %d rows", n)
    return n

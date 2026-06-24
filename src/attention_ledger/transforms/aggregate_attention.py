"""Build the daily aggregate tables ``domain_daily`` and ``topic_daily``.

Aggregation collapses raw events into one row per (date, entity, source,
signal). ``normalized_value`` is the within-(source, date) percentile rank of
``log1p(metric_value)`` — making heterogeneous metrics comparable in [0, 1]
without ever conflating raw pageviews with raw comment counts.
"""

from __future__ import annotations

from ..storage import Storage
from ..utils.logging import get_logger

logger = get_logger(__name__)


DOMAIN_DAILY_SQL = """
DELETE FROM domain_daily;
INSERT INTO domain_daily
    (date, domain, source, attention_signal, metric_name,
     metric_value, normalized_value, rank_within_source)
WITH agg AS (
    SELECT
        date,
        domain,
        source,
        attention_signal,
        any_value(metric_name) AS metric_name,
        sum(metric_value)      AS metric_value
    FROM attention_events
    WHERE domain IS NOT NULL AND domain <> ''
    GROUP BY date, domain, source, attention_signal
)
SELECT
    date,
    domain,
    source,
    attention_signal,
    metric_name,
    metric_value,
    percent_rank() OVER (
        PARTITION BY source, date ORDER BY ln(1 + metric_value)
    ) AS normalized_value,
    row_number() OVER (
        PARTITION BY source, date ORDER BY metric_value DESC
    ) AS rank_within_source
FROM agg;
"""

# Topic aggregation joins events to their classification. Domains that were
# never classified fall back to 'miscellaneous' so nothing is silently dropped.
TOPIC_DAILY_SQL = """
DELETE FROM topic_daily;
INSERT INTO topic_daily
    (date, topic, source, attention_signal, metric_value,
     normalized_value, top_entities, top_domains)
WITH labeled AS (
    SELECT
        e.date,
        e.source,
        e.attention_signal,
        coalesce(c.category, 'miscellaneous') AS topic,
        e.entity_label,
        e.domain,
        e.metric_value
    FROM attention_events e
    LEFT JOIN entity_classification c
      ON c.source = e.source AND c.entity_id = e.entity_id
),
agg AS (
    SELECT
        date,
        topic,
        source,
        attention_signal,
        sum(metric_value) AS metric_value
    FROM labeled
    GROUP BY date, topic, source, attention_signal
),
top_ent AS (
    SELECT date, topic, source, attention_signal,
           string_agg(entity_label, ', ' ORDER BY mv DESC) FILTER (WHERE rn <= 5) AS top_entities
    FROM (
        SELECT date, topic, source, attention_signal, entity_label,
               sum(metric_value) AS mv,
               row_number() OVER (
                   PARTITION BY date, topic, source, attention_signal
                   ORDER BY sum(metric_value) DESC
               ) AS rn
        FROM labeled
        WHERE entity_label IS NOT NULL
        GROUP BY date, topic, source, attention_signal, entity_label
    )
    GROUP BY date, topic, source, attention_signal
),
top_dom AS (
    SELECT date, topic, source, attention_signal,
           string_agg(domain, ', ' ORDER BY mv DESC) FILTER (WHERE rn <= 5) AS top_domains
    FROM (
        SELECT date, topic, source, attention_signal, domain,
               sum(metric_value) AS mv,
               row_number() OVER (
                   PARTITION BY date, topic, source, attention_signal
                   ORDER BY sum(metric_value) DESC
               ) AS rn
        FROM labeled
        WHERE domain IS NOT NULL
        GROUP BY date, topic, source, attention_signal, domain
    )
    GROUP BY date, topic, source, attention_signal
)
SELECT
    a.date,
    a.topic,
    a.source,
    a.attention_signal,
    a.metric_value,
    percent_rank() OVER (PARTITION BY a.source, a.date ORDER BY ln(1 + a.metric_value)) AS normalized_value,
    te.top_entities,
    td.top_domains
FROM agg a
LEFT JOIN top_ent te USING (date, topic, source, attention_signal)
LEFT JOIN top_dom td USING (date, topic, source, attention_signal);
"""


def build_domain_daily(storage: Storage) -> int:
    """Rebuild the ``domain_daily`` table from ``attention_events``.

    Returns:
        The number of rows written.
    """
    storage.con.execute(DOMAIN_DAILY_SQL)
    n = storage.table_count("domain_daily")
    logger.info("Built domain_daily: %d rows", n)
    return n


def build_topic_daily(storage: Storage) -> int:
    """Rebuild the ``topic_daily`` table from events + classification.

    Returns:
        The number of rows written.
    """
    storage.con.execute(TOPIC_DAILY_SQL)
    n = storage.table_count("topic_daily")
    logger.info("Built topic_daily: %d rows", n)
    return n

"""Research-table exports.

Produces the deliverable CSV (or Parquet) package from the DuckDB tables:

* ``domain_daily.csv``
* ``topic_daily.csv``
* ``attention_index_daily.csv``
* ``top_domains_by_source.csv``
* ``top_topics_by_source.csv``
* ``attention_spikes.csv``

Derived tables (top-N and spikes) are computed on the fly so the export is
always consistent with the current database state.
"""

from __future__ import annotations

from pathlib import Path

from .storage import Storage
from .utils.logging import get_logger

logger = get_logger(__name__)

# Top 50 domains per source by total metric value across the loaded window.
TOP_DOMAINS_BY_SOURCE_SQL = """
SELECT source, domain, attention_signal,
       sum(metric_value) AS total_metric,
       avg(normalized_value) AS avg_normalized,
       count(*) AS days_present
FROM domain_daily
GROUP BY source, domain, attention_signal
QUALIFY row_number() OVER (PARTITION BY source ORDER BY sum(metric_value) DESC) <= 50
ORDER BY source, total_metric DESC
"""

TOP_TOPICS_BY_SOURCE_SQL = """
SELECT source, topic, attention_signal,
       sum(metric_value) AS total_metric,
       avg(normalized_value) AS avg_normalized,
       count(*) AS days_present
FROM topic_daily
GROUP BY source, topic, attention_signal
QUALIFY row_number() OVER (PARTITION BY source ORDER BY sum(metric_value) DESC) <= 50
ORDER BY source, total_metric DESC
"""

# Spikes: day-over-day jumps in a domain's within-source normalized value.
# A spike is flagged when the normalized value rises by >= 0.25 vs the prior
# day for the same (domain, source, signal).
ATTENTION_SPIKES_SQL = """
WITH series AS (
    SELECT date, domain, source, attention_signal, metric_value, normalized_value,
           lag(normalized_value) OVER (
               PARTITION BY domain, source, attention_signal ORDER BY date
           ) AS prev_norm,
           lag(metric_value) OVER (
               PARTITION BY domain, source, attention_signal ORDER BY date
           ) AS prev_metric
    FROM domain_daily
)
SELECT date, domain, source, attention_signal,
       metric_value, prev_metric,
       normalized_value, prev_norm,
       (normalized_value - prev_norm) AS norm_delta
FROM series
WHERE prev_norm IS NOT NULL
  AND (normalized_value - prev_norm) >= 0.25
ORDER BY norm_delta DESC
"""

# Core table -> SQL select mapping for the always-present exports.
_CORE_TABLES = {
    "domain_daily": "SELECT * FROM domain_daily ORDER BY date, source, rank_within_source",
    "topic_daily": "SELECT * FROM topic_daily ORDER BY date, source, metric_value DESC",
    "attention_index_daily": (
        "SELECT * FROM attention_index_daily "
        "ORDER BY date, level, composite_attention_score DESC"
    ),
}

_DERIVED_TABLES = {
    "top_domains_by_source": TOP_DOMAINS_BY_SOURCE_SQL,
    "top_topics_by_source": TOP_TOPICS_BY_SOURCE_SQL,
    "attention_spikes": ATTENTION_SPIKES_SQL,
}


def export_tables(storage: Storage, out_dir: str | Path, fmt: str = "csv") -> list[Path]:
    """Export all research tables to ``out_dir`` in the requested format.

    Args:
        storage: An open :class:`Storage`.
        out_dir: Destination directory (created if missing).
        fmt: ``"csv"`` or ``"parquet"``.

    Returns:
        A list of written file paths.

    Raises:
        ValueError: If ``fmt`` is unsupported.
    """
    fmt = fmt.lower()
    if fmt not in {"csv", "parquet"}:
        raise ValueError(f"Unsupported export format: {fmt!r} (use csv or parquet)")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    all_queries = {**_CORE_TABLES, **_DERIVED_TABLES}
    for name, query in all_queries.items():
        dest = out / f"{name}.{fmt}"
        copy_fmt = "(FORMAT CSV, HEADER)" if fmt == "csv" else "(FORMAT PARQUET)"
        storage.con.execute(f"COPY ({query}) TO '{dest}' {copy_fmt}")
        written.append(dest)
        logger.info("Exported %s", dest)

    return written

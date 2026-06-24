"""DuckDB storage layer.

Owns the database connection, the canonical schema (``domains``,
``attention_events``, ``domain_daily``, ``topic_daily``,
``attention_index_daily``, plus ``ingestion_runs`` metadata), and helpers to
append normalized events and record ingestion runs. All analytics in the
project read from and write to this single local DuckDB file.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

import duckdb

from .config import Config, get_config
from .schemas import AttentionEvent, IngestionRunLog
from .utils.logging import get_logger

logger = get_logger(__name__)

# Canonical DDL. Tables are created idempotently. A sequence backs synthetic
# integer ids for events; domains use a hash-free incrementing id keyed by
# the unique domain string.
SCHEMA_SQL = """
CREATE SEQUENCE IF NOT EXISTS seq_event_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_domain_id START 1;

CREATE TABLE IF NOT EXISTS domains (
    domain_id           BIGINT PRIMARY KEY DEFAULT nextval('seq_domain_id'),
    domain              VARCHAR UNIQUE,
    registrable_domain  VARCHAR,
    subdomain           VARCHAR,
    tld                 VARCHAR,
    platform_label      VARCHAR,
    category_label      VARCHAR,
    created_at          TIMESTAMP DEFAULT now(),
    updated_at          TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS attention_events (
    event_id            BIGINT PRIMARY KEY DEFAULT nextval('seq_event_id'),
    source              VARCHAR NOT NULL,
    attention_signal    VARCHAR NOT NULL,
    timestamp           TIMESTAMP,
    date                DATE NOT NULL,
    url                 VARCHAR,
    domain              VARCHAR,
    subdomain           VARCHAR,
    path                VARCHAR,
    entity_id           VARCHAR,
    entity_label        VARCHAR,
    entity_type         VARCHAR,
    metric_name         VARCHAR NOT NULL,
    metric_value        DOUBLE NOT NULL,
    raw_payload_path    VARCHAR
);

CREATE TABLE IF NOT EXISTS domain_daily (
    date                DATE,
    domain              VARCHAR,
    source              VARCHAR,
    attention_signal    VARCHAR,
    metric_name         VARCHAR,
    metric_value        DOUBLE,
    normalized_value    DOUBLE,
    rank_within_source  BIGINT
);

CREATE TABLE IF NOT EXISTS topic_daily (
    date                DATE,
    topic               VARCHAR,
    source              VARCHAR,
    attention_signal    VARCHAR,
    metric_value        DOUBLE,
    normalized_value    DOUBLE,
    top_entities        VARCHAR,
    top_domains         VARCHAR
);

CREATE TABLE IF NOT EXISTS attention_index_daily (
    date                     DATE,
    domain_or_topic          VARCHAR,
    level                    VARCHAR,
    pageview_score           DOUBLE,
    discursive_score         DOUBLE,
    news_score               DOUBLE,
    rank_score               DOUBLE,
    structural_score         DOUBLE,
    composite_attention_score DOUBLE,
    source_coverage_count    INTEGER,
    notes                    VARCHAR
);

CREATE TABLE IF NOT EXISTS entity_classification (
    source       VARCHAR,
    entity_id    VARCHAR,
    entity_label VARCHAR,
    entity_type  VARCHAR,
    topic        VARCHAR,
    category     VARCHAR,
    method       VARCHAR,
    updated_at   TIMESTAMP DEFAULT now(),
    UNIQUE (source, entity_id)
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    source       VARCHAR,
    started_at   TIMESTAMP,
    finished_at  TIMESTAMP,
    rows_written BIGINT,
    parameters   VARCHAR,
    status       VARCHAR,
    message      VARCHAR
);
"""

EVENT_COLUMNS: Sequence[str] = (
    "source",
    "attention_signal",
    "timestamp",
    "date",
    "url",
    "domain",
    "subdomain",
    "path",
    "entity_id",
    "entity_label",
    "entity_type",
    "metric_name",
    "metric_value",
    "raw_payload_path",
)


class Storage:
    """Thin wrapper around a DuckDB connection scoped to the ledger schema."""

    def __init__(self, db_path: Path | str | None = None, config: Config | None = None):
        """Open (or create) the DuckDB database.

        Args:
            db_path: Optional explicit path to the database file. Defaults to
                the configured ``db_path``.
            config: Optional :class:`Config`; defaults to the cached config.
        """
        self.config = config or get_config()
        self.db_path = Path(db_path) if db_path else self.config.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(self.db_path))

    # --- lifecycle -----------------------------------------------------
    def init_schema(self) -> None:
        """Create all tables and sequences idempotently."""
        self.con.execute(SCHEMA_SQL)
        logger.info("Initialized schema in %s", self.db_path)

    def close(self) -> None:
        """Close the underlying connection."""
        self.con.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- writes --------------------------------------------------------
    def append_events(self, events: Iterable[AttentionEvent]) -> int:
        """Append validated attention events to ``attention_events``.

        Args:
            events: Iterable of :class:`AttentionEvent` models.

        Returns:
            The number of rows written.
        """
        rows = []
        for ev in events:
            d = ev.model_dump()
            rows.append(tuple(d[c] for c in EVENT_COLUMNS))
        if not rows:
            logger.warning("append_events called with zero rows")
            return 0
        placeholders = ", ".join(["?"] * len(EVENT_COLUMNS))
        cols = ", ".join(EVENT_COLUMNS)
        self.con.executemany(
            f"INSERT INTO attention_events ({cols}) VALUES ({placeholders})",
            rows,
        )
        logger.info("Wrote %d events", len(rows))
        return len(rows)

    def upsert_domains_from_events(self) -> int:
        """Populate the ``domains`` table from distinct event domains.

        Inserts any domain present in ``attention_events`` that is not yet in
        ``domains``. Domain decomposition is filled by the classify step;
        here we only ensure rows exist.

        Returns:
            Number of new domain rows inserted.
        """
        before = self.con.execute("SELECT count(*) FROM domains").fetchone()[0]
        self.con.execute(
            """
            INSERT INTO domains (domain, registrable_domain)
            SELECT DISTINCT domain, domain
            FROM attention_events
            WHERE domain IS NOT NULL AND domain <> ''
              AND domain NOT IN (SELECT domain FROM domains)
            """
        )
        after = self.con.execute("SELECT count(*) FROM domains").fetchone()[0]
        inserted = after - before
        logger.info("Upserted %d new domains", inserted)
        return inserted

    def log_run(self, run: IngestionRunLog) -> None:
        """Persist an ingestion run record."""
        self.con.execute(
            """
            INSERT INTO ingestion_runs
                (source, started_at, finished_at, rows_written, parameters, status, message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.source,
                run.started_at,
                run.finished_at,
                run.rows_written,
                run.parameters,
                run.status,
                run.message,
            ),
        )

    def record_run(
        self,
        source: str,
        started_at: datetime,
        finished_at: datetime,
        rows_written: int,
        parameters: str,
        status: str = "ok",
        message: str = "",
    ) -> None:
        """Convenience wrapper to build and persist an :class:`IngestionRunLog`."""
        self.log_run(
            IngestionRunLog(
                source=source,
                started_at=started_at,
                finished_at=finished_at,
                rows_written=rows_written,
                parameters=parameters,
                status=status,
                message=message,
            )
        )

    # --- reads ---------------------------------------------------------
    def table_count(self, table: str) -> int:
        """Return the row count for a table (0 if it does not exist)."""
        try:
            return self.con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        except duckdb.CatalogException:
            return 0

    def has_events(self) -> bool:
        """Return True if any attention events have been ingested."""
        return self.table_count("attention_events") > 0

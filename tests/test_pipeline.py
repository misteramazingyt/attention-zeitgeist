"""End-to-end pipeline test using a temporary DuckDB database (offline)."""

from __future__ import annotations

from attention_ledger.config import Config
from attention_ledger.exports import export_tables
from attention_ledger.sources import gdelt, tranco, wikimedia
from attention_ledger.storage import Storage
from attention_ledger.transforms.aggregate_attention import (
    build_domain_daily,
    build_topic_daily,
)
from attention_ledger.transforms.classify_topics import classify_domains, classify_wikipedia
from attention_ledger.transforms.normalize_domains import normalize_domains
from attention_ledger.transforms.score_attention import build_attention_index


def test_full_pipeline(tmp_path):
    cfg = Config(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "processed" / "test.duckdb",
        offline=True,
    )
    cfg.ensure_dirs()

    wiki = wikimedia.ingest("2026-01-01", "2026-01-03", project="en.wikipedia", config=cfg)
    news = gdelt.ingest("2026-01-01", "2026-01-03", query="AI", config=cfg)
    ranks = tranco.ingest(input_path=cfg.raw_dir / "t.csv", demo=True, config=cfg)

    with Storage(config=cfg) as storage:
        storage.init_schema()
        storage.append_events(wiki)
        storage.append_events(news)
        storage.append_events(ranks)
        storage.upsert_domains_from_events()

        normalize_domains(storage)
        classify_domains(storage)
        classify_wikipedia(storage)

        d = build_domain_daily(storage)
        t = build_topic_daily(storage)
        i = build_attention_index(storage)

        assert d > 0 and t > 0 and i > 0

        # Composite scores must be within [0, 1].
        bounds = storage.con.execute(
            "SELECT min(composite_attention_score), max(composite_attention_score) "
            "FROM attention_index_daily"
        ).fetchone()
        assert bounds[0] >= 0.0 and bounds[1] <= 1.0

        # At least one domain should be covered by more than one source signal
        # (Wikipedia domain + Tranco both touch wikipedia.org / others).
        max_cov = storage.con.execute(
            "SELECT max(source_coverage_count) FROM attention_index_daily WHERE level='domain'"
        ).fetchone()[0]
        assert max_cov >= 1

        paths = export_tables(storage, out_dir=cfg.exports_dir, fmt="csv")
        names = {p.name for p in paths}
        assert {
            "domain_daily.csv",
            "topic_daily.csv",
            "attention_index_daily.csv",
            "top_domains_by_source.csv",
            "top_topics_by_source.csv",
            "attention_spikes.csv",
        } <= names
        for p in paths:
            assert p.exists()

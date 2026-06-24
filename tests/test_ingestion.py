"""Tests for sample ingestion rows across connectors (offline mode)."""

from __future__ import annotations

import json

import pytest

from attention_ledger.config import Config
from attention_ledger.schemas import AttentionEvent, AttentionSignal
from attention_ledger.sources import gdelt, reddit, tranco, wikimedia


@pytest.fixture()
def offline_config(tmp_path) -> Config:
    """A Config rooted in a temp dir with offline mode enabled."""
    cfg = Config(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "processed" / "test.duckdb",
        offline=True,
    )
    cfg.ensure_dirs()
    return cfg


def test_wikimedia_offline_rows(offline_config):
    events = wikimedia.ingest("2026-01-01", "2026-01-02", project="en.wikipedia", config=offline_config)
    assert events, "expected synthetic wikimedia events"
    ev = events[0]
    assert isinstance(ev, AttentionEvent)
    assert ev.source == "wikimedia"
    assert ev.attention_signal == AttentionSignal.PAGEVIEW.value
    assert ev.entity_type == "wikipedia_article"
    assert ev.metric_name == "views"
    assert ev.metric_value > 0
    # Two days of data should be present.
    assert len({e.date for e in events}) == 2


def test_gdelt_offline_rows(offline_config):
    events = gdelt.ingest("2026-01-01", "2026-01-01", query="AI", config=offline_config)
    assert events
    ev = events[0]
    assert ev.source == "gdelt"
    assert ev.attention_signal == AttentionSignal.NEWS.value
    assert ev.metric_name == "article_count"
    assert ev.domain and "." in ev.domain


def test_tranco_demo_rows(offline_config):
    path = offline_config.raw_dir / "tranco_demo.csv"
    events = tranco.ingest(input_path=path, demo=True, config=offline_config)
    assert events
    ev = events[0]
    assert ev.source == "tranco"
    assert ev.attention_signal == AttentionSignal.RANK.value
    # Inverse rank: the first (rank 1) domain has the highest metric value.
    assert events[0].metric_value >= events[-1].metric_value


def test_reddit_jsonl_rows(offline_config, tmp_path):
    dump = tmp_path / "sample.jsonl"
    records = [
        {"subreddit": "politics", "created_utc": 1767312000, "title": "x", "url": "https://bbc.com/a"},
        {"subreddit": "AskScience", "created_utc": 1767312500, "body": "a comment"},
    ]
    dump.write_text("\n".join(json.dumps(r) for r in records))
    events = reddit.ingest(input_path=dump, config=offline_config)
    sources = {e.source for e in events}
    assert sources == {"reddit"}
    metrics = {e.metric_name for e in events}
    # A post, a comment, and a link-share to bbc.com.
    assert "posts" in metrics
    assert "comments" in metrics
    assert "link_shares" in metrics
    shared = [e for e in events if e.metric_name == "link_shares"][0]
    assert shared.domain == "bbc.com"


def test_event_validation_rejects_unknown_signal():
    with pytest.raises(Exception):
        AttentionEvent(
            source="x",
            attention_signal="bogus_attention",
            date="2026-01-01",
            metric_name="views",
            metric_value=1.0,
        )

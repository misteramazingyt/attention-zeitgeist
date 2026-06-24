"""Common Crawl web-graph connector (structural_attention).

Common Crawl publishes a host- and domain-level web graph with harmonic
centrality and PageRank rankings (the ``cc-main-*-domain-ranks`` files). These
ship as tab-separated ``.txt.gz`` files shaped roughly:

    harmonicc_pos  harmonicc_val  pr_pos  pr_val  #host_rev

where ``#host_rev`` is the reversed host (``com.example``). This connector
parses a downloaded/decompressed ranks file into structural-attention events
keyed by registrable domain, using inverse harmonic-centrality position as the
metric.

This is the lowest-priority source (large, supply-side rather than usage), so
it operates purely on a local file you provide.
"""

from __future__ import annotations

import gzip
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

from ..config import Config, get_config
from ..schemas import AttentionEvent, AttentionSignal
from ..utils.dates import parse_date
from ..utils.logging import get_logger
from ..utils.urls import parse_domain
from ._common import store_raw

logger = get_logger(__name__)


def _open_text(path: Path) -> Iterator[str]:
    """Yield decoded lines from a plain or gzip-compressed text file."""
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            yield from fh
    else:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            yield from fh


def _unreverse_host(rev: str) -> str:
    """Convert a reversed host (``com.example.www``) to normal order."""
    parts = [p for p in rev.strip().split(".") if p]
    return ".".join(reversed(parts))


def ingest(
    input_path: str | Path,
    as_of: str | date | None = None,
    limit: int | None = 100_000,
    config: Config | None = None,
) -> list[AttentionEvent]:
    """Ingest a Common Crawl domain-ranks file.

    Args:
        input_path: Path to a ``cc-main-*-domain-ranks.txt`` (optionally
            ``.gz``) file.
        as_of: Date to attribute the snapshot to. Defaults to today.
        limit: Maximum number of top domains to ingest (the files are huge).
            Pass ``None`` to ingest everything.
        config: Optional config; defaults to the cached config.

    Returns:
        A list of normalized :class:`AttentionEvent` rows.
    """
    cfg = config or get_config()
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Common Crawl input not found: {path}")
    snapshot_date = parse_date(as_of) if as_of else datetime.now().date()

    store_raw(
        "commoncrawl",
        f"{path.stem}.source.txt",
        f"ingested from {path.resolve()} (limit={limit})\n".encode(),
        cfg,
    )

    events: list[AttentionEvent] = []
    seen = 0
    for line in _open_text(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 5:
            continue
        try:
            harmonic_pos = int(fields[0])
        except ValueError:
            continue
        host = _unreverse_host(fields[4])
        parts = parse_domain(host)
        reg = parts.registrable_domain or host
        if not reg:
            continue
        events.append(
            AttentionEvent(
                source="commoncrawl",
                attention_signal=AttentionSignal.STRUCTURAL.value,
                timestamp=datetime(snapshot_date.year, snapshot_date.month, snapshot_date.day),
                date=snapshot_date,
                url=None,
                domain=reg,
                subdomain=parts.subdomain or None,
                path=None,
                entity_id=reg,
                entity_label=reg,
                entity_type="domain",
                metric_name="inverse_harmonic_rank",
                metric_value=1.0 / max(1, harmonic_pos),
                raw_payload_path=None,
            )
        )
        seen += 1
        if limit is not None and seen >= limit:
            break

    logger.info("Common Crawl: %d domains from %s", len(events), path.name)
    return events

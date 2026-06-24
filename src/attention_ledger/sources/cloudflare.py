"""Cloudflare Radar connector (rank_attention).

Cloudflare Radar publishes domain popularity rankings (and, via its API,
category labels and rank movement). The free CSV export mirrors Tranco's
shape (``rank,domain`` or ``domain,rank,categories``), so this connector
parses a downloaded Radar CSV into rank-attention events.

Live API access requires a Cloudflare API token; this connector therefore
focuses on the offline CSV path, which needs no credentials.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from io import StringIO
from pathlib import Path

from ..config import Config, get_config
from ..schemas import AttentionEvent, AttentionSignal
from ..utils.dates import parse_date
from ..utils.logging import get_logger
from ..utils.urls import parse_domain
from ._common import store_raw

logger = get_logger(__name__)


def parse_rows(text: str) -> list[tuple[int, str, str | None]]:
    """Parse a Cloudflare Radar CSV into ``(rank, domain, category)`` tuples.

    Handles header rows and flexible column ordering by inspecting the header
    names when present; otherwise assumes ``rank,domain[,categories]``.
    """
    reader = csv.reader(StringIO(text))
    all_rows = [r for r in reader if r]
    if not all_rows:
        return []

    header = [c.strip().lower() for c in all_rows[0]]
    has_header = any(h in {"rank", "domain", "categories", "category"} for h in header)
    rank_idx, domain_idx, cat_idx = 0, 1, None
    if has_header:
        if "rank" in header:
            rank_idx = header.index("rank")
        if "domain" in header:
            domain_idx = header.index("domain")
        for cand in ("categories", "category"):
            if cand in header:
                cat_idx = header.index(cand)
                break
        body = all_rows[1:]
    else:
        body = all_rows

    out: list[tuple[int, str, str | None]] = []
    for pos, row in enumerate(body, start=1):
        try:
            rank = int(row[rank_idx]) if len(row) > rank_idx and row[rank_idx].strip().isdigit() else pos
        except (ValueError, IndexError):
            rank = pos
        domain = row[domain_idx].strip() if len(row) > domain_idx else ""
        category = (
            row[cat_idx].strip() if cat_idx is not None and len(row) > cat_idx else None
        )
        if domain:
            out.append((rank, domain, category or None))
    return out


def ingest(
    input_path: str | Path,
    as_of: str | date | None = None,
    config: Config | None = None,
) -> list[AttentionEvent]:
    """Ingest a Cloudflare Radar domain-ranking CSV.

    Args:
        input_path: Path to a Radar CSV export.
        as_of: Date to attribute the ranking to. Defaults to today.
        config: Optional config; defaults to the cached config.

    Returns:
        A list of normalized :class:`AttentionEvent` rows.
    """
    cfg = config or get_config()
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Cloudflare Radar input not found: {path}")
    snapshot_date = parse_date(as_of) if as_of else datetime.now().date()

    text = path.read_text()
    raw_path = store_raw("cloudflare", path.name, text.encode(), cfg)
    rows = parse_rows(text)
    if not rows:
        raise ValueError(f"No usable rows parsed from Cloudflare file {path}")

    events: list[AttentionEvent] = []
    for rank, domain, category in rows:
        parts = parse_domain(domain)
        reg = parts.registrable_domain or domain
        events.append(
            AttentionEvent(
                source="cloudflare",
                attention_signal=AttentionSignal.RANK.value,
                timestamp=datetime(snapshot_date.year, snapshot_date.month, snapshot_date.day),
                date=snapshot_date,
                url=None,
                domain=reg,
                subdomain=parts.subdomain or None,
                path=None,
                entity_id=reg,
                entity_label=category or reg,
                entity_type="domain",
                metric_name="inverse_rank",
                metric_value=1.0 / rank,
                raw_payload_path=str(raw_path),
            )
        )
    logger.info("Cloudflare: %d ranked domains as of %s", len(events), snapshot_date)
    return events

"""Tranco connector (rank_attention).

Tranco publishes a research-oriented ranked list of the most popular domains.
The list ships as a CSV of ``rank,domain``. We convert each rank into an
attention metric: ``metric_value = 1 / rank`` (so rank 1 carries the most
weight) while preserving the raw rank in the entity fields.

If no input file exists and ``--demo`` is requested, a small built-in
top-domain list is written and used so the demo runs offline.
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

# Built-in demo list (broadly representative of top global domains).
_DEMO_TOP_DOMAINS = [
    "google.com", "youtube.com", "facebook.com", "wikipedia.org", "amazon.com",
    "reddit.com", "instagram.com", "x.com", "tiktok.com", "netflix.com",
    "nytimes.com", "bbc.com", "cnn.com", "apple.com", "microsoft.com",
    "openai.com", "github.com", "bing.com", "yahoo.com", "linkedin.com",
    "pornhub.com", "espn.com", "bloomberg.com", "twitch.tv", "spotify.com",
]


def write_demo_csv(path: Path) -> Path:
    """Write the built-in demo Tranco list to ``path`` and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        for i, dom in enumerate(_DEMO_TOP_DOMAINS, start=1):
            writer.writerow([i, dom])
    logger.info("Wrote demo Tranco CSV with %d domains to %s", len(_DEMO_TOP_DOMAINS), path)
    return path


def parse_rows(text: str) -> list[tuple[int, str]]:
    """Parse Tranco CSV text into ``(rank, domain)`` tuples.

    Tolerates an optional header row and either ``rank,domain`` or bare
    ``domain`` (in which case position is used as rank).

    Args:
        text: Raw CSV content.

    Returns:
        A list of ``(rank, domain)`` tuples.
    """
    rows: list[tuple[int, str]] = []
    reader = csv.reader(StringIO(text))
    for pos, fields in enumerate(reader, start=1):
        if not fields:
            continue
        if len(fields) >= 2:
            rank_raw, domain = fields[0].strip(), fields[1].strip()
            if rank_raw.lower() == "rank":  # header
                continue
            try:
                rank = int(rank_raw)
            except ValueError:
                continue
        else:
            domain = fields[0].strip()
            if domain.lower() == "domain":
                continue
            rank = pos
        if domain:
            rows.append((rank, domain))
    return rows


def ingest(
    input_path: str | Path | None = None,
    as_of: str | date | None = None,
    demo: bool = False,
    config: Config | None = None,
) -> list[AttentionEvent]:
    """Ingest a Tranco ranked-domain CSV.

    Args:
        input_path: Path to a Tranco CSV. If missing and ``demo`` is True (or
            config offline mode is on), a demo CSV is generated at this path
            (or a default location).
        as_of: Date to attribute the ranking to. Defaults to today.
        demo: Force generation of the built-in demo list if input is absent.
        config: Optional config; defaults to the cached config.

    Returns:
        A list of normalized :class:`AttentionEvent` rows.
    """
    cfg = config or get_config()
    snapshot_date = parse_date(as_of) if as_of else datetime.now().date()

    path = Path(input_path) if input_path else (cfg.raw_dir / "tranco" / "tranco_demo.csv")
    if not path.exists():
        if demo or cfg.offline:
            write_demo_csv(path)
        else:
            raise FileNotFoundError(
                f"Tranco input not found: {path}. Pass --demo to generate a sample list."
            )

    text = path.read_text()
    raw_path = store_raw("tranco", path.name, text.encode(), cfg)
    rows = parse_rows(text)
    if not rows:
        raise ValueError(f"No usable rows parsed from Tranco file {path}")

    events: list[AttentionEvent] = []
    for rank, domain in rows:
        parts = parse_domain(domain)
        reg = parts.registrable_domain or domain
        events.append(
            AttentionEvent(
                source="tranco",
                attention_signal=AttentionSignal.RANK.value,
                timestamp=datetime(snapshot_date.year, snapshot_date.month, snapshot_date.day),
                date=snapshot_date,
                url=None,
                domain=reg,
                subdomain=parts.subdomain or None,
                path=None,
                entity_id=reg,
                entity_label=reg,
                entity_type="domain",
                metric_name="inverse_rank",
                # Inverse rank: higher = more popular. Preserves ordering while
                # giving the score step a positive, log-friendly quantity.
                metric_value=1.0 / rank,
                raw_payload_path=str(raw_path),
            )
        )
    logger.info("Tranco: %d ranked domains as of %s", len(events), snapshot_date)
    return events

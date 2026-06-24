"""Reddit connector (discursive_attention).

Parses Reddit public dumps / Pushshift-style exports. Supports ``.jsonl``,
``.jsonl.zst``, ``.csv``, and ``.parquet`` inputs containing submissions and/or
comments. For each record we emit:

* one ``posts``/``comments`` discursive event attributed to the subreddit, and
* (for submissions with an external link) one ``link_shares`` event attributed
  to the shared external domain — capturing which domains circulate inside
  Reddit.

The parser is tolerant of the heterogeneous field names found across dump
vintages (``created_utc`` vs ``created``, ``subreddit`` vs ``sr``, etc.).
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from ..config import Config, get_config
from ..schemas import AttentionEvent, AttentionSignal
from ..utils.logging import get_logger
from ..utils.urls import parse_domain
from ._common import store_raw

logger = get_logger(__name__)

_REDDIT_INTERNAL = {"reddit.com", "redd.it", "redditmedia.com"}


def _iter_records(path: Path) -> Iterator[dict[str, Any]]:
    """Yield record dicts from a Reddit dump in a supported format."""
    suffix = "".join(path.suffixes).lower()
    if suffix.endswith(".jsonl.zst") or suffix.endswith(".json.zst") or path.suffix == ".zst":
        yield from _iter_zst_jsonl(path)
    elif path.suffix == ".jsonl" or path.suffix == ".ndjson":
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)
    elif path.suffix == ".csv":
        with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            yield from csv.DictReader(fh)
    elif path.suffix == ".parquet":
        import polars as pl

        for row in pl.read_parquet(path).iter_rows(named=True):
            yield row
    else:
        raise ValueError(
            f"Unsupported Reddit input format: {path.name} "
            "(expected .jsonl, .jsonl.zst, .csv, or .parquet)"
        )


def _iter_zst_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Stream-decompress a zstandard-compressed JSONL file."""
    import io

    import zstandard as zstd

    dctx = zstd.ZstdDecompressor(max_window_size=2**31)
    with path.open("rb") as fh:
        with dctx.stream_reader(fh) as reader:
            text = io.TextIOWrapper(reader, encoding="utf-8", errors="replace")
            for line in text:
                line = line.strip()
                if line:
                    yield json.loads(line)


def _to_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _record_date(rec: dict[str, Any]) -> tuple[date, datetime] | None:
    """Extract a (date, datetime) from common Reddit timestamp fields."""
    raw = rec.get("created_utc", rec.get("created"))
    ts = _to_int(raw)
    if ts is None:
        return None
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
    return dt.date(), dt


def _is_comment(rec: dict[str, Any]) -> bool:
    """Heuristically classify a record as a comment vs a submission."""
    if "body" in rec and "title" not in rec:
        return True
    kind = str(rec.get("kind", "")).lower()
    if kind == "t1":
        return True
    if kind == "t3":
        return False
    # Submissions carry a title; comments carry a body.
    return "title" not in rec and "body" in rec


def ingest(input_path: str | Path, config: Config | None = None) -> list[AttentionEvent]:
    """Ingest a Reddit dump file into normalized attention events.

    Args:
        input_path: Path to a ``.jsonl``, ``.jsonl.zst``, ``.csv``, or
            ``.parquet`` Reddit dump.
        config: Optional config; defaults to the cached config.

    Returns:
        A list of normalized :class:`AttentionEvent` rows.
    """
    cfg = config or get_config()
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Reddit input not found: {path}")

    # Record provenance: note the source file rather than copying potentially
    # huge dumps into data/raw.
    raw_note = store_raw(
        "reddit",
        f"{path.stem}.source.txt",
        f"ingested from {path.resolve()}\n".encode(),
        cfg,
    )

    events: list[AttentionEvent] = []
    skipped = 0
    for rec in _iter_records(path):
        dd = _record_date(rec)
        if dd is None:
            skipped += 1
            continue
        day, dt = dd
        subreddit = (
            rec.get("subreddit") or rec.get("sr") or rec.get("subreddit_name_prefixed") or "unknown"
        )
        subreddit = str(subreddit).removeprefix("r/").strip() or "unknown"
        is_comment = _is_comment(rec)
        metric_name = "comments" if is_comment else "posts"
        entity_type = "subreddit"

        events.append(
            AttentionEvent(
                source="reddit",
                attention_signal=AttentionSignal.DISCURSIVE.value,
                timestamp=dt,
                date=day,
                url=None,
                domain="reddit.com",
                subdomain=None,
                path=f"/r/{subreddit}",
                entity_id=f"r/{subreddit}",
                entity_label=subreddit,
                entity_type=entity_type,
                metric_name=metric_name,
                metric_value=1.0,
                raw_payload_path=str(raw_note),
            )
        )

        # External link circulation (submissions only).
        if not is_comment:
            link = rec.get("url") or rec.get("url_overridden_by_dest")
            if link:
                parts = parse_domain(link)
                reg = parts.registrable_domain
                if reg and reg not in _REDDIT_INTERNAL:
                    events.append(
                        AttentionEvent(
                            source="reddit",
                            attention_signal=AttentionSignal.DISCURSIVE.value,
                            timestamp=dt,
                            date=day,
                            url=str(link),
                            domain=reg,
                            subdomain=parts.subdomain or None,
                            path=None,
                            entity_id=reg,
                            entity_label=reg,
                            entity_type="shared_domain",
                            metric_name="link_shares",
                            metric_value=1.0,
                            raw_payload_path=str(raw_note),
                        )
                    )

    if skipped:
        logger.warning("Reddit: skipped %d records lacking a usable timestamp", skipped)
    logger.info("Reddit: produced %d events from %s", len(events), path.name)
    return events

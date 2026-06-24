"""GDELT connector (news_attention).

Queries the GDELT DOC 2.0 API for matching news articles, normalizes their
source domains, and emits one :class:`AttentionEvent` per article with
``metric_name="article_count"`` and ``metric_value=1`` (aggregation to daily
domain counts happens in the build step).

In offline mode, a deterministic synthetic article stream is generated across a
fixed set of news domains.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from ..config import Config, get_config
from ..schemas import AttentionEvent, AttentionSignal
from ..utils.dates import compact, date_range, to_iso
from ..utils.logging import get_logger
from ..utils.urls import parse_domain
from ._common import http_get, store_raw

logger = get_logger(__name__)

_DEMO_DOMAINS = [
    "nytimes.com", "bbc.com", "cnn.com", "theguardian.com", "reuters.com",
    "foxnews.com", "washingtonpost.com", "aljazeera.com", "apnews.com",
    "techcrunch.com", "wired.com", "bloomberg.com",
]


def _synthesize_articles(day: date, query: str) -> list[dict[str, Any]]:
    """Return a deterministic synthetic article list for a day."""
    seed = day.toordinal()
    articles = []
    for i, dom in enumerate(_DEMO_DOMAINS):
        # number of articles for this domain on this day
        n = 3 + ((seed + i * 5) % 7)
        for j in range(n):
            articles.append(
                {
                    "url": f"https://www.{dom}/{day.isoformat()}/story-{i}-{j}",
                    "domain": dom,
                    "seendate": f"{compact(day)}T12{i:02d}00Z",
                    "title": f"{query} coverage {i}-{j}",
                }
            )
    return articles


def _fetch_articles(day: date, query: str, config: Config) -> tuple[list[dict], bytes]:
    """Fetch GDELT articles for a single day matching ``query``."""
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": "250",
        "startdatetime": f"{compact(day)}000000",
        "enddatetime": f"{compact(day)}235959",
        "sort": "hybridrel",
    }
    resp = http_get(config.gdelt_api, params=params, config=config)
    raw = resp.content
    try:
        payload = resp.json()
    except json.JSONDecodeError:
        # GDELT occasionally returns empty/non-JSON bodies for sparse queries.
        logger.warning("GDELT returned non-JSON for %s; treating as empty", to_iso(day))
        return [], raw
    return payload.get("articles", []) or [], raw


def ingest(
    start: str | date,
    end: str | date,
    query: str,
    config: Config | None = None,
) -> list[AttentionEvent]:
    """Ingest GDELT news articles for a date range and query.

    Args:
        start: Inclusive start date (YYYY-MM-DD).
        end: Inclusive end date (YYYY-MM-DD).
        query: GDELT query string, e.g. ``"AI OR artificial intelligence"``.
        config: Optional config; defaults to the cached config.

    Returns:
        A list of normalized :class:`AttentionEvent` rows (one per article).
    """
    cfg = config or get_config()
    events: list[AttentionEvent] = []

    for day in date_range(start, end):
        if cfg.offline:
            articles = _synthesize_articles(day, query)
            raw_path = store_raw(
                "gdelt",
                f"artlist_{compact(day)}_offline.json",
                json.dumps({"articles": articles}).encode(),
                cfg,
            )
        else:
            try:
                articles, raw = _fetch_articles(day, query, cfg)
            except Exception as exc:  # noqa: BLE001
                logger.error("GDELT fetch failed for %s: %s", to_iso(day), exc)
                raise
            raw_path = store_raw("gdelt", f"artlist_{compact(day)}.json", raw, cfg)

        for art in articles:
            url = art.get("url", "")
            parts = parse_domain(art.get("domain") or url)
            if not parts.registrable_domain:
                continue
            ts = _parse_seendate(art.get("seendate")) or datetime(day.year, day.month, day.day)
            events.append(
                AttentionEvent(
                    source="gdelt",
                    attention_signal=AttentionSignal.NEWS.value,
                    timestamp=ts,
                    date=day,
                    url=url or None,
                    domain=parts.registrable_domain,
                    subdomain=parts.subdomain or None,
                    path=None,
                    entity_id=parts.registrable_domain,
                    entity_label=art.get("title") or parts.registrable_domain,
                    entity_type="news_article",
                    metric_name="article_count",
                    metric_value=1.0,
                    raw_payload_path=str(raw_path),
                )
            )
        logger.info("GDELT %s: %d articles", to_iso(day), len(articles))

    return events


def _parse_seendate(value: str | None) -> datetime | None:
    """Parse a GDELT ``seendate`` (``YYYYMMDDTHHMMSSZ``) into a datetime."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ")
    except ValueError:
        return None

"""Wikimedia Pageviews connector (pageview_attention).

Uses the public Wikimedia REST API ``metrics/pageviews/top`` endpoint to fetch
the most-viewed articles per project per day. Each article-day becomes one
:class:`AttentionEvent` with ``metric_name="views"``.

In offline mode a deterministic synthetic top-article list is generated so the
demo pipeline runs without network access.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Iterable

from ..config import Config, get_config
from ..schemas import AttentionEvent, AttentionSignal
from ..utils.dates import compact, date_range, to_iso
from ..utils.logging import get_logger
from ._common import http_get, store_raw

logger = get_logger(__name__)

# A small fixed catalogue used to synthesize offline demo data. The mix spans
# several topical domains so downstream classification has something to chew on.
_DEMO_ARTICLES = [
    "Artificial_intelligence", "ChatGPT", "Donald_Trump", "Taylor_Swift",
    "Israel", "Buddhism", "Bitcoin", "Climate_change", "World_War_II",
    "Elon_Musk", "India", "Football", "Quantum_computing", "Christianity",
    "Stock_market", "OpenAI", "Large_language_model", "Ukraine",
    "Cristiano_Ronaldo", "Apple_Inc.",
]


def _synthesize_top(day: date, project: str) -> list[dict]:
    """Return a deterministic synthetic 'top articles' list for a day.

    Values vary by day-of-year and article index so time series have texture
    without any randomness (keeping the demo reproducible).
    """
    seed = day.toordinal()
    articles = []
    for i, name in enumerate(_DEMO_ARTICLES):
        base = 100_000 - i * 3_500
        wobble = ((seed + i * 7) % 11) * 1_500
        views = max(500, base + wobble)
        articles.append({"article": name, "views": views, "rank": i + 1})
    return articles


def _fetch_top(day: date, project: str, access: str, config: Config) -> tuple[list[dict], bytes]:
    """Fetch the top-viewed articles for a project on a given day.

    Returns:
        A ``(items, raw_bytes)`` tuple where ``items`` is the list of article
        dicts and ``raw_bytes`` is the original payload for raw storage.
    """
    url = (
        f"{config.wiki_api}/metrics/pageviews/top/"
        f"{project}/{access}/{day.year}/{day.month:02d}/{day.day:02d}"
    )
    resp = http_get(url, config=config)
    raw = resp.content
    payload = resp.json()
    items = payload.get("items", [])
    articles = items[0].get("articles", []) if items else []
    return articles, raw


def ingest(
    start: str | date,
    end: str | date,
    project: str | None = None,
    access: str = "all-access",
    config: Config | None = None,
) -> list[AttentionEvent]:
    """Ingest Wikimedia top pageviews for a date range.

    Args:
        start: Inclusive start date (YYYY-MM-DD).
        end: Inclusive end date (YYYY-MM-DD).
        project: Wikimedia project, e.g. ``en.wikipedia``. Defaults to config.
        access: One of ``all-access``, ``desktop``, ``mobile-web``,
            ``mobile-app``.
        config: Optional config; defaults to the cached config.

    Returns:
        A list of normalized :class:`AttentionEvent` rows.
    """
    cfg = config or get_config()
    project = project or cfg.wiki_project
    events: list[AttentionEvent] = []

    for day in date_range(start, end):
        if cfg.offline:
            articles = _synthesize_top(day, project)
            raw_path = store_raw(
                "wikimedia",
                f"top_{project}_{compact(day)}_offline.json",
                json.dumps({"items": [{"articles": articles}]}).encode(),
                cfg,
            )
        else:
            try:
                articles, raw = _fetch_top(day, project, access, cfg)
            except Exception as exc:  # noqa: BLE001 - surface, don't swallow
                logger.error("Wikimedia fetch failed for %s %s: %s", project, to_iso(day), exc)
                raise
            raw_path = store_raw(
                "wikimedia", f"top_{project}_{compact(day)}.json", raw, cfg
            )

        for art in articles:
            name = art.get("article", "")
            if not name or name in {"Main_Page", "Special:Search"}:
                continue
            views = float(art.get("views", 0) or 0)
            events.append(
                AttentionEvent(
                    source="wikimedia",
                    attention_signal=AttentionSignal.PAGEVIEW.value,
                    timestamp=datetime(day.year, day.month, day.day),
                    date=day,
                    url=f"https://{project.replace('.', '.')}.org/wiki/{name}",
                    domain=f"{project}.org",
                    subdomain=project.split(".")[0] if "." in project else None,
                    path=f"/wiki/{name}",
                    entity_id=f"{project}:{name}",
                    entity_label=name.replace("_", " "),
                    entity_type="wikipedia_article",
                    metric_name="views",
                    metric_value=views,
                    raw_payload_path=str(raw_path),
                )
            )
        logger.info("Wikimedia %s %s: %d articles", project, to_iso(day), len(articles))

    return events


def aggregate_counts(events: Iterable[AttentionEvent]) -> dict[str, float]:
    """Sum views per article label (helper for quick inspection/testing)."""
    out: dict[str, float] = {}
    for ev in events:
        key = ev.entity_label or ev.entity_id or ev.url or "unknown"
        out[key] = out.get(key, 0.0) + ev.metric_value
    return out

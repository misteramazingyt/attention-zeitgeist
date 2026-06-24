"""Pydantic schemas and shared enumerations for the attention ledger.

These define the canonical data model: the ``attention_signal`` taxonomy,
source identifiers, the default classification categories, and validated
row models for normalized attention events. Connectors emit
:class:`AttentionEvent` rows; everything downstream relies on these
guarantees (non-empty source, known signal type, finite metric value).
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class AttentionSignal(str, Enum):
    """The plural taxonomy of attention proxies.

    Each signal is a fundamentally different measurement and must never be
    collapsed with another without preserving source-level scores.
    """

    PAGEVIEW = "pageview_attention"      # visits/views, e.g. Wikipedia
    DISCURSIVE = "discursive_attention"  # posts/comments, e.g. Reddit
    NEWS = "news_attention"              # article publication/circulation, e.g. GDELT
    RANK = "rank_attention"              # relative popularity rank, e.g. Tranco/Cloudflare
    STRUCTURAL = "structural_attention"  # link/inlink centrality, e.g. Common Crawl


class Source(str, Enum):
    """Recognized data sources."""

    WIKIMEDIA = "wikimedia"
    REDDIT = "reddit"
    GDELT = "gdelt"
    TRANCO = "tranco"
    CLOUDFLARE = "cloudflare"
    COMMONCRAWL = "commoncrawl"


# Mapping from source to its primary attention signal. A source may emit other
# signals, but this is the default it contributes to the composite index.
SOURCE_SIGNAL: dict[str, str] = {
    Source.WIKIMEDIA.value: AttentionSignal.PAGEVIEW.value,
    Source.REDDIT.value: AttentionSignal.DISCURSIVE.value,
    Source.GDELT.value: AttentionSignal.NEWS.value,
    Source.TRANCO.value: AttentionSignal.RANK.value,
    Source.CLOUDFLARE.value: AttentionSignal.RANK.value,
    Source.COMMONCRAWL.value: AttentionSignal.STRUCTURAL.value,
}

# Composite-index score column for each signal.
SIGNAL_SCORE_COLUMN: dict[str, str] = {
    AttentionSignal.PAGEVIEW.value: "pageview_score",
    AttentionSignal.DISCURSIVE.value: "discursive_score",
    AttentionSignal.NEWS.value: "news_score",
    AttentionSignal.RANK.value: "rank_score",
    AttentionSignal.STRUCTURAL.value: "structural_score",
}

# Default rule-based classification categories.
DEFAULT_CATEGORIES: list[str] = [
    "politics",
    "news",
    "entertainment",
    "sports",
    "religion",
    "education",
    "reference",
    "technology",
    "commerce",
    "finance",
    "pornography",
    "gaming",
    "health",
    "science",
    "social media",
    "forums",
    "AI",
    "miscellaneous",
]


class AttentionEvent(BaseModel):
    """A single normalized attention observation.

    This is the atomic unit written to the ``attention_events`` table. One
    event is one (source, signal, entity, metric) measurement at a timestamp.
    """

    source: str = Field(..., description="Source identifier, e.g. 'wikimedia'.")
    attention_signal: str = Field(..., description="An AttentionSignal value.")
    timestamp: Optional[datetime] = Field(
        None, description="Full event timestamp, if available."
    )
    date: date_cls = Field(..., description="Calendar date of the observation.")
    url: Optional[str] = Field(None, description="Source URL, if any.")
    domain: Optional[str] = Field(None, description="Full host/domain.")
    subdomain: Optional[str] = Field(None, description="Subdomain component.")
    path: Optional[str] = Field(None, description="URL path component.")
    entity_id: Optional[str] = Field(None, description="Stable entity identifier.")
    entity_label: Optional[str] = Field(None, description="Human-readable entity label.")
    entity_type: Optional[str] = Field(
        None, description="e.g. wikipedia_article, subreddit, news_article, domain."
    )
    metric_name: str = Field(..., description="e.g. views, comments, article_count.")
    metric_value: float = Field(..., description="The measured value (>= 0 expected).")
    raw_payload_path: Optional[str] = Field(
        None, description="Path to the stored raw payload backing this event."
    )

    @field_validator("source", "attention_signal", "metric_name")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("must be a non-empty string")
        return str(v).strip()

    @field_validator("attention_signal")
    @classmethod
    def _known_signal(cls, v: str) -> str:
        valid = {s.value for s in AttentionSignal}
        if v not in valid:
            raise ValueError(f"unknown attention_signal {v!r}; expected one of {sorted(valid)}")
        return v

    @field_validator("metric_value")
    @classmethod
    def _finite_value(cls, v: float) -> float:
        if v != v or v in (float("inf"), float("-inf")):  # NaN/inf guard
            raise ValueError("metric_value must be finite")
        return float(v)


class IngestionRunLog(BaseModel):
    """A record of one ingestion run, persisted for auditability."""

    source: str
    started_at: datetime
    finished_at: datetime
    rows_written: int
    parameters: str
    status: str = "ok"
    message: str = ""

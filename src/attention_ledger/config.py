"""Central configuration for the attention ledger.

Configuration is resolved from environment variables (optionally loaded from a
``.env`` file) with conservative defaults so the project runs out of the box.
The :class:`Config` object is the single source of truth for filesystem paths,
API endpoints, and runtime flags such as offline mode.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

try:  # python-dotenv is a declared dependency but keep import resilient.
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional at runtime.
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    """Resolved runtime configuration.

    Attributes:
        data_dir: Root of the data tree (raw/interim/processed/exports).
        db_path: Path to the DuckDB database file.
        wiki_project: Default Wikimedia project for pageview ingestion.
        wiki_api: Wikimedia REST API base URL.
        gdelt_api: GDELT DOC 2.0 API base URL.
        http_timeout: HTTP request timeout in seconds.
        http_retries: Number of retry attempts for HTTP requests.
        offline: When true, network connectors emit synthetic demo data.
    """

    data_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("ATTENTION_LEDGER_DATA_DIR", "./data")
        ).resolve()
    )
    db_path: Path = field(
        default_factory=lambda: Path(
            os.environ.get(
                "ATTENTION_LEDGER_DB_PATH",
                "./data/processed/attention_ledger.duckdb",
            )
        ).resolve()
    )
    wiki_project: str = field(
        default_factory=lambda: os.environ.get(
            "ATTENTION_LEDGER_WIKI_PROJECT", "en.wikipedia"
        )
    )
    wiki_api: str = field(
        default_factory=lambda: os.environ.get(
            "ATTENTION_LEDGER_WIKI_API", "https://wikimedia.org/api/rest_v1"
        )
    )
    gdelt_api: str = field(
        default_factory=lambda: os.environ.get(
            "ATTENTION_LEDGER_GDELT_API",
            "https://api.gdeltproject.org/api/v2/doc/doc",
        )
    )
    http_timeout: float = field(
        default_factory=lambda: float(
            os.environ.get("ATTENTION_LEDGER_HTTP_TIMEOUT", "60")
        )
    )
    http_retries: int = field(
        default_factory=lambda: int(
            os.environ.get("ATTENTION_LEDGER_HTTP_RETRIES", "3")
        )
    )
    offline: bool = field(default_factory=lambda: _env_bool("ATTENTION_LEDGER_OFFLINE"))

    # --- Derived paths -------------------------------------------------
    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def interim_dir(self) -> Path:
        return self.data_dir / "interim"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    def ensure_dirs(self) -> None:
        """Create the full data directory tree if it does not yet exist."""
        for d in (self.raw_dir, self.interim_dir, self.processed_dir, self.exports_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def raw_source_dir(self, source: str) -> Path:
        """Return (and create) the raw-storage directory for a given source."""
        d = self.raw_dir / source
        d.mkdir(parents=True, exist_ok=True)
        return d


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Return a process-wide cached :class:`Config` instance."""
    return Config()

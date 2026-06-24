"""Shared connector helpers: HTTP with retries and raw-payload storage.

Keeping these in one place ensures every connector retries transient network
errors consistently and always persists the raw bytes it received before
transforming them (so a parse bug never destroys the original data).
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from ..config import Config, get_config
from ..utils.logging import get_logger

logger = get_logger(__name__)


def http_get(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    config: Config | None = None,
) -> httpx.Response:
    """Perform a GET request with retries and exponential backoff.

    Args:
        url: Target URL.
        params: Optional query parameters.
        headers: Optional headers (a default User-Agent is added).
        config: Optional config; defaults to the cached config.

    Returns:
        The successful :class:`httpx.Response`.

    Raises:
        httpx.HTTPError: If all retry attempts fail.
    """
    cfg = config or get_config()
    hdrs = {"User-Agent": "attention-ledger/0.1 (research; +local)"}
    if headers:
        hdrs.update(headers)

    last_exc: Exception | None = None
    for attempt in range(1, cfg.http_retries + 1):
        try:
            resp = httpx.get(
                url, params=params, headers=hdrs, timeout=cfg.http_timeout, follow_redirects=True
            )
            resp.raise_for_status()
            return resp
        except httpx.HTTPError as exc:
            last_exc = exc
            wait = 2 ** attempt
            logger.warning(
                "HTTP GET failed (attempt %d/%d) for %s: %s; retrying in %ds",
                attempt,
                cfg.http_retries,
                url,
                exc,
                wait,
            )
            if attempt < cfg.http_retries:
                time.sleep(wait)
    assert last_exc is not None
    raise last_exc


def store_raw(source: str, name: str, content: bytes, config: Config | None = None) -> Path:
    """Persist a raw payload under ``data/raw/<source>/<name>``.

    Args:
        source: Source identifier (subdirectory name).
        name: Filename for the payload.
        content: Raw bytes to write.
        config: Optional config; defaults to the cached config.

    Returns:
        The path the payload was written to.
    """
    cfg = config or get_config()
    dest = cfg.raw_source_dir(source) / name
    dest.write_bytes(content)
    logger.debug("Stored raw payload %s (%d bytes)", dest, len(content))
    return dest

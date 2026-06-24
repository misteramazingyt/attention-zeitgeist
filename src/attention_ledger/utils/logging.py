"""Logging helpers for the attention ledger.

Provides a single configured logger factory so that every ingestion run and
transform emits consistent, timestamped log lines. We deliberately avoid
silent failures: connectors should log what they fetch, how many rows they
produced, and any rows they had to skip.
"""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


def configure_logging(level: str | None = None) -> None:
    """Configure the root logger once for the whole process.

    Args:
        level: Optional log level name (e.g. ``"INFO"``). If omitted, the
            ``ATTENTION_LEDGER_LOG_LEVEL`` environment variable is consulted,
            defaulting to ``INFO``.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    level_name = (level or os.environ.get("ATTENTION_LEDGER_LOG_LEVEL", "INFO")).upper()
    log_level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger, configuring logging on first use.

    Args:
        name: Logger name, typically ``__name__`` of the calling module.

    Returns:
        A :class:`logging.Logger` instance.
    """
    configure_logging()
    return logging.getLogger(name)

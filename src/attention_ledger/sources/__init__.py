"""Data source connectors.

Each connector is independently testable and exposes an ``ingest(...)``
function returning a list of :class:`~attention_ledger.schemas.AttentionEvent`.
Connectors store raw payloads under ``data/raw/<source>/`` before transforming
them, and never silently swallow errors.

To add a new source, create ``sources/<name>.py`` with an ``ingest`` function,
register it in ``cli.py``, and (optionally) add a ``SOURCE_SIGNAL`` entry in
``schemas.py``.
"""

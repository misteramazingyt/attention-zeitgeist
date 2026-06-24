"""Populate and normalize the ``domains`` table.

Ensures every domain seen in ``attention_events`` has a ``domains`` row with
its registrable domain, subdomain, and TLD decomposed via the shared URL
utilities. Classification (platform/category labels) is applied separately in
:mod:`classify_topics`.
"""

from __future__ import annotations

from ..storage import Storage
from ..utils.logging import get_logger
from ..utils.urls import parse_domain

logger = get_logger(__name__)


def normalize_domains(storage: Storage) -> int:
    """Decompose every ``domains`` row into registrable_domain/subdomain/tld.

    First ensures rows exist for all event domains, then fills in structural
    components for any row missing them.

    Args:
        storage: An open :class:`Storage`.

    Returns:
        The number of domain rows updated.
    """
    storage.upsert_domains_from_events()
    rows = storage.con.execute(
        "SELECT domain_id, domain FROM domains WHERE domain IS NOT NULL"
    ).fetchall()

    updated = 0
    for domain_id, domain in rows:
        parts = parse_domain(domain)
        storage.con.execute(
            """
            UPDATE domains
            SET registrable_domain = ?, subdomain = ?, tld = ?, updated_at = now()
            WHERE domain_id = ?
            """,
            (parts.registrable_domain, parts.subdomain, parts.tld, domain_id),
        )
        updated += 1
    logger.info("Normalized %d domain rows", updated)
    return updated

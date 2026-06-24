"""URL and domain parsing helpers.

These functions implement the project's notion of a *registrable domain*
(eTLD+1), subdomain, and TLD using :mod:`tldextract`. Normalization here is
the backbone of cross-source joins: a Reddit-shared link, a GDELT article,
and a Tranco rank must all resolve to the same ``registrable_domain`` to be
comparable.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import tldextract

# Use the bundled snapshot so domain parsing works fully offline. This avoids
# a network round-trip to refresh the public-suffix list during ingestion.
_extractor = tldextract.TLDExtract(suffix_list_urls=())


@dataclass(frozen=True)
class DomainParts:
    """Structured decomposition of a host or URL into domain components."""

    domain: str
    registrable_domain: str
    subdomain: str
    tld: str


def normalize_host(value: str) -> str:
    """Lowercase a host/URL and strip scheme, path, port, and leading ``www.``.

    Args:
        value: A raw URL or bare hostname.

    Returns:
        A bare lowercase hostname, or an empty string if none could be found.
    """
    if not value:
        return ""
    value = value.strip()
    if "//" not in value:
        # Bare host or host/path; give urlparse a scheme to anchor on.
        candidate = "http://" + value
    else:
        candidate = value
    netloc = urlparse(candidate).netloc or ""
    host = netloc.split("@")[-1].split(":")[0].lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def parse_domain(value: str) -> DomainParts:
    """Decompose a URL or hostname into domain parts.

    Args:
        value: A raw URL or bare hostname.

    Returns:
        A :class:`DomainParts` instance. Fields are empty strings when the
        component is absent (e.g. no subdomain, or an unparseable input).
    """
    host = normalize_host(value)
    if not host:
        return DomainParts("", "", "", "")
    ext = _extractor(host)
    registrable = ".".join(p for p in (ext.domain, ext.suffix) if p)
    full = ".".join(p for p in (ext.subdomain, ext.domain, ext.suffix) if p)
    return DomainParts(
        domain=full or host,
        registrable_domain=registrable or host,
        subdomain=ext.subdomain,
        tld=ext.suffix,
    )


def registrable_domain(value: str) -> str:
    """Return just the registrable domain (eTLD+1) for a URL or host."""
    return parse_domain(value).registrable_domain


def url_path(value: str) -> str:
    """Return the path component of a URL (empty string if absent)."""
    if not value:
        return ""
    candidate = value if "//" in value else "http://" + value
    return urlparse(candidate).path or ""

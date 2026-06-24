"""Tests for URL parsing and domain normalization."""

from __future__ import annotations

import pytest

from attention_ledger.utils.urls import (
    normalize_host,
    parse_domain,
    registrable_domain,
    url_path,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://www.nytimes.com/2026/01/01/story", "nytimes.com"),
        ("http://EN.WIKIPEDIA.ORG/wiki/AI", "en.wikipedia.org"),
        ("bbc.com", "bbc.com"),
        ("https://news.bbc.co.uk:443/path?q=1", "news.bbc.co.uk"),
        ("", ""),
        ("ftp://user:pass@files.example.org/x", "files.example.org"),
    ],
)
def test_normalize_host(value, expected):
    assert normalize_host(value) == expected


@pytest.mark.parametrize(
    "value,registrable,subdomain,tld",
    [
        ("https://www.nytimes.com/x", "nytimes.com", "", "com"),
        ("https://news.bbc.co.uk/y", "bbc.co.uk", "news", "co.uk"),
        ("sub.deep.example.com", "example.com", "sub.deep", "com"),
        ("en.wikipedia.org", "wikipedia.org", "en", "org"),
    ],
)
def test_parse_domain(value, registrable, subdomain, tld):
    parts = parse_domain(value)
    assert parts.registrable_domain == registrable
    assert parts.subdomain == subdomain
    assert parts.tld == tld


def test_registrable_domain_helper():
    assert registrable_domain("https://m.youtube.com/watch?v=abc") == "youtube.com"


def test_url_path():
    assert url_path("https://example.com/a/b/c?x=1") == "/a/b/c"
    assert url_path("example.com") == ""


def test_reddit_and_gdelt_resolve_same_domain():
    # A link shared on Reddit and an article seen by GDELT must join.
    assert registrable_domain("https://www.theguardian.com/world/x") == registrable_domain(
        "theguardian.com"
    )

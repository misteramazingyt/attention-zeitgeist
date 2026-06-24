"""Tests for date parsing and validation."""

from __future__ import annotations

from datetime import date

import pytest

from attention_ledger.utils.dates import (
    compact,
    date_range,
    parse_date,
    to_iso,
    validate_range,
)


def test_parse_date_string():
    assert parse_date("2026-01-07") == date(2026, 1, 7)


def test_parse_date_passthrough():
    d = date(2025, 12, 31)
    assert parse_date(d) == d


@pytest.mark.parametrize("bad", ["2026/01/07", "07-01-2026", "not-a-date", "2026-13-01"])
def test_parse_date_invalid(bad):
    with pytest.raises(ValueError):
        parse_date(bad)


def test_validate_range_order():
    with pytest.raises(ValueError):
        validate_range("2026-01-10", "2026-01-01")


def test_date_range_inclusive():
    days = list(date_range("2026-01-01", "2026-01-03"))
    assert days == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]


def test_iso_and_compact():
    d = date(2026, 1, 7)
    assert to_iso(d) == "2026-01-07"
    assert compact(d) == "20260107"

"""Date parsing and validation helpers.

Centralizing date handling keeps connectors honest: every ingestion command
validates its date inputs through :func:`parse_date` and iterates days via
:func:`date_range`, so malformed dates fail loudly and early.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterator

DATE_FMT = "%Y-%m-%d"


def parse_date(value: str | date | datetime) -> date:
    """Parse and validate a date given as a string or date-like object.

    Args:
        value: A ``YYYY-MM-DD`` string, a :class:`datetime.date`, or a
            :class:`datetime.datetime`.

    Returns:
        A :class:`datetime.date`.

    Raises:
        ValueError: If a string cannot be parsed as ``YYYY-MM-DD``.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"Unsupported date value: {value!r}")
    try:
        return datetime.strptime(value.strip(), DATE_FMT).date()
    except ValueError as exc:
        raise ValueError(
            f"Invalid date {value!r}; expected format YYYY-MM-DD"
        ) from exc


def validate_range(start: str | date, end: str | date) -> tuple[date, date]:
    """Validate that ``start`` <= ``end`` and return parsed dates.

    Args:
        start: Inclusive start date.
        end: Inclusive end date.

    Returns:
        A ``(start_date, end_date)`` tuple.

    Raises:
        ValueError: If ``start`` is after ``end``.
    """
    s = parse_date(start)
    e = parse_date(end)
    if s > e:
        raise ValueError(f"start date {s} is after end date {e}")
    return s, e


def date_range(start: str | date, end: str | date) -> Iterator[date]:
    """Yield each date from ``start`` to ``end`` inclusive.

    Args:
        start: Inclusive start date.
        end: Inclusive end date.

    Yields:
        Consecutive :class:`datetime.date` values.
    """
    s, e = validate_range(start, end)
    current = s
    while current <= e:
        yield current
        current += timedelta(days=1)


def to_iso(d: date) -> str:
    """Return the ISO ``YYYY-MM-DD`` representation of a date."""
    return d.strftime(DATE_FMT)


def compact(d: date) -> str:
    """Return the compact ``YYYYMMDD`` representation (used by some APIs)."""
    return d.strftime("%Y%m%d")

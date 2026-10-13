"""Shared HTTP Retry-After parsing; retain valid long waits and conflicting Date headers."""

import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx2


def retry_after_seconds(
    value: str | None, date_header: str | None, *, received_at: datetime | None = None
) -> int | None:
    """Parse an upstream 429 delay without truncating valid long waits."""
    if value is None:
        return None
    value = value.strip()
    if value.isascii() and value.isdecimal():
        # Keep a JSON/JavaScript-safe integer; absurd larger values are unknown.
        if len(value) > 16:
            return None
        seconds = int(value)
        return seconds if seconds <= 2**53 - 1 else None

    def http_date(raw: str | None) -> datetime | None:
        try:
            parsed = parsedate_to_datetime(raw) if raw else None
        except (TypeError, ValueError, OverflowError):
            return None
        return parsed.astimezone(UTC) if parsed is not None and parsed.tzinfo else None

    deadline = http_date(value)
    if deadline is None:
        return None
    reference = http_date(date_header) or received_at or datetime.now(UTC)
    if reference.tzinfo is None:
        return None
    return max(0, math.ceil((deadline - reference).total_seconds()))


def retry_after_from_headers(headers: httpx2.Headers) -> int | None:
    """Conflicting Date headers must not shorten a valid upstream wait."""
    value = headers.get("retry-after")
    dates = headers.get_list("date")
    if not dates:
        return retry_after_seconds(value, None)
    waits = [retry_after_seconds(value, date) for date in dates]
    valid = [wait for wait in waits if wait is not None]
    return max(valid) if valid else None

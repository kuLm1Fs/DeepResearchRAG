"""Time helpers shared across API and logging code."""

from datetime import datetime, timezone


def utc_now_naive() -> datetime:
    """Return current UTC time as a naive datetime for existing DB columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_now_iso() -> str:
    """Return current UTC time as an ISO-8601 string with timezone."""
    return datetime.now(timezone.utc).isoformat()

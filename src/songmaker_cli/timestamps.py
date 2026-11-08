"""Shared UTC clock and reading of datetimes that arrive from outside the database."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware_timestamp(value: datetime) -> datetime:
    """Read a datetime whose zone may be missing as UTC, preserving explicit offsets."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value

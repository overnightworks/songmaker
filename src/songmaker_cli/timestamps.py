"""Shared UTC clock and database timestamp interpretation."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware_timestamp(value: datetime) -> datetime:
    """Interpret naive database timestamps as UTC, preserving explicit offsets."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value

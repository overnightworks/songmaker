"""UTC timestamps for worker model and task state."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)

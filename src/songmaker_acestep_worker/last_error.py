"""The most recent worker failure and its occurrence time."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class LastError:
    message: str
    at: datetime

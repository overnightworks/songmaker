"""Transaction-level advisory locks: the fixed ids and the one function that takes one."""

from __future__ import annotations

import enum

from sqlalchemy import text
from sqlalchemy.orm import Session


@enum.unique
class AdvisoryLock(enum.IntEnum):
    RATE_LIMIT = 1
    ALBUM_ID = 2
    SONG_SLUG = 5
    PLAYLIST_SLUG = 6
    COVER_SUGGESTIONS = 7
    LORA_CAPACITY = 8
    USER_MANAGEMENT = 9
    PURGE = 10


def lock_until_transaction_ends(session: Session, lock_id: int) -> None:
    """Take an exclusive advisory lock released on commit or rollback.

    Different ids serialize independently; a computed id is an `int`.
    """
    session.execute(text("SELECT pg_advisory_xact_lock(:id)").bindparams(id=int(lock_id)))

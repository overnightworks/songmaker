"""Global SQLAlchemy filter that hides soft-deleted Album and Song rows.

The do_orm_execute event listener appends with_loader_criteria to every
ORM SELECT (top-level and relationship loads) so soft-deleted rows are
invisible by default. Three call sites — restore_album, restore_song,
and the cleanup_expired periodic task — opt out by setting
execution_options(include_deleted=True). Code that needs to bypass the
filter for an entire block (e.g. hard_delete_user, where ORM cascade
walks relationships) uses the include_deleted() context manager, which
sets a session-level flag the listener checks.

This is the only safe approach. Manually filtering each query function
guarantees missed spots: 10+ entry points across albums.py, songs.py,
chat mention resolution, playlist traversal, sharing, and search.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from songmaker_cli.db.models import Album, Song

INCLUDE_DELETED_OPTION = "include_deleted"
_SESSION_FLAG = "include_deleted"


def _filter_soft_deleted(execute_state) -> None:
    if execute_state.execution_options.get(INCLUDE_DELETED_OPTION, False):
        return
    if execute_state.session.info.get(_SESSION_FLAG, False):
        return
    if not execute_state.is_select:
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            Album,
            lambda cls: cls.deleted_at.is_(None),
            include_aliases=True,
        ),
        with_loader_criteria(
            Song,
            lambda cls: cls.deleted_at.is_(None),
            include_aliases=True,
        ),
    )


def install_soft_delete_filter() -> None:
    """Register the do_orm_execute listener on the Session class.

    Idempotent — registering twice is harmless because the listener
    function is the same object both times.
    """
    if not event.contains(Session, "do_orm_execute", _filter_soft_deleted):
        event.listen(Session, "do_orm_execute", _filter_soft_deleted)


@contextmanager
def include_deleted(session: Session) -> Iterator[Session]:
    """Suspend the soft-delete filter for the duration of the block.

    Use this when ORM cascade or relationship traversal must see
    soft-deleted rows (hard_delete_user, cleanup_expired). Per-query
    callsites should prefer execution_options(include_deleted=True).
    """
    previous = session.info.get(_SESSION_FLAG, False)
    session.info[_SESSION_FLAG] = True
    try:
        yield session
    finally:
        session.info[_SESSION_FLAG] = previous

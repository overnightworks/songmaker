"""The one builder of a reference-recording row for tests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from songmaker_cli.db.models import ReferenceRecording
from songmaker_cli.reference_audio import owner_reference_audio_root


def a_reference(
    session: Session, user_id: str, *, name: str, size_bytes: int = 4,
    duration_sec: float | None = None, storage_path: str | None = None,
    reference_id: str | None = None, original_filename: str | None = None,
    created_at: datetime | None = None, unused_since: datetime | None = None,
    is_kept: bool = False,
) -> ReferenceRecording:
    """Add and flush the row; the caller commits.

    Without ``storage_path`` the row is stored where the owner's references live.
    """
    if storage_path is None:
        storage_path = str(owner_reference_audio_root(Path(), user_id) / name)
    row = ReferenceRecording(
        user_id=user_id, storage_path=storage_path, size_bytes=size_bytes,
        original_filename=original_filename or name, duration_sec=duration_sec,
        unused_since=unused_since, is_kept=is_kept,
    )
    if reference_id is not None:
        row.id = reference_id
    if created_at is not None:
        row.created_at = created_at
    session.add(row)
    session.flush()
    return row

"""Reference recordings: the owner's uploaded reference audio, one row per file."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from songmaker_cli.db.models import ReferenceRecording


@dataclass(frozen=True)
class ReferenceUsage:
    files: int
    bytes: int


def create_reference_recording(
    session: Session,
    *,
    user_id: str,
    storage_path: str,
    original_filename: str,
    size_bytes: int,
    duration_sec: float | None,
) -> ReferenceRecording:
    recording = ReferenceRecording(
        user_id=user_id,
        storage_path=storage_path,
        original_filename=original_filename,
        size_bytes=size_bytes,
        duration_sec=duration_sec,
    )
    session.add(recording)
    session.flush()
    return recording


def owner_reference_usage(session: Session, user_id: str) -> ReferenceUsage:
    files, size = session.execute(
        select(
            func.count(ReferenceRecording.id),
            func.coalesce(func.sum(ReferenceRecording.size_bytes), 0),
        ).where(ReferenceRecording.user_id == user_id)
    ).one()
    return ReferenceUsage(files=files, bytes=int(size))

"""Reference recordings: the owner's uploaded reference audio, one row per file."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from songmaker_cli.db.models import Generation, ReferenceRecording, Version


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


def get_owned_reference_recording(
    session: Session, user_id: str, reference_id: str, *, lock: bool = False,
) -> ReferenceRecording | None:
    """The owner's own row, or None for a missing or foreign id.

    ``lock`` takes the row lock until the transaction ends, so a concurrent delete
    waits for a link that is being saved and a link being saved waits for a delete.
    """
    query = select(ReferenceRecording).where(
        ReferenceRecording.id == reference_id, ReferenceRecording.user_id == user_id,
    )
    if lock:
        query = query.with_for_update()
    return session.execute(query).scalar_one_or_none()


def delete_reference_recording(session: Session, recording: ReferenceRecording) -> str:
    """Delete the row and flush; returns its storage path.

    A version or take that still links the row refuses the flush with ``IntegrityError``.
    """
    storage_path = recording.storage_path
    session.delete(recording)
    session.flush()
    return storage_path


def reference_ids_in_use(session: Session, reference_ids: Collection[str]) -> set[str]:
    """The ids a version or a take links, trashed songs' and albums' links included.

    The query names neither Song nor Album, so the soft-delete filter cannot hide a link.
    """
    if not reference_ids:
        return set()
    return set(
        session.execute(
            select(ReferenceRecording.id).where(
                ReferenceRecording.id.in_(reference_ids),
                or_(
                    exists().where(Version.reference_recording_id == ReferenceRecording.id),
                    exists().where(Generation.reference_recording_id == ReferenceRecording.id),
                ),
            ),
        ).scalars(),
    )


def owned_reference_storage_paths(session: Session, user_id: str) -> set[str]:
    return set(
        session.execute(
            select(ReferenceRecording.storage_path).where(ReferenceRecording.user_id == user_id),
        ).scalars(),
    )


def list_owned_reference_recordings(session: Session, user_id: str) -> list[ReferenceRecording]:
    """The owner's own rows, newest first; the id orders rows sharing an instant."""
    return list(
        session.execute(
            select(ReferenceRecording)
            .where(ReferenceRecording.user_id == user_id)
            .order_by(ReferenceRecording.created_at.desc(), ReferenceRecording.id)
        ).scalars()
    )


def owner_reference_usage(session: Session, user_id: str) -> ReferenceUsage:
    files, size = session.execute(
        select(
            func.count(ReferenceRecording.id),
            func.coalesce(func.sum(ReferenceRecording.size_bytes), 0),
        ).where(ReferenceRecording.user_id == user_id)
    ).one()
    return ReferenceUsage(files=files, bytes=int(size))

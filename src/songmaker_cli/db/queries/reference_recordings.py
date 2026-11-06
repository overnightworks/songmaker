"""Reference recordings: the owner's uploaded reference audio, one row per file."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Final

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from songmaker_cli.db.models import Album, Generation, ReferenceRecording, Song, Version
from songmaker_cli.timestamps import utcnow

REFERENCE_LINK_COLUMNS: Final = (
    Version.reference_recording_id,
    Generation.reference_recording_id,
)


@dataclass(frozen=True)
class ReferenceUsage:
    files: int
    bytes: int


@dataclass(frozen=True)
class ReferenceLinkCounts:
    versions: int
    takes: int


@dataclass(frozen=True)
class VersionUse:
    song_id: str
    song_title: str
    song_slug: str
    album_id: str
    version_number: int
    is_trashed: bool


@dataclass(frozen=True)
class TakeUse:
    song_id: str
    song_title: str
    song_slug: str
    album_id: str
    generation_number: int
    version_number: int | None
    is_archived: bool
    is_trashed: bool
    audio_duration_sec: float | None


@dataclass(frozen=True)
class ReferenceUses:
    versions: list[VersionUse]
    takes: list[TakeUse]


def create_reference_recording(
    session: Session,
    *,
    user_id: str,
    storage_path: str,
    original_filename: str,
    size_bytes: int,
    duration_sec: float | None,
) -> ReferenceRecording:
    unused_since = utcnow()
    recording = ReferenceRecording(
        created_at=unused_since,
        unused_since=unused_since,
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


def lock_and_mark_reference_used(
    session: Session, user_id: str, reference_id: str,
) -> ReferenceRecording | None:
    """The owner's own row, locked until the transaction ends and no longer unused.

    None for a missing or foreign id. Every path that newly links a version or a take
    to a reference takes its link through here.
    """
    recording = get_owned_reference_recording(session, user_id, reference_id, lock=True)
    if recording is not None:
        recording.unused_since = None
        session.flush()
    return recording


def mark_newly_unused(session: Session, reference_ids: Collection[str]) -> int:
    """Stamp ``unused_since`` on each unstamped, unkept row that no version or take links.

    The rows are locked in id order, then the links are counted by a fresh statement, so an
    attach that committed first is seen and one that comes later waits and clears the stamp.
    Unknown ids are ignored. Returns the stamped count.
    """
    if not reference_ids:
        return 0
    candidates = session.execute(
        select(ReferenceRecording)
        .where(
            ReferenceRecording.id.in_(reference_ids),
            ReferenceRecording.unused_since.is_(None),
            ReferenceRecording.is_kept.is_(False),
        )
        .order_by(ReferenceRecording.id)
        .with_for_update(),
    ).scalars().all()
    link_counts = reference_link_counts(session, [row.id for row in candidates])
    unlinked = [
        row for row in candidates
        if link_counts[row.id] == ReferenceLinkCounts(versions=0, takes=0)
    ]
    stamped_at = utcnow()
    for row in unlinked:
        row.unused_since = stamped_at
    session.flush()
    return len(unlinked)


def delete_reference_recording(session: Session, recording: ReferenceRecording) -> str:
    """Delete the row and flush; returns its storage path.

    A version or take that still links the row refuses the flush with ``IntegrityError``.
    """
    storage_path = recording.storage_path
    session.delete(recording)
    session.flush()
    return storage_path


def reference_link_counts(
    session: Session, reference_ids: Collection[str],
) -> dict[str, ReferenceLinkCounts]:
    """Per id, the saved versions and takes that link it, trashed songs' and albums' included.

    The queries name neither Song nor Album, so the soft-delete filter cannot hide a link.
    Every asked id is answered, with zero counts when nothing links it.
    """
    if not reference_ids:
        return {}
    version_counts, take_counts = (
        dict(
            session.execute(
                select(link, func.count()).where(link.in_(reference_ids)).group_by(link),
            ).all(),
        )
        for link in REFERENCE_LINK_COLUMNS
    )
    return {
        reference_id: ReferenceLinkCounts(
            versions=version_counts.get(reference_id, 0), takes=take_counts.get(reference_id, 0),
        )
        for reference_id in reference_ids
    }


def linked_reference_ids(session: Session, song_ids: Collection[str]) -> set[str]:
    """The references the given songs' versions and takes link, archived takes included."""
    if not song_ids:
        return set()
    linked: set[str] = set()
    for model in (Version, Generation):
        linked.update(
            session.scalars(
                select(model.reference_recording_id).where(
                    model.song_id.in_(song_ids), model.reference_recording_id.is_not(None),
                ),
            ),
        )
    return linked


def reference_uses(session: Session, reference_id: str) -> ReferenceUses:
    """The versions and takes linking the reference, newest first, trashed ones included."""
    trashed = or_(Song.deleted_at.is_not(None), Album.deleted_at.is_not(None))
    versions = session.execute(
        select(
            Song.id, Song.title, Song.slug, Album.id, Version.version_number, trashed,
        )
        .join(Song, Version.song_id == Song.id)
        .join(Album, Song.album_id == Album.id)
        .where(Version.reference_recording_id == reference_id)
        .order_by(Version.created_at.desc(), Version.id)
        .execution_options(include_deleted=True),
    ).all()
    takes = session.execute(
        select(
            Song.id, Song.title, Song.slug, Album.id, Generation.generation_number,
            Version.version_number, Generation.is_archived, trashed,
            Generation.audio_duration_sec,
        )
        .join(Song, Generation.song_id == Song.id)
        .join(Album, Song.album_id == Album.id)
        .outerjoin(Version, Generation.version_id == Version.id)
        .where(Generation.reference_recording_id == reference_id)
        .order_by(Generation.created_at.desc(), Generation.id)
        .execution_options(include_deleted=True),
    ).all()
    return ReferenceUses(
        versions=[VersionUse(*row) for row in versions], takes=[TakeUse(*row) for row in takes],
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

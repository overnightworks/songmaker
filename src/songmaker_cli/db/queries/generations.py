"""Query functions for generations — CRUD, pick/unpick, scores, ratings, sharing, file deletion."""

from __future__ import annotations

import logging
from collections.abc import Collection, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from sqlalchemy import ColumnElement, exists
from sqlalchemy.orm import Session, aliased, joinedload

from songmaker_cli import audio_files
from songmaker_cli.audio_paths import canonical_audio_filename
from songmaker_cli.constants import JobStatus
from songmaker_cli.db.models import Album, Generation, Rating, Score, Song
from songmaker_cli.db.queries.sharing import (
    disable_sharing,
    enable_sharing,
    playable_take_filter,
)
from songmaker_cli.whisper_cues import WhisperCue

log = logging.getLogger(__name__)

INITIAL_GENERATION_NUMBER: Final[int] = 1
COHERENCE_SCORE_KEY: Final = "lyrical_coherence"
COHERENCE_SUMMARY_KEY: Final = "lyrical_summary"
ARCHIVED_TAKE_DETAIL: Final = "Restore this take first."


class ArchivedTakeError(Exception):
    """The take is archived; keep, pick, share and playlist add need it restored first."""


def _probe_audio_duration_or_none(audio_dir: Path, mp3_rel: str) -> float | None:
    """Measure a generation's real audio length, logging if it can't be read."""
    duration = audio_files.read_audio_duration(audio_dir / mp3_rel)
    if duration is None:
        log.warning("Could not measure audio duration for %s", mp3_rel)
    return duration


def measure_generation_audio_duration(
    session: Session, audio_dir: Path, generation: Generation,
) -> float | None:
    """Backfill a generation's measured duration if it doesn't have one yet.

    Skips re-probing a generation that already carries a measured duration.
    A failed probe stores None, same as an unmeasured generation, so a later
    call retries rather than getting stuck on a transient read failure —
    this is deliberately not idempotent across a failure.
    """
    if generation.audio_duration_sec is not None:
        return generation.audio_duration_sec
    generation.audio_duration_sec = _probe_audio_duration_or_none(
        audio_dir, generation.mp3_path,
    )
    session.flush()
    return generation.audio_duration_sec


def get_generation(session: Session, gen_id: str) -> Generation | None:
    return (
        session.query(Generation)
        .options(
            joinedload(Generation.scores),
            joinedload(Generation.rating),
            joinedload(Generation.song).joinedload(Song.album),
            joinedload(Generation.src_generation).joinedload(Generation.version),
            joinedload(Generation.version),
        )
        .filter_by(id=gen_id)
        .first()
    )


def list_own_playable_generations(session: Session, user_id: str) -> list[Generation]:
    """Return a musician's playable takes with the fields picker callers need."""
    return (
        session.query(Generation)
        .join(Generation.song)
        .join(Song.album)
        .outerjoin(Generation.version)
        .options(
            joinedload(Generation.song).joinedload(Song.album),
            joinedload(Generation.version),
        )
        .filter(
            Album.created_by == user_id,
            playable_take_filter(),
        )
        .order_by(Generation.created_at.desc(), Generation.id.desc())
        .all()
    )


_GENERATION_FILE_SUFFIXES: Final = (
    ".mp3",
    ".wav",
    ".raw.wav",
    ".pre-remaster.wav",
    ".pre-remaster.mp3",
    ".md",
    ".whisper",
)


def generation_file_set(audio_rel: str) -> list[str]:
    """Return every file a take owns, as audio-dir-relative names."""
    stem = audio_rel.removesuffix(".mp3").removesuffix(".wav")
    return [stem + suffix for suffix in _GENERATION_FILE_SUFFIXES]


def all_generation_paths(session: Session) -> set[str]:
    """Return every file name owned by a take in the DB."""
    rows = session.query(Generation.mp3_path, Generation.wav_path).all()
    return {
        owned
        for mp3, wav in rows
        for audio_rel in (mp3, wav)
        if audio_rel
        for owned in generation_file_set(audio_rel)
    }


def create_generation(
    session: Session,
    song_id: str,
    version_id: str | None,
    mp3_path: str,
    model_mode: str,
    audio_dir: Path,
    seed: int | None = None,
    generation_params: dict | None = None,
    wav_path: str | None = None,
    src_generation_id: str | None = None,
    generation_id: str | None = None,
    *,
    created_by: str,
    reference_recording_id: str | None = None,
) -> Generation:
    """Create the row for a completed generation, naming the user who made it.

    The stored MP3 filename is canonicalized against ``audio_dir`` before the
    row is added. Its measured duration is stored on ``audio_duration_sec`` —
    the take's own length, never the requested
    ``generation_params.audio_duration`` parameter it was asked for.
    """
    max_num = (
        session.query(Generation.generation_number)
        .filter_by(song_id=song_id)
        .order_by(Generation.generation_number.desc())
        .first()
    )
    gen_number = (max_num[0] + 1) if max_num else INITIAL_GENERATION_NUMBER

    canonical_mp3_path = canonical_audio_filename(audio_dir, mp3_path) if mp3_path else ""
    if mp3_path and canonical_mp3_path is None:
        raise ValueError("Generation MP3 path must stay within the audio directory")

    gen = Generation(
        song_id=song_id,
        version_id=version_id,
        generation_number=gen_number,
        mp3_path=canonical_mp3_path,
        wav_path=wav_path,
        seed=seed,
        generation_params=generation_params,
        model_mode=model_mode,
        src_generation_id=src_generation_id,
        created_by=created_by,
        reference_recording_id=reference_recording_id,
        status=JobStatus.COMPLETED,
    )
    if generation_id is not None:
        gen.id = generation_id
    gen.audio_duration_sec = _probe_audio_duration_or_none(audio_dir, canonical_mp3_path)
    session.add(gen)
    session.flush()
    return gen


def save_scores(
    session: Session,
    generation_id: str,
    scores: dict[str, object],
    refreshed_keys: Collection[str],
) -> None:
    """Merge one scoring run's values into the generation's stored scores.

    Only ``refreshed_keys`` — the keys owned by the scorers that actually
    produced a value — are dropped before the merge. A scorer that timed out,
    failed, or was skipped therefore keeps the value it stored earlier.
    """
    from sqlalchemy.orm.attributes import flag_modified

    # Score has no uniqueness on (generation_id, scorer); locking the generation row
    # serializes writers so two first writes cannot each insert a batch row.
    session.query(Generation.id).filter_by(id=generation_id).with_for_update().first()
    existing = (
        session.query(Score)
        .filter_by(generation_id=generation_id, scorer="batch")
        .with_for_update()
        .populate_existing()
        .first()
    )
    if existing is None:
        session.add(Score(generation_id=generation_id, scorer="batch", value=dict(scores)))
        session.flush()
        return

    merged = {
        key: value for key, value in existing.value.items() if key not in refreshed_keys
    }
    merged.update(scores)
    existing.value = merged
    flag_modified(existing, "value")
    session.flush()


def save_coherence_verdict(
    session: Session, generation_id: str, score: int, summary: str,
) -> None:
    """Store the co-writer's coherence verdict as one pair beside the take's other scores."""
    pair = {COHERENCE_SCORE_KEY: score, COHERENCE_SUMMARY_KEY: summary}
    save_scores(session, generation_id, pair, pair.keys())


def set_generation_transcript(
    session: Session,
    generation_id: str,
    text: str,
    cues: Sequence[WhisperCue],
) -> None:
    generation = _require_generation(session, generation_id)
    generation.whisper_text = text
    generation.whisper_cues = list(cues)
    session.flush()


def save_rating(
    session: Session, generation_id: str, rating_value: float, notes: str = "",
) -> Rating:
    existing = session.query(Rating).filter_by(generation_id=generation_id).first()
    if existing:
        existing.rating = rating_value
        existing.notes = notes
        session.flush()
        return existing

    rating = Rating(generation_id=generation_id, rating=rating_value, notes=notes)
    session.add(rating)
    session.flush()
    return rating


def _require_generation(session: Session, generation_id: str) -> Generation:
    gen = session.query(Generation).filter_by(id=generation_id).first()
    if not gen:
        raise ValueError(f"Generation not found: {generation_id}")
    return gen


def _lock_generation(session: Session, generation_id: str) -> Generation:
    """Lock the take and reload it, so a concurrent archive or restore is seen.

    The lock is limited to the take (`of=Generation`) because the eager join to its
    reference recording is an outer join, which PostgreSQL cannot lock.
    """
    gen = (
        session.query(Generation)
        .filter_by(id=generation_id)
        .with_for_update(of=Generation)
        .populate_existing()
        .first()
    )
    if not gen:
        raise ValueError(f"Generation not found: {generation_id}")
    return gen


def lock_unarchived_generation(session: Session, generation_id: str) -> Generation:
    """The one refusal of an archived take: lock it, or raise `ArchivedTakeError`."""
    gen = _lock_generation(session, generation_id)
    if gen.is_archived:
        raise ArchivedTakeError(generation_id)
    return gen


def pick_generation(session: Session, generation_id: str) -> None:
    gen = _require_generation(session, generation_id)
    session.query(Generation).filter_by(song_id=gen.song_id).update({"is_picked": False})
    gen = lock_unarchived_generation(session, generation_id)
    gen.is_picked = True
    session.flush()


def unpick_generation(session: Session, generation_id: str) -> None:
    gen = _require_generation(session, generation_id)
    gen.is_picked = False
    session.flush()


def keep_generation(session: Session, generation_id: str) -> None:
    gen = lock_unarchived_generation(session, generation_id)
    gen.is_kept = True
    session.flush()


def unkeep_generation(session: Session, generation_id: str) -> None:
    gen = _require_generation(session, generation_id)
    gen.is_kept = False
    session.flush()


def _expired_for_archive_filters() -> tuple[ColumnElement[bool], ...]:
    """What makes a take archivable by retention: neither picked, kept nor archived."""
    return (
        Generation.is_picked.is_(False),
        Generation.is_kept.is_(False),
        Generation.is_archived.is_(False),
    )


def archive_generation(session: Session, generation_id: str) -> Generation | None:
    """Archive the take, or return None when no such take is archivable any more.

    The row lock is limited to the take (`of=Generation`) because the eager join to
    its reference recording is an outer join, which PostgreSQL cannot lock.
    """
    gen = (
        session.query(Generation)
        .filter(Generation.id == generation_id, *_expired_for_archive_filters())
        .with_for_update(of=Generation)
        .populate_existing()
        .first()
    )
    if gen is None:
        return None
    gen.is_archived = True
    gen.archived_at = datetime.now(timezone.utc)
    session.flush()
    return gen


def unarchive_generation(session: Session, generation_id: str) -> Generation:
    gen = _require_generation(session, generation_id)
    gen.is_archived = False
    gen.archived_at = None
    session.flush()
    return gen


def list_generations_expired_for_archive(
    session: Session, cutoff: datetime,
) -> list[Generation]:
    return (
        session.query(Generation)
        .filter(*_expired_for_archive_filters(), Generation.created_at < cutoff)
        .all()
    )


def _expired_for_delete_filters(cutoff: datetime) -> tuple[ColumnElement[bool], ...]:
    """What makes an archived take deletable by retention: archived before the cutoff,
    neither picked nor kept, and not the anchor of another take."""
    child = aliased(Generation)
    is_anchor = exists().where(child.src_generation_id == Generation.id)
    return (
        Generation.is_archived.is_(True),
        Generation.archived_at.isnot(None),
        Generation.archived_at < cutoff,
        Generation.is_picked.is_(False),
        Generation.is_kept.is_(False),
        ~is_anchor,
    )


def list_generations_expired_for_delete(
    session: Session, cutoff: datetime,
) -> list[Generation]:
    return session.query(Generation).filter(*_expired_for_delete_filters(cutoff)).all()


def _delete_locked_generation(session: Session, gen: Generation) -> list[str]:
    paths = [p for p in [gen.mp3_path, gen.wav_path] if p]
    session.delete(gen)
    session.flush()
    return paths


def delete_expired_generation(
    session: Session, generation_id: str, cutoff: datetime,
) -> list[str] | None:
    """Delete the take if it still qualifies for retention's final deletion.

    Returns its file paths for post-commit cleanup, or None when it no longer
    qualifies or no longer exists.
    """
    gen = (
        session.query(Generation)
        .filter(Generation.id == generation_id, *_expired_for_delete_filters(cutoff))
        .with_for_update(of=Generation)
        .populate_existing()
        .first()
    )
    if gen is None:
        return None
    return _delete_locked_generation(session, gen)


def get_generations(session: Session, generation_ids: list[str]) -> list[Generation]:
    """Load the generations that exist among the IDs, each with its song and album."""
    return (
        session.query(Generation)
        .options(joinedload(Generation.song).joinedload(Song.album))
        .filter(Generation.id.in_(generation_ids))
        .all()
    )


def bulk_delete_generations(session: Session, generations: list[Generation]) -> list[str]:
    """Delete the generations and return relative file paths for post-commit cleanup."""
    paths: list[str] = []
    for gen in generations:
        paths.extend(p for p in [gen.mp3_path, gen.wav_path] if p)
        session.delete(gen)

    session.flush()
    log.info("Bulk deleted %d generations", len(generations))
    return paths


def delete_generation(session: Session, generation_id: str) -> list[str]:
    """Delete a generation record and return relative file paths for cleanup.

    Callers must delete files AFTER committing the transaction to avoid
    inconsistency if the commit fails.
    """
    # Lock the take before the ORM delete removes its scores and ratings, the order
    # retention's final deletion uses, so the two never wait on each other in a cycle.
    gen = _lock_generation(session, generation_id)
    return _delete_locked_generation(session, gen)


def get_generation_by_slug(session: Session, slug: str) -> Generation | None:
    return (
        session.query(Generation)
        .options(
            joinedload(Generation.scores),
            joinedload(Generation.rating),
            joinedload(Generation.version),
            joinedload(Generation.song).joinedload(Song.album),
        )
        .filter_by(share_slug=slug, is_shared=True)
        .first()
    )


def enable_generation_sharing(session: Session, generation_id: str) -> Generation:
    lock_unarchived_generation(session, generation_id)
    gen = enable_sharing(session, Generation, generation_id)
    gen.is_kept = True
    session.flush()
    return gen


def disable_generation_sharing(session: Session, generation_id: str) -> Generation:
    return disable_sharing(session, Generation, generation_id)


def delete_generation_files(audio_dir: Path, mp3_rel: str) -> None:
    audio_root = audio_dir.resolve()
    mp3 = (audio_dir / mp3_rel).resolve()
    if not mp3.is_relative_to(audio_root):
        log.warning("Path traversal blocked in delete: %s", mp3_rel)
        return
    for owned in generation_file_set(mp3.relative_to(audio_root).as_posix()):
        path = audio_root / owned
        if path.exists():
            path.unlink()
            log.info("Deleted: %s", path)

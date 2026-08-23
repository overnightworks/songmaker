"""Query functions for generations — CRUD, pick/unpick, scores, ratings, sharing, file deletion."""

from __future__ import annotations

import logging
from collections.abc import Collection
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from sqlalchemy.orm import Session, aliased, joinedload

from songmaker_cli.constants import JobStatus
from songmaker_cli.db.models import Generation, Rating, Score, Song
from songmaker_cli.db.queries.sharing import disable_sharing, enable_sharing

log = logging.getLogger(__name__)

INITIAL_GENERATION_NUMBER: Final[int] = 1


def get_generation(session: Session, gen_id: str) -> Generation | None:
    return (
        session.query(Generation)
        .options(
            joinedload(Generation.scores),
            joinedload(Generation.rating),
            joinedload(Generation.song).joinedload(Song.album),
            joinedload(Generation.src_generation),
            joinedload(Generation.version),
        )
        .filter_by(id=gen_id)
        .first()
    )


def all_generation_paths(session: Session) -> set[str]:
    """Return set of all mp3_path and wav_path values in the DB."""
    rows = session.query(Generation.mp3_path, Generation.wav_path).all()
    return {p for mp3, wav in rows for p in (mp3, wav) if p}


def create_generation(
    session: Session,
    song_id: str,
    version_id: str | None,
    mp3_path: str,
    model_mode: str,
    seed: int | None = None,
    generation_params: dict | None = None,
    wav_path: str | None = None,
    src_generation_id: str | None = None,
    generation_id: str | None = None,
) -> Generation:
    max_num = (
        session.query(Generation.generation_number)
        .filter_by(song_id=song_id)
        .order_by(Generation.generation_number.desc())
        .first()
    )
    gen_number = (max_num[0] + 1) if max_num else INITIAL_GENERATION_NUMBER

    gen = Generation(
        song_id=song_id,
        version_id=version_id,
        generation_number=gen_number,
        mp3_path=mp3_path,
        wav_path=wav_path,
        seed=seed,
        generation_params=generation_params,
        model_mode=model_mode,
        src_generation_id=src_generation_id,
        status=JobStatus.COMPLETED,
    )
    if generation_id is not None:
        gen.id = generation_id
    session.add(gen)
    session.flush()
    log.info("Created generation #%d for song %s (seed=%s)", gen_number, song_id, seed)
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

    existing = (
        session.query(Score)
        .filter_by(generation_id=generation_id, scorer="batch")
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


def pick_generation(session: Session, generation_id: str) -> None:
    gen = session.query(Generation).filter_by(id=generation_id).first()
    if not gen:
        raise ValueError(f"Generation not found: {generation_id}")
    session.query(Generation).filter_by(song_id=gen.song_id).update({"is_picked": False})
    gen.is_picked = True
    session.flush()


def unpick_generation(session: Session, generation_id: str) -> None:
    gen = session.query(Generation).filter_by(id=generation_id).first()
    if not gen:
        raise ValueError(f"Generation not found: {generation_id}")
    gen.is_picked = False
    session.flush()


def keep_generation(session: Session, generation_id: str) -> None:
    gen = session.query(Generation).filter_by(id=generation_id).first()
    if not gen:
        raise ValueError(f"Generation not found: {generation_id}")
    gen.is_kept = True
    session.flush()


def unkeep_generation(session: Session, generation_id: str) -> None:
    gen = session.query(Generation).filter_by(id=generation_id).first()
    if not gen:
        raise ValueError(f"Generation not found: {generation_id}")
    gen.is_kept = False
    session.flush()


def archive_generation(session: Session, generation_id: str) -> Generation:
    gen = session.query(Generation).filter_by(id=generation_id).first()
    if not gen:
        raise ValueError(f"Generation not found: {generation_id}")
    gen.is_archived = True
    gen.archived_at = datetime.now(timezone.utc)
    session.flush()
    return gen


def unarchive_generation(session: Session, generation_id: str) -> Generation:
    gen = session.query(Generation).filter_by(id=generation_id).first()
    if not gen:
        raise ValueError(f"Generation not found: {generation_id}")
    gen.is_archived = False
    gen.archived_at = None
    session.flush()
    return gen


def list_generations_expired_for_archive(
    session: Session, cutoff: datetime,
) -> list[Generation]:
    return (
        session.query(Generation)
        .filter(
            Generation.is_picked.is_(False),
            Generation.is_kept.is_(False),
            Generation.is_archived.is_(False),
            Generation.created_at < cutoff,
        )
        .all()
    )


def list_generations_expired_for_delete(
    session: Session, cutoff: datetime,
) -> list[Generation]:
    child = aliased(Generation)
    anchor_subq = (
        session.query(child.id)
        .filter(child.src_generation_id == Generation.id)
        .exists()
    )
    return (
        session.query(Generation)
        .filter(
            Generation.is_archived.is_(True),
            Generation.archived_at.isnot(None),
            Generation.archived_at < cutoff,
            ~anchor_subq,
        )
        .all()
    )


def bulk_delete_generations(
    session: Session, generation_ids: list[str], user_id: str,
) -> tuple[int, list[str]]:
    generations = (
        session.query(Generation)
        .options(joinedload(Generation.song).joinedload(Song.album))
        .filter(Generation.id.in_(generation_ids))
        .all()
    )

    found_ids = {g.id for g in generations}
    missing = set(generation_ids) - found_ids
    if missing:
        raise ValueError(f"Generations not found: {', '.join(sorted(missing))}")

    for gen in generations:
        album = gen.song.album if gen.song else None
        if not album or album.created_by != user_id:
            raise PermissionError(f"Generation {gen.id} not owned by user")

    paths: list[str] = []
    for gen in generations:
        for p in [gen.mp3_path, gen.wav_path]:
            if p:
                paths.append(p)
        session.delete(gen)

    session.flush()
    log.info("Bulk deleted %d generations", len(generations))
    return len(generations), paths


def delete_generation(session: Session, generation_id: str) -> list[str]:
    """Delete a generation record and return relative file paths for cleanup.

    Callers must delete files AFTER committing the transaction to avoid
    inconsistency if the commit fails.
    """
    gen = session.query(Generation).filter_by(id=generation_id).first()
    if not gen:
        raise ValueError(f"Generation not found: {generation_id}")

    paths = [p for p in [gen.mp3_path, gen.wav_path] if p]
    session.delete(gen)
    session.flush()

    log.info("Deleted generation %s", generation_id)
    return paths


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
    gen = enable_sharing(session, Generation, generation_id)
    gen.is_kept = True
    session.flush()
    return gen


def disable_generation_sharing(session: Session, generation_id: str) -> Generation:
    return disable_sharing(session, Generation, generation_id)


_GENERATION_FILE_SUFFIXES = [".mp3", ".wav", ".md", ".whisper"]


def delete_generation_files(audio_dir: Path, mp3_rel: str) -> None:
    mp3 = (audio_dir / mp3_rel).resolve()
    if not mp3.is_relative_to(audio_dir.resolve()):
        log.warning("Path traversal blocked in delete: %s", mp3_rel)
        return
    for suffix in _GENERATION_FILE_SUFFIXES:
        path = mp3.with_suffix(suffix)
        if path.exists():
            path.unlink()
            log.info("Deleted: %s", path)

"""Query functions for generations — CRUD, pick/unpick, scores, ratings, sharing, file deletion."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from sqlalchemy.orm import Session, joinedload

from songmaker_cli.db.models import Generation, Rating, Score, Song

log = logging.getLogger(__name__)


def get_generation(session: Session, gen_id: str) -> Generation | None:
    return (
        session.query(Generation)
        .options(
            joinedload(Generation.scores),
            joinedload(Generation.rating),
            joinedload(Generation.song).joinedload(Song.album),
        )
        .filter_by(id=gen_id)
        .first()
    )


def create_generation(
    session: Session,
    song_id: str,
    version_id: str | None,
    mp3_path: str,
    seed: int | None = None,
    generation_params: dict | None = None,
    wav_path: str | None = None,
) -> Generation:
    max_num = (
        session.query(Generation.generation_number)
        .filter_by(song_id=song_id)
        .order_by(Generation.generation_number.desc())
        .first()
    )
    gen_number = (max_num[0] + 1) if max_num else 1

    gen = Generation(
        song_id=song_id,
        version_id=version_id,
        generation_number=gen_number,
        mp3_path=mp3_path,
        wav_path=wav_path,
        seed=seed,
        generation_params=generation_params,
        status="completed",
    )
    session.add(gen)
    session.flush()
    log.info("Created generation #%d for song %s (seed=%s)", gen_number, song_id, seed)
    return gen


def save_scores(session: Session, generation_id: str, scores: dict) -> None:
    from sqlalchemy.orm.attributes import flag_modified

    existing = (
        session.query(Score)
        .filter_by(generation_id=generation_id, scorer="batch")
        .first()
    )
    if existing:
        existing.value = scores
        flag_modified(existing, "value")
    else:
        session.add(Score(generation_id=generation_id, scorer="batch", value=scores))
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
            joinedload(Generation.song).joinedload(Song.album),
        )
        .filter_by(share_slug=slug, is_shared=True)
        .first()
    )


def enable_generation_sharing(session: Session, generation_id: str) -> Generation:
    gen = session.query(Generation).filter_by(id=generation_id).first()
    if not gen:
        raise ValueError(f"Generation not found: {generation_id}")
    if not gen.share_slug:
        gen.share_slug = str(uuid.uuid4())
    gen.is_shared = True
    gen.is_kept = True
    session.flush()
    log.info("Enabled sharing for generation %s (slug=%s)", generation_id, gen.share_slug)
    return gen


def disable_generation_sharing(session: Session, generation_id: str) -> Generation:
    gen = session.query(Generation).filter_by(id=generation_id).first()
    if not gen:
        raise ValueError(f"Generation not found: {generation_id}")
    gen.share_slug = None
    gen.is_shared = False
    session.flush()
    log.info("Disabled sharing for generation %s", generation_id)
    return gen


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

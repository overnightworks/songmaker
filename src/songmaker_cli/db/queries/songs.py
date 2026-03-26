"""Query functions for albums, songs, versions, generations, scores, and ratings."""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from sqlalchemy.orm import Session, joinedload

from songmaker_cli.db.models import (
    Album,
    Generation,
    Rating,
    Score,
    Song,
    Version,
)

log = logging.getLogger(__name__)


class _Unset:
    """Sentinel distinguishing 'not provided' from None."""

UNSET = _Unset()


# ── Albums ────────────────────────────────────────────────────────


def list_albums(
    session: Session,
    user_id: str | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> list[Album]:
    query = session.query(Album).options(joinedload(Album.songs))
    if user_id:
        query = query.filter_by(created_by=user_id)
    query = query.order_by(Album.title).offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def count_albums(session: Session, user_id: str | None = None) -> int:
    query = session.query(Album)
    if user_id:
        query = query.filter_by(created_by=user_id)
    return query.count()


def get_album(session: Session, album_id: str) -> Album | None:
    return session.query(Album).filter_by(id=album_id).first()


def create_album(
    session: Session,
    album_id: str,
    title: str,
    artist: str = "",
    created_by: str | None = None,
) -> Album:
    album = Album(id=album_id, title=title, artist=artist, created_by=created_by)
    session.add(album)
    session.flush()
    log.info("Created album '%s' (id=%s, owner=%s)", title, album_id, created_by)
    return album


def get_album_by_slug(session: Session, slug: str) -> Album | None:
    return (
        session.query(Album)
        .options(
            joinedload(Album.songs)
            .joinedload(Song.generations),
        )
        .filter_by(share_slug=slug, is_shared=True)
        .first()
    )


def enable_album_sharing(session: Session, album_id: str) -> Album:
    album = session.query(Album).filter_by(id=album_id).first()
    if not album:
        raise ValueError(f"Album not found: {album_id}")
    if not album.share_slug:
        album.share_slug = str(uuid.uuid4())
    album.is_shared = True
    session.flush()
    log.info("Enabled sharing for album %s (slug=%s)", album_id, album.share_slug)
    return album


def disable_album_sharing(session: Session, album_id: str) -> Album:
    album = session.query(Album).filter_by(id=album_id).first()
    if not album:
        raise ValueError(f"Album not found: {album_id}")
    album.share_slug = None
    album.is_shared = False
    session.flush()
    log.info("Disabled sharing for album %s", album_id)
    return album


# ── Songs ─────────────────────────────────────────────────────────


def list_songs(
    session: Session,
    album_id: str | None = None,
    user_id: str | None = None,
    light: bool = False,
    offset: int = 0,
    limit: int | None = None,
) -> list[Song]:
    if light:
        query = (
            session.query(Song)
            .options(
                joinedload(Song.versions),
                joinedload(Song.generations),
                joinedload(Song.album),
            )
            .order_by(Song.album_id, Song.track_number)
        )
    else:
        query = (
            session.query(Song)
            .options(
                joinedload(Song.versions),
                joinedload(Song.generations).joinedload(Generation.scores),
                joinedload(Song.generations).joinedload(Generation.rating),
                joinedload(Song.album),
            )
            .order_by(Song.album_id, Song.track_number)
        )
    if album_id:
        query = query.filter_by(album_id=album_id)
    if user_id:
        query = query.join(Album).filter(Album.created_by == user_id)
    query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def count_songs(
    session: Session,
    album_id: str | None = None,
    user_id: str | None = None,
) -> int:
    query = session.query(Song)
    if album_id:
        query = query.filter_by(album_id=album_id)
    if user_id:
        query = query.join(Album).filter(Album.created_by == user_id)
    return query.count()


def get_song(session: Session, song_id: str) -> Song | None:
    return (
        session.query(Song)
        .options(
            joinedload(Song.versions),
            joinedload(Song.generations).joinedload(Generation.scores),
            joinedload(Song.generations).joinedload(Generation.rating),
            joinedload(Song.album),
        )
        .filter_by(id=song_id)
        .first()
    )


def create_song(
    session: Session,
    title: str,
    album_id: str,
    lyrics: str = "",
    prompt: str = "",
    bpm: int = 0,
    duration: int = 180,
    key: str = "",
    language: str = "",
    generation_params: dict | None = None,
) -> Song:
    album = session.query(Album).filter_by(id=album_id).first()
    if not album:
        raise ValueError(f"Album not found: {album_id}")

    max_track = (
        session.query(Song.track_number)
        .filter_by(album_id=album_id)
        .order_by(Song.track_number.desc())
        .first()
    )
    track_number = (max_track[0] + 1) if max_track else 1

    song = Song(
        title=title, album_id=album_id, language=language, track_number=track_number,
    )
    session.add(song)
    session.flush()

    version = Version(
        song_id=song.id, version_number=1,
        lyrics=lyrics, prompt=prompt, bpm=bpm, duration=duration, key=key,
        generation_params=generation_params,
    )
    session.add(version)
    session.flush()
    log.info("Created song '%s' (id=%s) in album '%s'", title, song.id, album_id)
    return song


def update_song(
    session: Session,
    song_id: str,
    lyrics: str | None = None,
    prompt: str | None = None,
    bpm: int | None = None,
    duration: int | None = None,
    key: str | None = None,
    generation_params: dict | None | _Unset = UNSET,
) -> Version:
    song = get_song(session, song_id)
    if not song:
        raise ValueError(f"Song not found: {song_id}")

    prev = song.latest_version
    next_num = (prev.version_number + 1) if prev else 1

    if isinstance(generation_params, _Unset):
        new_gen_params = prev.generation_params if prev else None
        prev_num = prev.version_number if prev else 0
        log.debug("generation_params not provided, carrying forward from v%d", prev_num)
    else:
        new_gen_params = generation_params or None

    version = Version(
        song_id=song_id,
        version_number=next_num,
        lyrics=lyrics if lyrics is not None else (prev.lyrics if prev else ""),
        prompt=prompt if prompt is not None else (prev.prompt if prev else ""),
        bpm=bpm if bpm is not None else (prev.bpm if prev else 0),
        duration=duration if duration is not None else (prev.duration if prev else 180),
        key=key if key is not None else (prev.key if prev else ""),
        generation_params=new_gen_params,
    )
    session.add(version)
    session.flush()
    log.info("Updated song %s → v%d", song_id, next_num)
    return version


# ── Generations ───────────────────────────────────────────────────


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


def get_generation_by_path(session: Session, mp3_path: str) -> Generation | None:
    return (
        session.query(Generation)
        .options(joinedload(Generation.scores), joinedload(Generation.rating))
        .filter_by(mp3_path=mp3_path)
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


# ── Scores & Ratings ──────────────────────────────────────────────


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


# ── Pick ──────────────────────────────────────────────────────────


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


# ── Deletion ──────────────────────────────────────────────────────


def delete_version(
    session: Session, version_id: str, *,
    delete_generations: bool = False, output_dir: Path | None = None,
) -> None:
    version = session.query(Version).filter_by(id=version_id).first()
    if not version:
        raise ValueError(f"Version not found: {version_id}")

    if delete_generations:
        for gen in version.generations:
            if output_dir and gen.mp3_path:
                _delete_generation_files(output_dir, gen.mp3_path)
            session.delete(gen)
    else:
        for gen in version.generations:
            gen.version_id = None

    session.delete(version)
    session.flush()
    log.info("Deleted version %s (delete_generations=%s)", version_id, delete_generations)


def delete_generation(
    session: Session, generation_id: str, output_dir: Path | None = None,
) -> None:
    gen = session.query(Generation).filter_by(id=generation_id).first()
    if not gen:
        raise ValueError(f"Generation not found: {generation_id}")

    if output_dir and gen.mp3_path:
        _delete_generation_files(output_dir, gen.mp3_path)

    session.delete(gen)
    session.flush()
    log.info("Deleted generation %s", generation_id)


_GENERATION_FILE_SUFFIXES = [".mp3", ".wav", ".md", ".whisper"]


def _delete_generation_files(output_dir: Path, mp3_rel: str) -> None:
    mp3 = (output_dir / mp3_rel).resolve()
    if not mp3.is_relative_to(output_dir.resolve()):
        log.warning("Path traversal blocked in delete: %s", mp3_rel)
        return
    for suffix in _GENERATION_FILE_SUFFIXES:
        path = mp3.with_suffix(suffix)
        if path.exists():
            path.unlink()
            log.info("Deleted: %s", path)


def cleanup_album(
    session: Session, album_id: str, output_dir: Path | None = None,
) -> int:
    """Delete all non-picked generations for an album. Returns count deleted."""
    gens = (
        session.query(Generation)
        .join(Song)
        .options(joinedload(Generation.scores), joinedload(Generation.rating))
        .filter(Song.album_id == album_id, Generation.is_picked == False)  # noqa: E712
        .all()
    )
    count = len(gens)
    for gen in gens:
        if output_dir and gen.mp3_path:
            _delete_generation_files(output_dir, gen.mp3_path)
        session.delete(gen)
    session.flush()
    return count


def delete_album(
    session: Session, album_id: str, output_dir: Path | None = None,
) -> None:
    album = session.query(Album).filter_by(id=album_id).first()
    if not album:
        raise ValueError(f"Album not found: {album_id}")

    gens = (
        session.query(Generation)
        .join(Song)
        .options(joinedload(Generation.scores), joinedload(Generation.rating))
        .filter(Song.album_id == album_id)
        .all()
    )
    for gen in gens:
        if output_dir and gen.mp3_path:
            _delete_generation_files(output_dir, gen.mp3_path)
        session.delete(gen)

    session.delete(album)
    session.flush()

    if output_dir:
        album_dir = (output_dir / album_id).resolve()
        if album_dir.is_relative_to(output_dir.resolve()) and album_dir.is_dir():
            shutil.rmtree(album_dir, ignore_errors=True)
            log.info("Removed album directory: %s", album_dir)

    log.info("Deleted album %s", album_id)


def move_song(
    session: Session, song_id: str, new_album_id: str,
    output_dir: Path | None = None,
) -> Song:
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise ValueError(f"Song not found: {song_id}")

    new_album = session.query(Album).filter_by(id=new_album_id).first()
    if not new_album:
        raise ValueError(f"Album not found: {new_album_id}")

    if song.album_id == new_album_id:
        return song

    old_album_id = song.album_id
    song.album_id = new_album_id

    if output_dir:
        _move_generation_files(session, song_id, old_album_id, new_album_id, output_dir)

    session.flush()
    log.info("Moved song %s from album %s to %s", song_id, old_album_id, new_album_id)
    return song


def _move_generation_files(
    session: Session, song_id: str,
    old_album_id: str, new_album_id: str,
    output_dir: Path,
) -> None:
    new_dir = output_dir / new_album_id
    new_dir.mkdir(parents=True, exist_ok=True)

    gens = session.query(Generation).filter_by(song_id=song_id).all()
    for gen in gens:
        if gen.mp3_path:
            gen.mp3_path = _move_file_and_update_path(
                output_dir, gen.mp3_path, old_album_id, new_album_id,
            )
        if gen.wav_path:
            gen.wav_path = _move_file_and_update_path(
                output_dir, gen.wav_path, old_album_id, new_album_id,
            )


def _move_file_and_update_path(
    output_dir: Path, rel_path: str,
    old_album_id: str, new_album_id: str,
) -> str:
    src = (output_dir / rel_path).resolve()
    if not src.is_relative_to(output_dir.resolve()):
        log.warning("Path traversal blocked in move: %s", rel_path)
        return rel_path

    new_rel = rel_path.replace(old_album_id + "/", new_album_id + "/", 1)
    dst = (output_dir / new_rel).resolve()

    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        log.info("Moved: %s -> %s", src, dst)

    return new_rel

"""Database query functions — called by API endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session, joinedload

from songmaker_cli.db.models import (
    Album,
    Generation,
    Job,
    LoginAttempt,
    Rating,
    Score,
    Song,
    User,
    UserSession,
    Version,
)

log = logging.getLogger(__name__)

_UNSET = object()


def list_albums(session: Session) -> list[Album]:
    return (
        session.query(Album)
        .options(joinedload(Album.songs))
        .order_by(Album.title)
        .all()
    )


def get_album(session: Session, album_id: str) -> Album | None:
    return session.query(Album).filter_by(id=album_id).first()


def list_songs(session: Session, album_id: str | None = None) -> list[Song]:
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
    return query.all()


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
    generation_params: dict | None | object = _UNSET,
) -> Version:
    song = get_song(session, song_id)
    if not song:
        raise ValueError(f"Song not found: {song_id}")

    prev = song.latest_version
    next_num = (prev.version_number + 1) if prev else 1

    if generation_params is _UNSET:
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


# ── Deletion ─────────────────────────────────────────────────────────


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


def _delete_generation_files(output_dir: Path, mp3_rel: str) -> None:
    """Remove MP3 and related files (.md snapshot, .whisper) from disk."""
    mp3 = output_dir / mp3_rel
    for suffix in [".mp3", ".md", ".whisper"]:
        path = mp3.with_suffix(suffix)
        if path.exists():
            path.unlink()
            log.info("Deleted: %s", path)


# ── Jobs ─────────────────────────────────────────────────────────────


def create_job(session: Session, job_type: str, user_id: str | None = None) -> Job:
    job = Job(type=job_type, user_id=user_id)
    session.add(job)
    session.flush()
    return job


def count_user_jobs_in_window(
    session: Session, user_id: str, job_type: str, window_seconds: int = 3600,
) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    return (
        session.query(Job)
        .filter(
            Job.user_id == user_id,
            Job.type == job_type,
            Job.started_at >= cutoff,
        )
        .count()
    )


def count_user_active_jobs(session: Session, user_id: str) -> int:
    return (
        session.query(Job)
        .filter(
            Job.user_id == user_id,
            Job.status.in_(("queued", "running")),
        )
        .count()
    )


def count_total_queued_jobs(session: Session) -> int:
    return (
        session.query(Job)
        .filter(Job.status.in_(("queued", "running")))
        .count()
    )


def update_job_status(
    session: Session, job_id: str, status: str,
    progress: float = 0.0, error: str | None = None,
) -> None:
    job = session.query(Job).filter_by(id=job_id).first()
    if not job:
        return
    job.status = status
    job.progress = progress
    job.error = error
    if status in ("completed", "failed"):
        job.completed_at = datetime.now(timezone.utc)
    session.flush()


def get_job(session: Session, job_id: str) -> Job | None:
    return session.query(Job).filter_by(id=job_id).first()




# ── Generation creation ─────────────────────────────────────────────


def create_generation(
    session: Session,
    song_id: str,
    version_id: str | None,
    mp3_path: str,
    seed: int | None = None,
    generation_params: dict | None = None,
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


# ── Pick ─────────────────────────────────────────────────────────────


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


# ── Auth ────────────────────────────────────────────────────────────


def get_user_by_username(session: Session, username: str) -> User | None:
    return session.query(User).filter_by(username=username).first()


def get_user(session: Session, user_id: str) -> User | None:
    return session.query(User).filter_by(id=user_id).first()


def list_users(session: Session) -> list[User]:
    return session.query(User).order_by(User.username).all()


def user_count(session: Session) -> int:
    return session.query(User).count()


def create_user(
    session: Session, username: str, password_hash: str, role: str = "user",
) -> User:
    user = User(username=username, password_hash=password_hash, role=role)
    session.add(user)
    session.flush()
    log.info("Created user '%s' (role=%s)", username, role)
    return user


def update_user(
    session: Session,
    user_id: str,
    role: str | None = None,
    is_active: bool | None = None,
    password_hash: str | None = None,
) -> User:
    user = session.query(User).filter_by(id=user_id).first()
    if not user:
        raise ValueError(f"User not found: {user_id}")
    if role is not None:
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    if password_hash is not None:
        user.password_hash = password_hash
    session.flush()
    return user


# ── Sessions ────────────────────────────────────────────────────────


def create_session(
    session: Session,
    user_id: str,
    expires_at: datetime,
    ip_address: str = "",
    user_agent: str = "",
) -> UserSession:
    user_session = UserSession(
        user_id=user_id,
        expires_at=expires_at,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.add(user_session)
    session.flush()
    return user_session


def get_session_with_user(session: Session, session_id: str) -> UserSession | None:
    return (
        session.query(UserSession)
        .options(joinedload(UserSession.user))
        .filter_by(id=session_id)
        .first()
    )


def delete_session(session: Session, session_id: str) -> None:
    user_session = session.query(UserSession).filter_by(id=session_id).first()
    if user_session:
        session.delete(user_session)
        session.flush()


def list_active_sessions(session: Session) -> list[UserSession]:
    now = datetime.now(timezone.utc)
    return (
        session.query(UserSession)
        .options(joinedload(UserSession.user))
        .filter(UserSession.expires_at > now)
        .order_by(UserSession.created_at.desc())
        .all()
    )


def delete_expired_sessions(session: Session) -> int:
    now = datetime.now(timezone.utc)
    count = session.query(UserSession).filter(UserSession.expires_at <= now).delete()
    session.flush()
    return count


# ── Login attempts ──────────────────────────────────────────────────


def record_login_attempt(
    session: Session, ip_address: str, username: str, *, success: bool,
) -> LoginAttempt:
    attempt = LoginAttempt(
        ip_address=ip_address, username=username, success=success,
    )
    session.add(attempt)
    session.flush()
    return attempt


def count_recent_failed_attempts(
    session: Session, ip_address: str, window_seconds: int = 300,
) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    return (
        session.query(LoginAttempt)
        .filter(
            LoginAttempt.ip_address == ip_address,
            LoginAttempt.success == False,  # noqa: E712
            LoginAttempt.attempted_at >= cutoff,
        )
        .count()
    )


def list_login_attempts(
    session: Session, limit: int = 100,
) -> list[LoginAttempt]:
    return (
        session.query(LoginAttempt)
        .order_by(LoginAttempt.attempted_at.desc())
        .limit(limit)
        .all()
    )

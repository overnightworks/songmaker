"""Query functions for users, sessions, and the audit log."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from songmaker_cli.db.models import (
    Album,
    AuditLog,
    Playlist,
    ResourceEventCursor,
    User,
    UserSession,
)

log = logging.getLogger(__name__)


# ── Users ─────────────────────────────────────────────────────────


def get_user(session: Session, user_id: str) -> User | None:
    return session.query(User).filter_by(id=user_id).first()


def list_users(session: Session) -> list[User]:
    return session.query(User).order_by(User.username).all()


def create_user(session: Session, user_id: str, username: str, role: str) -> User:
    user = User(id=user_id, username=username, role=role)
    session.add(user)
    session.flush()
    session.add(ResourceEventCursor(user_id=user.id))
    session.flush()
    log.info("Created user %s (role=%s)", user_id, role)
    return user


def hard_delete_user(session: Session, user_id: str) -> tuple[list[str], list[str], list[str]]:
    """Hard-delete a user and all their albums/songs/generations.

    Returns relative audio file paths plus album and playlist ids for post-commit cleanup.
    """
    from songmaker_cli.db.soft_delete import include_deleted

    audio_paths: list[str] = []
    with include_deleted(session):
        albums = session.query(Album).filter_by(created_by=user_id).all()
        album_ids = [album.id for album in albums]
        for album in albums:
            audio_paths.extend(_album_audio_paths(album))
            session.delete(album)

    playlists = session.query(Playlist).filter_by(created_by=user_id).all()
    playlist_ids = [playlist.id for playlist in playlists]
    for playlist in playlists:
        session.delete(playlist)

    user = session.query(User).filter_by(id=user_id).first()
    if not user:
        raise ValueError(f"User not found: {user_id}")
    session.delete(user)
    session.flush()
    log.info("Hard-deleted user %s and %d album(s)", user_id, len(album_ids))
    return audio_paths, album_ids, playlist_ids


def _album_audio_paths(album: Album) -> list[str]:
    return [
        path
        for song in album.songs
        for generation in song.generations
        for path in (generation.mp3_path, generation.wav_path)
        if path
    ]


def set_user_role(session: Session, user_id: str, role: str) -> User:
    user = session.query(User).filter_by(id=user_id).first()
    if not user:
        raise ValueError(f"User not found: {user_id}")
    user.role = role
    session.flush()
    return user


# ── Sessions ──────────────────────────────────────────────────────


def create_session(
    session: Session, user_id: str, *, created_at: datetime, expires_at: datetime,
) -> UserSession:
    user_session = UserSession(user_id=user_id, created_at=created_at, expires_at=expires_at)
    session.add(user_session)
    session.flush()
    return user_session


def get_session_with_user(session: Session, session_id: str) -> UserSession | None:
    query = (
        session.query(UserSession)
        .options(joinedload(UserSession.user))
        .filter_by(id=session_id)
    )
    if session.bind.dialect.name != "sqlite":
        query = query.with_for_update(of=UserSession)
    return query.first()


def renew_session(
    session: Session,
    session_id: str,
    *,
    expires_at: datetime,
) -> bool:
    """Renew an existing row without recreating a revoked session."""
    rowcount = session.query(UserSession).filter_by(id=session_id).update({
        UserSession.expires_at: expires_at,
    })
    return rowcount == 1


def delete_session(session: Session, session_id: str) -> None:
    user_session = session.query(UserSession).filter_by(id=session_id).first()
    if user_session:
        session.delete(user_session)
        session.flush()


def list_active_sessions(
    session: Session,
    offset: int = 0,
    limit: int | None = None,
) -> list[UserSession]:
    now = datetime.now(timezone.utc)
    query = (
        session.query(UserSession)
        .options(joinedload(UserSession.user))
        .filter(UserSession.expires_at > now)
        .order_by(UserSession.created_at.desc())
        .offset(offset)
    )
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def count_active_sessions(session: Session) -> int:
    now = datetime.now(timezone.utc)
    return session.query(UserSession).filter(UserSession.expires_at > now).count()


def delete_user_sessions(session: Session, user_id: str) -> int:
    """Delete all sessions for a user. Returns count deleted."""
    count = session.query(UserSession).filter_by(user_id=user_id).delete()
    session.flush()
    return count


def delete_expired_sessions(session: Session) -> int:
    now = datetime.now(timezone.utc)
    count = session.query(UserSession).filter(UserSession.expires_at <= now).delete()
    session.flush()
    return count


def prune_overflow_sessions(session: Session, user_id: str, keep_newest: int) -> None:
    """Delete all but the user's ``keep_newest`` newest sessions; ``0`` keeps none."""
    kept = (
        session.query(UserSession.id)
        .filter_by(user_id=user_id)
        .order_by(UserSession.created_at.desc(), UserSession.id.desc())
        .limit(keep_newest)
        .subquery()
    )
    session.query(UserSession).filter(
        UserSession.user_id == user_id, UserSession.id.not_in(select(kept.c.id)),
    ).delete(synchronize_session=False)
    session.flush()


# ── Audit log ─────────────────────────────────────────────────────


def record_audit(
    session: Session,
    user_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str = "",
    detail: str = "",
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
    )
    session.add(entry)
    session.flush()
    return entry


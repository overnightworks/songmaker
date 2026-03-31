"""SQLAlchemy ORM models for the songmaker database.

Hierarchy: Song → Version (content snapshot) → Generation (MP3 output)
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _session_token() -> str:
    return secrets.token_urlsafe(32)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


TZDateTime = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class Album(Base):
    __tablename__ = "albums"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    artist: Mapped[str] = mapped_column(String(200))
    subtitle: Mapped[str] = mapped_column(String(400), default="")
    year: Mapped[str] = mapped_column(String(10), default="")
    colors: Mapped[dict] = mapped_column(JSON, default=dict)
    share_slug: Mapped[str | None] = mapped_column(
        String(36), unique=True, nullable=True, index=True,
    )
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)

    songs: Mapped[list[Song]] = relationship(back_populates="album", cascade="all, delete-orphan")


class Song(Base):
    __tablename__ = "songs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200))
    album_id: Mapped[str] = mapped_column(ForeignKey("albums.id"), index=True)
    language: Mapped[str] = mapped_column(String(10), default="")
    track_number: Mapped[int] = mapped_column(Integer, default=0)
    share_slug: Mapped[str | None] = mapped_column(
        String(36), unique=True, nullable=True, index=True,
    )
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow, onupdate=_utcnow)

    album: Mapped[Album] = relationship(back_populates="songs")
    versions: Mapped[list[Version]] = relationship(
        back_populates="song", cascade="all, delete-orphan",
        order_by="Version.created_at",
    )
    generations: Mapped[list[Generation]] = relationship(
        back_populates="song", cascade="all, delete-orphan",
        order_by="Generation.created_at.desc()",
    )

    @property
    def latest_version(self) -> Version | None:
        return self.versions[-1] if self.versions else None


class Version(Base):
    """A content snapshot — lyrics, prompt, params. Each save = new version."""

    __tablename__ = "versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    lyrics: Mapped[str] = mapped_column(Text, default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    bpm: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[int] = mapped_column(Integer, default=0)
    key: Mapped[str] = mapped_column(String(10), default="")
    generation_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)

    song: Mapped[Song] = relationship(back_populates="versions")
    generations: Mapped[list[Generation]] = relationship(back_populates="version")


class Generation(Base):
    """A generated audio output from a specific version."""

    __tablename__ = "generations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id"), index=True)
    version_id: Mapped[str | None] = mapped_column(
        ForeignKey("versions.id"), nullable=True,
    )
    generation_number: Mapped[int] = mapped_column(Integer, default=1)
    seed: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mp3_path: Mapped[str] = mapped_column(String(500), index=True)
    wav_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    whisper_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    is_picked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_kept: Mapped[bool] = mapped_column(Boolean, default=False)
    share_slug: Mapped[str | None] = mapped_column(
        String(36), unique=True, nullable=True, index=True,
    )
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)

    song: Mapped[Song] = relationship(back_populates="generations")
    version: Mapped[Version | None] = relationship(back_populates="generations")
    scores: Mapped[list[Score]] = relationship(
        back_populates="generation", cascade="all, delete-orphan",
    )
    rating: Mapped[Rating | None] = relationship(
        back_populates="generation", uselist=False, cascade="all, delete-orphan",
    )


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    generation_id: Mapped[str] = mapped_column(ForeignKey("generations.id"), index=True)
    scorer: Mapped[str] = mapped_column(String(50))
    value: Mapped[dict] = mapped_column(JSON)
    scored_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)

    generation: Mapped[Generation] = relationship(back_populates="scores")


class Rating(Base):
    __tablename__ = "ratings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    generation_id: Mapped[str] = mapped_column(ForeignKey("generations.id"), unique=True)
    rating: Mapped[float] = mapped_column(Float)
    notes: Mapped[str] = mapped_column(Text, default="")
    rated_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)

    generation: Mapped[Generation] = relationship(back_populates="rating")


class AvailableModel(Base):
    __tablename__ = "available_models"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class GenerationPreset(Base):
    __tablename__ = "generation_presets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(100))
    model_mode: Mapped[str] = mapped_column(String(10))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow, onupdate=_utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    worker_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)


# ── Auth ────────────────────────────────────────────────────────────


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    default_generation_config: Mapped[str | None] = mapped_column(
        String(36), nullable=True, default=None,
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow, onupdate=_utcnow)

    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan",
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(43), primary_key=True, default=_session_token)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)
    ip_address: Mapped[str] = mapped_column(String(45), default="")
    user_agent: Mapped[str] = mapped_column(String(500), default="")

    user: Mapped[User] = relationship(back_populates="sessions")


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    ip_address: Mapped[str] = mapped_column(String(45), index=True)
    username: Mapped[str] = mapped_column(String(100))
    success: Mapped[bool] = mapped_column(Boolean)
    attempted_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)


class RateLimitSetting(Base):
    __tablename__ = "rate_limit_settings"
    __table_args__ = (
        UniqueConstraint("user_id", "setting_key", name="uq_rate_limit_user_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    setting_key: Mapped[str] = mapped_column(String(50))
    value: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow, onupdate=_utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    action: Mapped[str] = mapped_column(String(30), index=True)
    resource_type: Mapped[str] = mapped_column(String(30))
    resource_id: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow, index=True)

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
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates

from songmaker_cli.api_models.generation_params import (
    BaseGenerationParams,
    StoredGenerationParams,
)
from songmaker_cli.constants import MODEL_DEFAULT_MODE, JobStatus


def _validate_base_generation_params(value: object) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        msg = (
            f"generation_params must be a dict or None, got {type(value).__name__}"
        )
        raise TypeError(msg)
    return BaseGenerationParams.model_validate(value).model_dump(exclude_none=True)


def _validate_stored_generation_params(value: object) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        msg = (
            f"generation_params must be a dict or None, got {type(value).__name__}"
        )
        raise TypeError(msg)
    return StoredGenerationParams.model_validate(value).model_dump(exclude_none=True)


def _uuid() -> str:
    return str(uuid.uuid4())


def _session_token() -> str:
    return secrets.token_urlsafe(32)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


TZDateTime = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class ShareMixin:
    """Mixin providing share_slug + is_shared columns for public sharing."""

    share_slug: Mapped[str | None] = mapped_column(
        String(36), unique=True, nullable=True, index=True,
    )
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)


class Album(ShareMixin, Base):
    __tablename__ = "albums"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    artist: Mapped[str] = mapped_column(String(200))
    subtitle: Mapped[str] = mapped_column(String(400), default="")
    year: Mapped[str] = mapped_column(String(10), default="")
    colors: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)

    deleted_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)

    songs: Mapped[list[Song]] = relationship(back_populates="album", cascade="all, delete-orphan")


class Song(ShareMixin, Base):
    __tablename__ = "songs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200))
    album_id: Mapped[str] = mapped_column(ForeignKey("albums.id"), index=True)
    vocal_language: Mapped[str] = mapped_column(String(10), default="")
    track_number: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow, onupdate=_utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)

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
    audio_duration: Mapped[int] = mapped_column(Integer, default=0)
    key_scale: Mapped[str] = mapped_column(String(10), default="")
    generation_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)

    song: Mapped[Song] = relationship(back_populates="versions")
    generations: Mapped[list[Generation]] = relationship(back_populates="version")

    @validates("generation_params")
    def _validate_generation_params(self, _key: str, value: object) -> dict | None:
        return _validate_base_generation_params(value)


class Generation(ShareMixin, Base):
    """A generated audio output from a specific version."""

    __tablename__ = "generations"
    __table_args__ = (
        UniqueConstraint("song_id", "generation_number", name="uq_generation_song_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id"), index=True)
    version_id: Mapped[str | None] = mapped_column(
        ForeignKey("versions.id"), nullable=True, index=True,
    )
    generation_number: Mapped[int] = mapped_column(Integer, default=1)
    seed: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mp3_path: Mapped[str] = mapped_column(String(500), index=True)
    wav_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    whisper_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.COMPLETED)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(
        TZDateTime, nullable=True, index=True,
    )
    is_picked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_kept: Mapped[bool] = mapped_column(Boolean, default=False)
    model_mode: Mapped[str] = mapped_column(
        String(10), nullable=False, default=MODEL_DEFAULT_MODE,
    )
    src_generation_id: Mapped[str | None] = mapped_column(
        ForeignKey("generations.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)

    song: Mapped[Song] = relationship(back_populates="generations")
    version: Mapped[Version | None] = relationship(back_populates="generations")
    src_generation: Mapped[Generation | None] = relationship(
        remote_side=[id], foreign_keys=[src_generation_id],
    )
    scores: Mapped[list[Score]] = relationship(
        back_populates="generation", cascade="all, delete-orphan",
    )
    rating: Mapped[Rating | None] = relationship(
        back_populates="generation", uselist=False, cascade="all, delete-orphan",
    )

    @validates("generation_params")
    def _validate_generation_params(self, _key: str, value: object) -> dict | None:
        return _validate_stored_generation_params(value)


class Playlist(ShareMixin, Base):
    __tablename__ = "playlists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow, onupdate=_utcnow)

    entries: Mapped[list[PlaylistEntry]] = relationship(
        back_populates="playlist", cascade="all, delete-orphan",
        order_by="PlaylistEntry.position",
    )


class PlaylistEntry(Base):
    __tablename__ = "playlist_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    playlist_id: Mapped[str] = mapped_column(ForeignKey("playlists.id"), index=True)
    generation_id: Mapped[str] = mapped_column(
        ForeignKey("generations.id", ondelete="CASCADE"), index=True,
    )
    position: Mapped[int] = mapped_column(Integer)
    added_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)

    playlist: Mapped[Playlist] = relationship(back_populates="entries")
    generation: Mapped[Generation] = relationship()


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

    @validates("params")
    def _validate_params(self, _key: str, value: object) -> dict:
        if value is None:
            return {}
        if not isinstance(value, dict):
            msg = f"params must be a dict, got {type(value).__name__}"
            raise TypeError(msg)
        return BaseGenerationParams.model_validate(value).model_dump(exclude_none=True)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED, index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    worker_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heartbeat_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)
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
    value_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow, onupdate=_utcnow)


class Conversation(Base):
    """A user-scoped chat session. Each user has at most one active (non-archived)
    conversation at a time; "new conversation" archives the current one and starts
    a fresh row. Messages attach via ``ChatMessage.conversation_id``.
    """

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=_utcnow, onupdate=_utcnow,
    )
    archived_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )
    summary: Mapped[ConversationSummary | None] = relationship(
        back_populates="conversation",
        uselist=False,
        cascade="all, delete-orphan",
    )


class ConversationSummary(Base):
    """Rolling summary of older messages in a conversation.

    One row per conversation (unique FK). Updated in place when the
    conversation grows past the summarization threshold. The last-
    summarized message id is an exclusive upper bound — messages
    created *after* that row are kept verbatim in the prompt; everything
    up to and including it is represented by ``summary_text``.
    """

    __tablename__ = "conversation_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        unique=True, index=True,
    )
    summary_text: Mapped[str] = mapped_column(Text)
    last_summarized_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True,
    )
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=_utcnow, onupdate=_utcnow,
    )

    conversation: Mapped[Conversation] = relationship(back_populates="summary")


class CowriterUserMemory(Base):
    """Durable per-user co-writer notes. Survives conversation archive."""

    __tablename__ = "cowriter_user_memories"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
    )
    body: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=_utcnow, onupdate=_utcnow,
    )


class CowriterSongMemory(Base):
    """Durable per-song co-writer notes. Not a second lyrics store."""

    __tablename__ = "cowriter_song_memories"

    song_id: Mapped[str] = mapped_column(
        ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True,
    )
    body: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=_utcnow, onupdate=_utcnow,
    )


class CowriterAlbumMemory(Base):
    """Optional album-scoped co-writer notes."""

    __tablename__ = "cowriter_album_memories"

    album_id: Mapped[str] = mapped_column(
        ForeignKey("albums.id", ondelete="CASCADE"), primary_key=True,
    )
    body: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=_utcnow, onupdate=_utcnow,
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    song_id: Mapped[str | None] = mapped_column(
        ForeignKey("songs.id", ondelete="CASCADE"), index=True, nullable=True,
    )
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True, nullable=True,
    )
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)

    conversation: Mapped[Conversation | None] = relationship(back_populates="messages")


class AceStepWorker(Base):
    __tablename__ = "acestep_workers"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    gpu_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vram_total_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)
    last_register_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=_utcnow, onupdate=_utcnow,
    )


class UserLora(Base):
    """User-trained LoRA adapter. One row per training run container.

    ``status`` moves through ``LoraStatus.DRAFT`` → ``QUEUED`` → ``PREPROCESSING``
    → ``TRAINING`` → ``EXPORTING`` → ``READY`` (or ``FAILED`` at any step).
    ``storage_path`` points at the exported adapter dir once status is READY;
    it is None while draft/training.
    """

    __tablename__ = "user_loras"
    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="uq_user_lora_user_slug"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tensor_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    training_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        TZDateTime, nullable=True, index=True,
    )

    samples: Mapped[list[UserLoraSample]] = relationship(
        back_populates="user_lora",
        cascade="all, delete-orphan",
        order_by="UserLoraSample.position",
    )


class UserLoraSample(Base):
    """An audio take inside a UserLora. Caption + lyrics live in DB; the
    on-disk sidecar ``.caption.txt`` / ``.lyrics.txt`` files are written
    only at training time and deleted afterward."""

    __tablename__ = "user_lora_samples"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_lora_id: Mapped[str] = mapped_column(
        ForeignKey("user_loras.id", ondelete="CASCADE"), index=True,
    )
    audio_path: Mapped[str] = mapped_column(String(500))
    caption: Mapped[str] = mapped_column(Text, default="")
    lyrics: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=_utcnow, onupdate=_utcnow,
    )

    user_lora: Mapped[UserLora] = relationship(back_populates="samples")


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

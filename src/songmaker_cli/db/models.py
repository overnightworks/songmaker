"""SQLAlchemy ORM models for the songmaker database."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    songs: Mapped[list[Song]] = relationship(back_populates="album", cascade="all, delete-orphan")


class Song(Base):
    __tablename__ = "songs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200))
    album_id: Mapped[str] = mapped_column(ForeignKey("albums.id"))
    language: Mapped[str] = mapped_column(String(10), default="")
    track_number: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    album: Mapped[Album] = relationship(back_populates="songs")
    revisions: Mapped[list[SongRevision]] = relationship(
        back_populates="song", cascade="all, delete-orphan", order_by="SongRevision.created_at",
    )
    versions: Mapped[list[Version]] = relationship(
        back_populates="song", cascade="all, delete-orphan", order_by="Version.created_at.desc()",
    )

    @property
    def latest_revision(self) -> SongRevision | None:
        return self.revisions[-1] if self.revisions else None


class SongRevision(Base):
    """Each save of lyrics/prompt creates a new revision for full history."""

    __tablename__ = "song_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id"))
    lyrics: Mapped[str] = mapped_column(Text, default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    bpm: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[int] = mapped_column(Integer, default=0)
    key: Mapped[str] = mapped_column(String(10), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    song: Mapped[Song] = relationship(back_populates="revisions")


class Version(Base):
    """Each generation attempt — links to the song and the revision used."""

    __tablename__ = "versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id"))
    revision_id: Mapped[str | None] = mapped_column(ForeignKey("song_revisions.id"), nullable=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mp3_path: Mapped[str] = mapped_column(String(500))
    whisper_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    song: Mapped[Song] = relationship(back_populates="versions")
    revision: Mapped[SongRevision | None] = relationship()
    scores: Mapped[list[Score]] = relationship(
        back_populates="version", cascade="all, delete-orphan",
    )
    rating: Mapped[Rating | None] = relationship(
        back_populates="version", uselist=False, cascade="all, delete-orphan",
    )


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(ForeignKey("versions.id"))
    scorer: Mapped[str] = mapped_column(String(50))
    value: Mapped[dict] = mapped_column(JSON)
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    version: Mapped[Version] = relationship(back_populates="scores")


class Rating(Base):
    __tablename__ = "ratings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(ForeignKey("versions.id"), unique=True)
    rating: Mapped[float] = mapped_column(Float)
    notes: Mapped[str] = mapped_column(Text, default="")
    rated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    version: Mapped[Version] = relationship(back_populates="rating")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    type: Mapped[str] = mapped_column(String(20))
    version_id: Mapped[str | None] = mapped_column(ForeignKey("versions.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

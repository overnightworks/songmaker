"""initial schema baseline

Revision ID: 2a5ce2401805
Revises:
Create Date: 2026-03-24

Full schema creation. Replaces the original index-only baseline.
All subsequent migrations build on top of this.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "2a5ce2401805"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(200), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)

    op.create_table(
        "albums",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("artist", sa.String(200), nullable=False),
        sa.Column("subtitle", sa.String(400), nullable=False),
        sa.Column("year", sa.String(10), nullable=False),
        sa.Column("colors", sa.JSON, nullable=False),
        sa.Column(
            "created_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index(op.f("ix_albums_created_by"), "albums", ["created_by"])

    op.create_table(
        "songs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("album_id", sa.String(64), sa.ForeignKey("albums.id"), nullable=False),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("track_number", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index(op.f("ix_songs_album_id"), "songs", ["album_id"])

    op.create_table(
        "versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("song_id", sa.String(36), sa.ForeignKey("songs.id"), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("lyrics", sa.Text, nullable=False),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("bpm", sa.Integer, nullable=False),
        sa.Column("duration", sa.Integer, nullable=False),
        sa.Column("key", sa.String(10), nullable=False),
        sa.Column("generation_params", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index(op.f("ix_versions_song_id"), "versions", ["song_id"])

    op.create_table(
        "generations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("song_id", sa.String(36), sa.ForeignKey("songs.id"), nullable=False),
        sa.Column("version_id", sa.String(36), sa.ForeignKey("versions.id"), nullable=True),
        sa.Column("generation_number", sa.Integer, nullable=False),
        sa.Column("seed", sa.Integer, nullable=True),
        sa.Column("mp3_path", sa.String(500), nullable=False),
        sa.Column("whisper_text", sa.Text, nullable=True),
        sa.Column("generation_params", sa.JSON, nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("is_archived", sa.Boolean, nullable=False),
        sa.Column("is_picked", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index(op.f("ix_generations_song_id"), "generations", ["song_id"])
    op.create_index(op.f("ix_generations_mp3_path"), "generations", ["mp3_path"])

    op.create_table(
        "scores",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "generation_id", sa.String(36),
            sa.ForeignKey("generations.id"), nullable=False,
        ),
        sa.Column("scorer", sa.String(50), nullable=False),
        sa.Column("value", sa.JSON, nullable=False),
        sa.Column("scored_at", sa.DateTime, nullable=False),
    )
    op.create_index(op.f("ix_scores_generation_id"), "scores", ["generation_id"])

    op.create_table(
        "ratings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "generation_id", sa.String(36),
            sa.ForeignKey("generations.id"), nullable=False, unique=True,
        ),
        sa.Column("rating", sa.Float, nullable=False),
        sa.Column("notes", sa.Text, nullable=False),
        sa.Column("rated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("progress", sa.Float, nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("error_type", sa.String(30), nullable=True),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("completed_at", sa.DateTime, nullable=True),
    )
    op.create_index(op.f("ix_jobs_user_id"), "jobs", ["user_id"])

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(43), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("user_agent", sa.String(500), nullable=False),
    )
    op.create_index(op.f("ix_user_sessions_user_id"), "user_sessions", ["user_id"])

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("attempted_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        op.f("ix_login_attempts_ip_address"), "login_attempts", ["ip_address"],
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("resource_type", sa.String(30), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=False),
        sa.Column("detail", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index(op.f("ix_audit_log_action"), "audit_log", ["action"])
    op.create_index(op.f("ix_audit_log_created_at"), "audit_log", ["created_at"])
    op.create_index(op.f("ix_audit_log_user_id"), "audit_log", ["user_id"])

    op.create_table(
        "generation_presets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("model_mode", sa.String(10), nullable=False),
        sa.Column("params", sa.JSON, nullable=False),
        sa.Column("is_default", sa.Boolean, nullable=False),
        sa.Column(
            "created_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        op.f("ix_generation_presets_created_by"), "generation_presets", ["created_by"],
    )


def downgrade() -> None:
    op.drop_table("generation_presets")
    op.drop_table("audit_log")
    op.drop_table("login_attempts")
    op.drop_table("user_sessions")
    op.drop_table("jobs")
    op.drop_table("ratings")
    op.drop_table("scores")
    op.drop_table("generations")
    op.drop_table("versions")
    op.drop_table("songs")
    op.drop_table("albums")
    op.drop_table("users")

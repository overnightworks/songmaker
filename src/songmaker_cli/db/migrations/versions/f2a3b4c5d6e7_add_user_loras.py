"""Add user_loras + user_lora_samples tables

Creates two tables for user-trained LoRA voice adapters. Captions and
lyrics are stored per-sample in the DB so they can be edited without
touching disk; the on-disk sidecar ``.caption.txt`` / ``.lyrics.txt``
files are materialized only at training time.

Revision ID: f2a3b4c5d6e7
Revises: e2f3a4b5c6d7
Create Date: 2026-04-20 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_loras",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("storage_path", sa.String(length=500), nullable=True),
        sa.Column("tensor_path", sa.String(length=500), nullable=True),
        sa.Column("training_job_id", sa.String(length=36), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["training_job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "slug", name="uq_user_lora_user_slug"),
    )
    op.create_index(
        op.f("ix_user_loras_user_id"), "user_loras", ["user_id"], unique=False,
    )
    op.create_index(
        op.f("ix_user_loras_status"), "user_loras", ["status"], unique=False,
    )
    op.create_index(
        op.f("ix_user_loras_training_job_id"),
        "user_loras", ["training_job_id"], unique=False,
    )
    op.create_index(
        op.f("ix_user_loras_deleted_at"),
        "user_loras", ["deleted_at"], unique=False,
    )

    op.create_table(
        "user_lora_samples",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_lora_id", sa.String(length=36), nullable=False),
        sa.Column("audio_path", sa.String(length=500), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False, server_default=""),
        sa.Column("lyrics", sa.Text(), nullable=False, server_default=""),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_lora_id"], ["user_loras.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_user_lora_samples_user_lora_id"),
        "user_lora_samples", ["user_lora_id"], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_user_lora_samples_user_lora_id"), table_name="user_lora_samples",
    )
    op.drop_table("user_lora_samples")
    op.drop_index(op.f("ix_user_loras_deleted_at"), table_name="user_loras")
    op.drop_index(op.f("ix_user_loras_training_job_id"), table_name="user_loras")
    op.drop_index(op.f("ix_user_loras_status"), table_name="user_loras")
    op.drop_index(op.f("ix_user_loras_user_id"), table_name="user_loras")
    op.drop_table("user_loras")

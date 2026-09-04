"""add album cover suggestions

Revision ID: f533c1a00001
Revises: e480a1b2c3d4
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f533c1a00001"
down_revision: str | Sequence[str] | None = "e480a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("album_id", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "fk_jobs_album_id_albums", "jobs", "albums", ["album_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_jobs_album_id", "jobs", ["album_id"])
    op.create_table(
        "album_cover_suggestions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("album_id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("png_path", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["album_id"], ["albums.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_album_cover_suggestions_album_id", "album_cover_suggestions", ["album_id"],
    )
    op.create_index(
        "ix_album_cover_suggestions_job_id", "album_cover_suggestions", ["job_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_album_cover_suggestions_job_id", table_name="album_cover_suggestions")
    op.drop_index("ix_album_cover_suggestions_album_id", table_name="album_cover_suggestions")
    op.drop_table("album_cover_suggestions")
    op.drop_index("ix_jobs_album_id", table_name="jobs")
    op.drop_constraint("fk_jobs_album_id_albums", "jobs", type_="foreignkey")
    op.drop_column("jobs", "album_id")

"""add song_id to jobs

Revision ID: fbd1b4667d21
Revises: d8e9f0a1b2c3
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'fbd1b4667d21'
down_revision: Union[str, Sequence[str], None] = 'd8e9f0a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.add_column("jobs", sa.Column("song_id", sa.String(length=36), nullable=True))
    op.create_index("ix_jobs_song_id", "jobs", ["song_id"])
    op.create_foreign_key(
        "fk_jobs_song_id_songs", "jobs", "songs", ["song_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.drop_constraint("fk_jobs_song_id_songs", "jobs", type_="foreignkey")
    op.drop_index("ix_jobs_song_id", table_name="jobs")
    op.drop_column("jobs", "song_id")

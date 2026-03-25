"""add foreign keys to created_by and user_id

Revision ID: dae031c49b2b
Revises: 63e85f91478c
Create Date: 2026-03-25 11:14:19.247204
"""

from __future__ import annotations

from typing import Sequence, Union

revision: str = "dae031c49b2b"
down_revision: Union[str, Sequence[str], None] = "63e85f91478c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add FK constraints on albums.created_by and jobs.user_id.

    SQLite does not support ALTER TABLE ADD FOREIGN KEY, so this migration
    is a no-op for existing databases.  The constraints are enforced by
    the ORM models (ForeignKey declarations) and by PRAGMA foreign_keys=ON
    for new databases created via create_all().
    """


def downgrade() -> None:
    """No-op — see upgrade docstring."""

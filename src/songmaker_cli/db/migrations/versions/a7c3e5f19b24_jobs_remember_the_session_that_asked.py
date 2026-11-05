"""jobs remember the session that asked

Revision ID: a7c3e5f19b24
Revises: d8b4f2a6c1e9
Create Date: 2026-11-04 00:00:00.000000

"""
from typing import Sequence

from songmaker_cli.db.migrations.indexed_foreign_key import (
    add_indexed_foreign_key,
    drop_indexed_foreign_key,
)

revision: str = 'a7c3e5f19b24'
down_revision: str | Sequence[str] | None = 'd8b4f2a6c1e9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "jobs"
COLUMN = "session_id"
REFERENT_TABLE = "user_sessions"
SESSION_ID_LENGTH = 43


def upgrade() -> None:
    add_indexed_foreign_key(TABLE, COLUMN, REFERENT_TABLE, length=SESSION_ID_LENGTH)


def downgrade() -> None:
    drop_indexed_foreign_key(TABLE, COLUMN, REFERENT_TABLE)

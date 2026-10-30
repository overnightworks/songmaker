"""jobs remember their version

Revision ID: e3a91c5d7f20
Revises: c4d7e1a9b3f6
Create Date: 2026-10-30 00:00:00.000000

"""
from typing import Sequence

from songmaker_cli.db.migrations.indexed_foreign_key import (
    add_indexed_foreign_key,
    drop_indexed_foreign_key,
)

revision: str = 'e3a91c5d7f20'
down_revision: str | Sequence[str] | None = 'c4d7e1a9b3f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "jobs"
COLUMN = "version_id"
REFERENT_TABLE = "versions"


def upgrade() -> None:
    add_indexed_foreign_key(TABLE, COLUMN, REFERENT_TABLE)


def downgrade() -> None:
    drop_indexed_foreign_key(TABLE, COLUMN, REFERENT_TABLE)

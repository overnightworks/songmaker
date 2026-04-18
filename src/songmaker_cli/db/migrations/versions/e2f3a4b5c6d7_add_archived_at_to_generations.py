"""Add archived_at to generations for two-stage retention cleanup

Enables hard-delete N days after archive. NULL means not archived.
Backfills archived_at = created_at for any row where is_archived=True
(none expected today, defensive).

Revision ID: e2f3a4b5c6d7
Revises: d0e1f2a3b4c5
Create Date: 2026-04-18 13:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generations",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE generations SET archived_at = created_at "
        "WHERE is_archived = true AND archived_at IS NULL"
    )
    op.create_index(
        "ix_generations_archived_at", "generations", ["archived_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_generations_archived_at", table_name="generations")
    op.drop_column("generations", "archived_at")

"""jobs name the web process that runs them

Revision ID: d2f6b8a4c7e1
Revises: c4e8a2d6f913
Create Date: 2026-11-14 19:30:00.000000

"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'd2f6b8a4c7e1'
down_revision: str | Sequence[str] | None = 'c4e8a2d6f913'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('owner_id', sa.String(length=36), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'owner_id')

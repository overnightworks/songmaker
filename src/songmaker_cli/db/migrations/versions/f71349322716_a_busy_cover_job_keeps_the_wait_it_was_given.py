"""a busy cover job keeps the wait the gateway named

Revision ID: f71349322716
Revises: a7c3e5f19b24
Create Date: 2026-11-05 13:00:00.000000

"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'f71349322716'
down_revision: str | Sequence[str] | None = 'a7c3e5f19b24'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('retry_after_seconds', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'retry_after_seconds')

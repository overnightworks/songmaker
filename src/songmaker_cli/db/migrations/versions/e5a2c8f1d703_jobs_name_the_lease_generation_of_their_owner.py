"""jobs name the lease generation of the process that runs them

Revision ID: e5a2c8f1d703
Revises: c7e1a4d9b2f8
Create Date: 2026-11-16 18:00:00.000000

The generation is the value tandem's lease holds for one start of a process: a lease that lapsed
and started anew has another. A row written before this column keeps NULL and is judged by its
owner alone, as before.
"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'e5a2c8f1d703'
down_revision: str | Sequence[str] | None = 'c7e1a4d9b2f8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('owner_generation', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'owner_generation')

"""add available_models table

Revision ID: b1c3f4a90210
Revises: a9552fef8282
Create Date: 2026-03-30 15:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b1c3f4a90210'
down_revision: Union[str, Sequence[str], None] = 'a9552fef8282'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'available_models',
        sa.Column('id', sa.String(length=20), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.execute("INSERT INTO available_models (id, is_active) VALUES ('sft', true)")
    op.execute("INSERT INTO available_models (id, is_active) VALUES ('turbo', false)")


def downgrade() -> None:
    op.drop_table('available_models')

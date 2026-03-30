"""add_default_generation_config_to_users

Revision ID: a9552fef8282
Revises: 472a8313e095
Create Date: 2026-03-30 14:24:16.244866

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a9552fef8282'
down_revision: Union[str, Sequence[str], None] = '472a8313e095'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('default_generation_config', sa.String(length=36), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('users', 'default_generation_config')

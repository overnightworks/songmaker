"""add value_text to rate_limit_settings

Revision ID: 2c0ce79a63eb
Revises: 2006299a7179
Create Date: 2026-04-01 09:50:58.203279

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '2c0ce79a63eb'
down_revision: Union[str, Sequence[str], None] = '2006299a7179'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'rate_limit_settings',
        sa.Column('value_text', sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('rate_limit_settings', 'value_text')

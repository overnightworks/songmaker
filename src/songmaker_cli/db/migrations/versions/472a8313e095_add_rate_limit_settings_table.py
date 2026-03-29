"""add rate_limit_settings table

Revision ID: 472a8313e095
Revises: 41ccd3b86e42
Create Date: 2026-03-29 15:40:14.156973

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '472a8313e095'
down_revision: Union[str, Sequence[str], None] = '41ccd3b86e42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'rate_limit_settings',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('setting_key', sa.String(length=50), nullable=False),
        sa.Column('value', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'setting_key', name='uq_rate_limit_user_key'),
    )
    op.create_index(
        op.f('ix_rate_limit_settings_user_id'),
        'rate_limit_settings', ['user_id'], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f('ix_rate_limit_settings_user_id'),
        table_name='rate_limit_settings',
    )
    op.drop_table('rate_limit_settings')

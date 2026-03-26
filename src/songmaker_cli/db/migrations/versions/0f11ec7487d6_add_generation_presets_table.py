"""add generation_presets table

Revision ID: 0f11ec7487d6
Revises: cb9d08c092f1
Create Date: 2026-03-26 12:22:52.978256

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0f11ec7487d6'
down_revision: Union[str, Sequence[str], None] = 'cb9d08c092f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('generation_presets',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('model_mode', sa.String(length=10), nullable=False),
    sa.Column('params', sa.JSON(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(
        op.f('ix_generation_presets_created_by'),
        'generation_presets', ['created_by'], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_generation_presets_created_by'), table_name='generation_presets')
    op.drop_table('generation_presets')

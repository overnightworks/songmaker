"""add user_id to jobs table

Revision ID: 2a0ee990833a
Revises: 323807790c5d
Create Date: 2026-03-24 15:29:10.535365

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2a0ee990833a'
down_revision: Union[str, Sequence[str], None] = '323807790c5d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('jobs', sa.Column('user_id', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_jobs_user_id'), 'jobs', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_jobs_user_id'), table_name='jobs')
    op.drop_column('jobs', 'user_id')

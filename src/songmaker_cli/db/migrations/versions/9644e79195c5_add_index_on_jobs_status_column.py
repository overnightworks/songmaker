"""add index on jobs status column

Revision ID: 9644e79195c5
Revises: 2edbefc68ee9
Create Date: 2026-03-27 13:06:23.114213

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9644e79195c5'
down_revision: Union[str, Sequence[str], None] = '2edbefc68ee9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(op.f('ix_jobs_status'), 'jobs', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_jobs_status'), table_name='jobs')

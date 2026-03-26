"""add wav_path to generations

Revision ID: 2edbefc68ee9
Revises: 6737ea2effc9
Create Date: 2026-03-26 20:46:32.889432

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2edbefc68ee9'
down_revision: Union[str, Sequence[str], None] = '6737ea2effc9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('generations', sa.Column('wav_path', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('generations', 'wav_path')

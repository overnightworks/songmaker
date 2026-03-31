"""add is_kept to generations

Revision ID: d4e5f6a7b8c9
Revises: 93236a097220
Create Date: 2026-03-31 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '57a5b30b7c8a'
down_revision: Union[str, Sequence[str], None] = '93236a097220'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('generations', sa.Column(
        'is_kept', sa.Boolean(), nullable=False,
        server_default=sa.text('false'),
    ))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('generations', 'is_kept')

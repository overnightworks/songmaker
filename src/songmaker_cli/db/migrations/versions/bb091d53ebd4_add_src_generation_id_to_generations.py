"""add src_generation_id to generations

Revision ID: bb091d53ebd4
Revises: f1a2b3c4d5e6
Create Date: 2026-04-03 14:46:32.277970

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'bb091d53ebd4'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FK_NAME = "fk_generations_src_generation_id"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'generations',
        sa.Column('src_generation_id', sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        FK_NAME, 'generations', 'generations',
        ['src_generation_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(FK_NAME, 'generations', type_='foreignkey')
    op.drop_column('generations', 'src_generation_id')

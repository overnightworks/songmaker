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
    with op.batch_alter_table('generations', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('src_generation_id', sa.String(length=36), nullable=True),
        )
        batch_op.create_foreign_key(
            FK_NAME, 'generations',
            ['src_generation_id'], ['id'], ondelete='SET NULL',
        )


def downgrade() -> None:
    with op.batch_alter_table('generations', schema=None) as batch_op:
        batch_op.drop_constraint(FK_NAME, type_='foreignkey')
        batch_op.drop_column('src_generation_id')

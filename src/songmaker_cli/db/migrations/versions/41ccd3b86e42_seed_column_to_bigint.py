"""seed column to bigint

Revision ID: 41ccd3b86e42
Revises: a6f0c121ea0f
Create Date: 2026-03-27 18:41:11.295264

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '41ccd3b86e42'
down_revision: Union[str, Sequence[str], None] = 'a6f0c121ea0f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.alter_column('generations', 'seed',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=True)
    # ### end Alembic commands ###


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.alter_column('generations', 'seed',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_nullable=True)
    # ### end Alembic commands ###

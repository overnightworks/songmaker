"""add model_mode to generations

Revision ID: e5f6a7b8c9d0
Revises: d4a1b2c3e5f6
Create Date: 2026-04-02 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4a1b2c3e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("generations", sa.Column("model_mode", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("generations", "model_mode")

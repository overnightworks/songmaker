"""add xl model variants

Revision ID: 70d4935df72d
Revises: bb091d53ebd4
Create Date: 2026-04-03 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = '70d4935df72d'
down_revision: Union[str, Sequence[str], None] = 'bb091d53ebd4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("INSERT INTO available_models (id, is_active) VALUES ('xl-turbo', false)")
    op.execute("INSERT INTO available_models (id, is_active) VALUES ('xl-sft', false)")
    op.execute("INSERT INTO available_models (id, is_active) VALUES ('xl-base', false)")


def downgrade() -> None:
    op.execute("DELETE FROM available_models WHERE id IN ('xl-turbo', 'xl-sft', 'xl-base')")

"""the stored chat rate limit rows go

Revision ID: c9fba1723c68
Revises: e8db38b3b46c
Create Date: 2026-11-09 13:10:00.000000

"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c9fba1723c68'
down_revision: str | Sequence[str] | None = 'e8db38b3b46c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHAT_KEY = 'chat_rate_limit'

settings = sa.table('rate_limit_settings', sa.column('setting_key'))


def upgrade() -> None:
    op.execute(settings.delete().where(settings.c.setting_key == CHAT_KEY))


def downgrade() -> None:
    """Restores nothing: the deleted limits are not recoverable and no reader of them remains."""

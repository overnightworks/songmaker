"""the reference countdown has a publication row

Revision ID: e8db38b3b46c
Revises: b7d2f95a1c38
Create Date: 2026-11-07 14:55:12.481903

"""
import uuid
from datetime import datetime, timezone
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'e8db38b3b46c'
down_revision: str | Sequence[str] | None = 'b7d2f95a1c38'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COUNTDOWN_KEY = 'reference_countdown_visible_since'

settings = sa.table(
    'rate_limit_settings',
    sa.column('id'),
    sa.column('user_id'),
    sa.column('setting_key'),
    sa.column('value'),
    sa.column('value_text'),
    sa.column('updated_at', sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    op.execute(
        settings.insert().values(
            id=str(uuid.uuid4()),
            user_id=None,
            setting_key=COUNTDOWN_KEY,
            value=0,
            value_text=None,
            updated_at=datetime.now(timezone.utc),
        )
    )


def downgrade() -> None:
    op.execute(settings.delete().where(settings.c.setting_key == COUNTDOWN_KEY))

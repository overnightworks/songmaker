"""references record when they became unused and whether the owner keeps them

Revision ID: 3d9a6b1e5c80
Revises: f71349322716
Create Date: 2026-11-06 13:13:37.177935

"""
from datetime import datetime, timezone
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '3d9a6b1e5c80'
down_revision: str | Sequence[str] | None = 'f71349322716'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'reference_recordings',
        sa.Column('is_kept', sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        'reference_recordings',
        sa.Column('unused_since', sa.DateTime(timezone=True), nullable=True),
    )
    references = sa.table(
        'reference_recordings',
        sa.column('id'),
        sa.column('unused_since', sa.DateTime(timezone=True)),
    )
    versions = sa.table('versions', sa.column('reference_recording_id'))
    takes = sa.table('generations', sa.column('reference_recording_id'))
    op.execute(
        references.update()
        .where(~sa.exists().where(versions.c.reference_recording_id == references.c.id))
        .where(~sa.exists().where(takes.c.reference_recording_id == references.c.id))
        .values(unused_since=datetime.now(timezone.utc))
    )


def downgrade() -> None:
    op.drop_column('reference_recordings', 'unused_since')
    op.drop_column('reference_recordings', 'is_kept')

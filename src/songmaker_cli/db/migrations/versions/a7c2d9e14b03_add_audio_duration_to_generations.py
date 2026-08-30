"""Add audio_duration_sec to generations

A take's own measured length (issue #258), separate from
generation_params.audio_duration — the requested duration parameter,
where 0 means "ACE-Step decides". Nullable float: NULL means "not measured
yet", never 0, so an unmeasured take can be told apart from a genuinely
silent or zero-length one. No backfill — existing rows stay NULL until
something reads and measures them.

Revision ID: a7c2d9e14b03
Revises: 5665abe396ef
Create Date: 2026-08-30 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7c2d9e14b03'
down_revision: Union[str, Sequence[str], None] = '5665abe396ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('generations', sa.Column(
        'audio_duration_sec', sa.Float(), nullable=True,
    ))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('generations', 'audio_duration_sec')

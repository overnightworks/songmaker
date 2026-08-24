"""add is_archived and archived_at to albums

Album archive (issue #223) — a visibility-only flag, not a soft-delete: an
archived album keeps its share links working and is only hidden from the
default library browse, search, and mix/pool. NULL archived_at means not
archived, mirroring the generations.archived_at pattern.

Revision ID: 5665abe396ef
Revises: fbd1b4667d21
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5665abe396ef'
down_revision: Union[str, Sequence[str], None] = 'fbd1b4667d21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('albums', sa.Column(
        'is_archived', sa.Boolean(), nullable=False,
        server_default=sa.text('false'),
    ))
    op.add_column('albums', sa.Column(
        'archived_at', sa.DateTime(timezone=True), nullable=True,
    ))
    op.create_index('ix_albums_archived_at', 'albums', ['archived_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_albums_archived_at', table_name='albums')
    op.drop_column('albums', 'archived_at')
    op.drop_column('albums', 'is_archived')

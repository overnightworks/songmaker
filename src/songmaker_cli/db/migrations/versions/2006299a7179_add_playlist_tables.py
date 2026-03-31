"""add playlist tables

Revision ID: 2006299a7179
Revises: 57a5b30b7c8a
Create Date: 2026-03-31 19:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2006299a7179'
down_revision: Union[str, Sequence[str], None] = '57a5b30b7c8a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'playlists',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('created_by', sa.String(length=36), nullable=True),
        sa.Column('share_slug', sa.String(length=36), nullable=True),
        sa.Column('is_shared', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_playlists_created_by'), 'playlists', ['created_by'])
    op.create_index(op.f('ix_playlists_share_slug'), 'playlists', ['share_slug'], unique=True)

    op.create_table(
        'playlist_entries',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('playlist_id', sa.String(length=36), nullable=False),
        sa.Column('generation_id', sa.String(length=36), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['generation_id'], ['generations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['playlist_id'], ['playlists.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_playlist_entries_playlist_id'), 'playlist_entries', ['playlist_id'])
    op.create_index(
        op.f('ix_playlist_entries_generation_id'), 'playlist_entries', ['generation_id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_playlist_entries_generation_id'), table_name='playlist_entries')
    op.drop_index(op.f('ix_playlist_entries_playlist_id'), table_name='playlist_entries')
    op.drop_table('playlist_entries')
    op.drop_index(op.f('ix_playlists_share_slug'), table_name='playlists')
    op.drop_index(op.f('ix_playlists_created_by'), table_name='playlists')
    op.drop_table('playlists')

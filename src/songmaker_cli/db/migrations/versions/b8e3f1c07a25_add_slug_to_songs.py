"""Add slug to songs

Slice S1 of issue #265: a readable song address (/album/anfield/stadion-lauf-a)
needs a slug per song, unique within its album rather than globally — two
albums may carry the same song slug because the path already separates them.

The index is deliberately not UNIQUE. Song rows are soft-deleted and only
purged later, and write paths outside the REST API (the co-writer's
create_song tool) still insert rows without a slug, so the empty server
default would collide. unique_song_slug() in api_helpers.py owns the
invariant under an advisory lock, the way unique_album_id() does for albums.

Backfill walks each album's songs oldest first and de-duplicates against the
slugs already handed out inside that album, so two songs titled "Intro" in one
album come out as "intro" and "intro-2" instead of colliding.

Revision ID: b8e3f1c07a25
Revises: a7c2d9e14b03
Create Date: 2026-08-30 00:00:00.000000

"""
from collections import defaultdict
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from slugify import slugify as _slugify

# revision identifiers, used by Alembic.
revision: str = 'b8e3f1c07a25'
down_revision: Union[str, Sequence[str], None] = 'a7c2d9e14b03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen copy of api_helpers.slugify()'s contract at this revision: a
# migration must keep producing the same slugs after the helper moves on.
_SLUG_MAX_LENGTH = 220
_SLUG_COUNTER_SUFFIX_BUDGET = 20
_SLUG_BASE_MAX_LENGTH = _SLUG_MAX_LENGTH - _SLUG_COUNTER_SUFFIX_BUDGET
_EMPTY_TITLE_SLUG = "untitled"

_SELECT_SONGS = (
    "SELECT id, title, album_id FROM songs ORDER BY album_id, created_at, id"
)
_UPDATE_SLUG = "UPDATE songs SET slug = :slug WHERE id = :id"


def _slug_base(title: str) -> str:
    return _slugify(title, max_length=_SLUG_BASE_MAX_LENGTH) or _EMPTY_TITLE_SLUG


def _backfill_song_slugs() -> None:
    bind = op.get_bind()
    taken_per_album: dict[str, set[str]] = defaultdict(set)
    for song_id, title, album_id in bind.execute(sa.text(_SELECT_SONGS)).fetchall():
        taken = taken_per_album[album_id]
        base = _slug_base(title)
        candidate = base
        counter = 1
        while candidate in taken:
            counter += 1
            candidate = f"{base}-{counter}"
        taken.add(candidate)
        bind.execute(sa.text(_UPDATE_SLUG), {"slug": candidate, "id": song_id})


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('songs', sa.Column(
        'slug', sa.String(length=_SLUG_MAX_LENGTH), nullable=False, server_default='',
    ))
    op.create_index('ix_songs_album_id_slug', 'songs', ['album_id', 'slug'])
    _backfill_song_slugs()


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_songs_album_id_slug', table_name='songs')
    op.drop_column('songs', 'slug')

"""Promote ix_songs_album_id_slug to a real UNIQUE(album_id, slug)

Slice S1b of issue #265 (#270): b8e3f1c07a25 deliberately left the index
non-unique because the co-writer's create_song/rename_song MCP tools wrote
songs straight through db/queries/songs.py, bypassing the slug assignment
that only lived in song_api.py. #270 closes that gap — mcp_server/tools.py
now calls the same unique_song_slug() as the REST API before every create
and rename — so the invariant can finally move from application code into
the schema itself.

Existing rows can still carry slug='' from before #270 landed (any song the
co-writer created or renamed in that window). upgrade() repairs those first,
reusing b8e3f1c07a25's dedupe strategy: walk empty-slug rows oldest first
per album, derive a base slug from the title, and suffix -2, -3, ... against
every slug already taken in that album (both pre-existing non-empty slugs
and ones this backfill just assigned). Only rows with slug='' are touched;
songs that already carry a real slug keep it untouched.

downgrade() restores the plain (non-unique) index, matching b8e3f1c07a25.

Revision ID: c9d4a2f18e37
Revises: b8e3f1c07a25
Create Date: 2026-08-30 00:00:00.000000

"""
from collections import defaultdict
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from slugify import slugify as _slugify

# revision identifiers, used by Alembic.
revision: str = 'c9d4a2f18e37'
down_revision: Union[str, Sequence[str], None] = 'b8e3f1c07a25'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen copy of api_helpers.slugify()'s contract at this revision, mirroring
# b8e3f1c07a25 — a migration must keep producing the same slugs after the
# helper moves on.
_SLUG_MAX_LENGTH = 220
_SLUG_COUNTER_SUFFIX_BUDGET = 20
_SLUG_BASE_MAX_LENGTH = _SLUG_MAX_LENGTH - _SLUG_COUNTER_SUFFIX_BUDGET
_EMPTY_TITLE_SLUG = "untitled"

_SELECT_TAKEN_SLUGS = "SELECT album_id, slug FROM songs WHERE slug != ''"
_SELECT_EMPTY_SLUG_SONGS = (
    "SELECT id, title, album_id FROM songs WHERE slug = '' "
    "ORDER BY album_id, created_at, id"
)
_UPDATE_SLUG = "UPDATE songs SET slug = :slug WHERE id = :id"


def _slug_base(title: str) -> str:
    return _slugify(title, max_length=_SLUG_BASE_MAX_LENGTH) or _EMPTY_TITLE_SLUG


def _backfill_empty_slugs() -> None:
    bind = op.get_bind()
    taken_per_album: dict[str, set[str]] = defaultdict(set)
    for album_id, slug in bind.execute(sa.text(_SELECT_TAKEN_SLUGS)).fetchall():
        taken_per_album[album_id].add(slug)

    rows = bind.execute(sa.text(_SELECT_EMPTY_SLUG_SONGS)).fetchall()
    for song_id, title, album_id in rows:
        taken = taken_per_album[album_id]
        base = _slug_base(title)
        candidate = base
        counter = 1
        while candidate in taken:
            counter += 1
            candidate = f"{base}-{counter}"
        taken.add(candidate)
        bind.execute(sa.text(_UPDATE_SLUG), {"slug": candidate, "id": song_id})


def _assert_no_empty_slugs_remain() -> None:
    """Second belt: state the invariant even though the ACCESS EXCLUSIVE
    lock already makes it unreachable on PostgreSQL. Costs one query."""
    bind = op.get_bind()
    straggler = bind.execute(sa.text("SELECT count(*) FROM songs WHERE slug = ''")).scalar()
    if straggler:
        raise RuntimeError(f"{straggler} song(s) still carry slug='' after backfill")


def upgrade() -> None:
    """Upgrade schema.

    On PostgreSQL, an old songmaker-web instance can still be serving
    writes while this migration runs (rolling deploy) — it can insert new
    slug='' rows between the backfill and the index creation, or hold a
    long-lived read lock on songs (a co-writer turn's SSE session keeps its
    DB session open for the whole response). Locking the table ACCESS
    EXCLUSIVE before touching it closes that window entirely: either the
    lock is granted immediately (nothing else was writing/reading songs)
    or, within lock_timeout, the migration aborts loudly and rolls back
    instead of silently landing a permanent slug='' row or hanging the
    live app behind a queued lock. SQLite (tests, this migration's own
    throwaway-DB probe) has no comparable lock primitive and doesn't need
    one — the whole migration already runs single-connection there.
    """
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("LOCK TABLE songs IN ACCESS EXCLUSIVE MODE")
    _backfill_empty_slugs()
    op.drop_index('ix_songs_album_id_slug', table_name='songs')
    op.create_index(
        'ix_songs_album_id_slug', 'songs', ['album_id', 'slug'], unique=True,
    )
    _assert_no_empty_slugs_remain()


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_songs_album_id_slug', table_name='songs')
    op.create_index(
        'ix_songs_album_id_slug', 'songs', ['album_id', 'slug'], unique=False,
    )

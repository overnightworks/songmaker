"""Add slug to playlists

Slice S5 of issue #265 (#286): a readable playlist address
(/playlist/friday-night) needs a slug per playlist, unique across every
playlist rather than scoped — playlists have no album to scope by, so this
follows the album precedent (#268: a global id that IS the slug) rather than
the song precedent (#268/#270's per-album scope).

Unlike b8e3f1c07a25/c9d4a2f18e37's two-phase split for songs, this lands the
column and its UNIQUE index in one migration: songs needed the split because
the co-writer's MCP tools wrote straight through db/queries/songs.py,
bypassing the REST API's slug assignment, so the index could only turn
unique once #270 closed that gap. Playlists have no such second write path —
create_playlist/update_playlist in db/queries/playlists.py are called only
from playlist_api.py, and both now require a slug argument, reserved via
unique_playlist_slug() before the one flush — so there is no window in which
this migration's own deploy could still be racing an old write path that
does not know about the column.

Backfill walks every playlist oldest first and de-duplicates against the
slugs already handed out, so two playlists titled "Favorites" come out as
"favorites" and "favorites-2" instead of colliding.

Revision ID: d5f8a3b21c46
Revises: c9d4a2f18e37
Create Date: 2026-08-31 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from slugify import slugify as _slugify

# revision identifiers, used by Alembic.
revision: str = 'd5f8a3b21c46'
down_revision: Union[str, Sequence[str], None] = 'c9d4a2f18e37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen copy of api_helpers.slugify()'s contract at this revision, mirroring
# b8e3f1c07a25/c9d4a2f18e37 — a migration must keep producing the same slugs
# after the helper moves on.
_SLUG_MAX_LENGTH = 220
_SLUG_COUNTER_SUFFIX_BUDGET = 20
_SLUG_BASE_MAX_LENGTH = _SLUG_MAX_LENGTH - _SLUG_COUNTER_SUFFIX_BUDGET
_EMPTY_TITLE_SLUG = "untitled"

_SELECT_PLAYLISTS = "SELECT id, title FROM playlists ORDER BY created_at, id"
_UPDATE_SLUG = "UPDATE playlists SET slug = :slug WHERE id = :id"


def _slug_base(title: str) -> str:
    return _slugify(title, max_length=_SLUG_BASE_MAX_LENGTH) or _EMPTY_TITLE_SLUG


def _backfill_playlist_slugs() -> None:
    bind = op.get_bind()
    taken: set[str] = set()
    for playlist_id, title in bind.execute(sa.text(_SELECT_PLAYLISTS)).fetchall():
        base = _slug_base(title)
        candidate = base
        counter = 1
        while candidate in taken:
            counter += 1
            candidate = f"{base}-{counter}"
        taken.add(candidate)
        bind.execute(sa.text(_UPDATE_SLUG), {"slug": candidate, "id": playlist_id})


def _assert_no_empty_slugs_remain() -> None:
    """Second belt: state the invariant even though the ACCESS EXCLUSIVE
    lock already makes it unreachable on PostgreSQL. Costs one query."""
    bind = op.get_bind()
    straggler = bind.execute(sa.text("SELECT count(*) FROM playlists WHERE slug = ''")).scalar()
    if straggler:
        raise RuntimeError(f"{straggler} playlist(s) still carry slug='' after backfill")


def upgrade() -> None:
    """Upgrade schema.

    On PostgreSQL, an old songmaker-web instance can still be serving writes
    while this migration runs (rolling deploy) — it can insert a new
    slug='' playlist between the backfill and the index creation. Locking
    the table ACCESS EXCLUSIVE before touching it closes that window
    entirely, the same way c9d4a2f18e37 does for songs. SQLite (tests, this
    migration's own throwaway-DB probe) has no comparable lock primitive and
    doesn't need one — the whole migration already runs single-connection
    there.
    """
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("LOCK TABLE playlists IN ACCESS EXCLUSIVE MODE")
    op.add_column('playlists', sa.Column(
        'slug', sa.String(length=_SLUG_MAX_LENGTH), nullable=False, server_default='',
    ))
    _backfill_playlist_slugs()
    _assert_no_empty_slugs_remain()
    op.create_index(op.f('ix_playlists_slug'), 'playlists', ['slug'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_playlists_slug'), table_name='playlists')
    op.drop_column('playlists', 'slug')

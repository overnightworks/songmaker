"""backup_required_files lists what a restore needs

Revision ID: 7d41e0b9a3c5
Revises: c9fba1723c68
Create Date: 2026-11-09 19:10:00.000000

The view names, relative to the audio root, every file the app breaks without. A later
migration that alters or drops a column this view reads must drop and recreate the view,
because PostgreSQL refuses to change a column a view depends on.
"""
from typing import Sequence

from alembic import op

revision: str = '7d41e0b9a3c5'
down_revision: str | Sequence[str] | None = 'c9fba1723c68'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEW = 'backup_required_files'
ADAPTER_SENTINEL = 'adapter_config.json'
COVER_DIRECTORIES = (
    ('albums', 'covers'),
    ('songs', 'song-covers'),
    ('playlists', 'playlist-covers'),
)


def _cover_files(table: str, directory: str) -> str:
    return f"""
    SELECT '{directory}/' || owner.id || '/' || variant.name
    FROM {table} AS owner
    CROSS JOIN LATERAL (VALUES
        ('card.jpg'),
        ('detail.jpg'),
        (CASE WHEN owner.cover_key ~ '\\.jpg$' THEN 'original.jpg' ELSE 'original.png' END)
    ) AS variant (name)
    WHERE owner.cover_key ~ '\\.'"""


def upgrade() -> None:
    selects = [
        "SELECT mp3_path FROM generations WHERE mp3_path <> ''",
        "SELECT storage_path FROM reference_recordings",
        "SELECT audio_path FROM user_lora_samples WHERE audio_path <> ''",
        "SELECT png_path FROM album_cover_suggestions",
        *(_cover_files(table, directory) for table, directory in COVER_DIRECTORIES),
        f"SELECT storage_path || '/{ADAPTER_SENTINEL}' FROM user_loras "
        "WHERE status = 'ready' AND storage_path IS NOT NULL",
    ]
    op.execute(f"CREATE VIEW {VIEW} (path) AS " + "\nUNION\n".join(selects))


def downgrade() -> None:
    op.execute(f"DROP VIEW {VIEW}")

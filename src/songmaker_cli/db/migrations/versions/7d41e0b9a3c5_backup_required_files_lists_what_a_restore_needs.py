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

CREATE_VIEW = r"""CREATE VIEW backup_required_files (path) AS
SELECT mp3_path FROM generations WHERE mp3_path <> ''
UNION
SELECT storage_path FROM reference_recordings
UNION
SELECT audio_path FROM user_lora_samples WHERE audio_path <> ''
UNION
SELECT png_path FROM album_cover_suggestions
UNION

    SELECT 'covers/' || owner.id || '/' || variant.name
    FROM albums AS owner
    CROSS JOIN LATERAL (VALUES
        ('card.jpg'),
        ('detail.jpg'),
        (CASE WHEN owner.cover_key ~ '\.jpg$' THEN 'original.jpg' ELSE 'original.png' END)
    ) AS variant (name)
    WHERE owner.cover_key ~ '\.'
UNION

    SELECT 'song-covers/' || owner.id || '/' || variant.name
    FROM songs AS owner
    CROSS JOIN LATERAL (VALUES
        ('card.jpg'),
        ('detail.jpg'),
        (CASE WHEN owner.cover_key ~ '\.jpg$' THEN 'original.jpg' ELSE 'original.png' END)
    ) AS variant (name)
    WHERE owner.cover_key ~ '\.'
UNION

    SELECT 'playlist-covers/' || owner.id || '/' || variant.name
    FROM playlists AS owner
    CROSS JOIN LATERAL (VALUES
        ('card.jpg'),
        ('detail.jpg'),
        (CASE WHEN owner.cover_key ~ '\.jpg$' THEN 'original.jpg' ELSE 'original.png' END)
    ) AS variant (name)
    WHERE owner.cover_key ~ '\.'
UNION
SELECT storage_path || '/lokr_weights.safetensors' FROM user_loras
WHERE status = 'ready' AND storage_path IS NOT NULL"""


def upgrade() -> None:
    op.execute(CREATE_VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW backup_required_files")

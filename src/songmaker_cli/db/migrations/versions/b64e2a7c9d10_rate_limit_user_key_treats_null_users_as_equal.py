"""one global rate limit row per key

Revision ID: b64e2a7c9d10
Revises: a3c9e1f7b254
Create Date: 2026-11-20 09:00:00.000000

PostgreSQL treats NULL user ids as distinct, so uq_rate_limit_user_key never constrained the
global rows (user_id NULL): two concurrent first Saves of one key left two rows, and the reader
returned the earlier. The upgrade keeps the newest global row of each key (updated_at, then id),
deletes the others, and recreates the constraint so that NULL user ids count as equal.
The downgrade restores the plain constraint; the deleted duplicates stay deleted.
"""
from typing import Sequence

from alembic import op

revision: str = 'b64e2a7c9d10'
down_revision: str | Sequence[str] | None = 'a3c9e1f7b254'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = 'rate_limit_settings'
CONSTRAINT = 'uq_rate_limit_user_key'
COLUMNS = ['user_id', 'setting_key']


def upgrade() -> None:
    op.execute('LOCK TABLE rate_limit_settings IN ACCESS EXCLUSIVE MODE')
    op.execute(
        'DELETE FROM rate_limit_settings WHERE user_id IS NULL AND id NOT IN ('
        'SELECT DISTINCT ON (setting_key) id FROM rate_limit_settings WHERE user_id IS NULL '
        'ORDER BY setting_key, updated_at DESC, id DESC)'
    )
    op.drop_constraint(CONSTRAINT, TABLE, type_='unique')
    op.create_unique_constraint(CONSTRAINT, TABLE, COLUMNS, postgresql_nulls_not_distinct=True)


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_='unique')
    op.create_unique_constraint(CONSTRAINT, TABLE, COLUMNS)

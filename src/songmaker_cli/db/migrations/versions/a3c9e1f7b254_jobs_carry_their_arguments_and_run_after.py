"""jobs carry their arguments and the time they wait for

Revision ID: a3c9e1f7b254
Revises: e5a2c8f1d703
Create Date: 2026-11-18 09:00:00.000000

The payload is the typed record of the job's type (see job_payloads): the arguments a worker runs
the job with. run_after is the time a deferred job waits for before a worker may claim it. A row
written before this migration keeps NULL in both; its arguments still travel in the queue message.
"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'a3c9e1f7b254'
down_revision: str | Sequence[str] | None = 'e5a2c8f1d703'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_COLUMN_TYPES: dict[str, sa.types.TypeEngine] = {
    'payload': postgresql.JSONB(),
    'run_after': sa.DateTime(timezone=True),
}


def upgrade() -> None:
    for name, column_type in NEW_COLUMN_TYPES.items():
        op.add_column('jobs', sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name in reversed(NEW_COLUMN_TYPES):
        op.drop_column('jobs', name)

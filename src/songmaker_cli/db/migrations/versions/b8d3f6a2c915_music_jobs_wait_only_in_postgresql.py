"""the music worker claims its jobs from PostgreSQL only

Revision ID: b8d3f6a2c915
Revises: a3c9e1f7b254
Create Date: 2026-11-18 12:00:00.000000

A music job written before the rows carried their arguments (a3c9e1f7b254) has its arguments only
in its arq message in Redis, which the music worker no longer reads, and nothing on the row can
rebuild them. The upgrade refuses while such a job still waits, so the old worker drains the
queue first instead of the new one failing the jobs.
"""
import sqlalchemy as sa
from alembic import op

revision = 'b8d3f6a2c915'
down_revision = 'a3c9e1f7b254'
branch_labels = None
depends_on = None

JOB_TYPES_WITH_PAYLOAD = (
    'generate', 'lora_training', 'load_model_on_worker', 'download_model_on_worker',
)

jobs = sa.table(
    'jobs',
    sa.column('id', sa.String),
    sa.column('type', sa.String),
    sa.column('status', sa.String),
    sa.column('payload', sa.JSON),
)


def upgrade() -> None:
    waiting_ids = list(op.get_bind().execute(
        sa.select(jobs.c.id).where(
            jobs.c.status == 'queued',
            jobs.c.type.in_(JOB_TYPES_WITH_PAYLOAD),
            jobs.c.payload.is_(None),
        ).order_by(jobs.c.id),
    ).scalars())
    if waiting_ids:
        raise RuntimeError(
            f'{len(waiting_ids)} queued music jobs carry their arguments only in Redis '
            f'({", ".join(waiting_ids[:5])}); stop new requests, let the running music worker '
            'finish them, then upgrade again',
        )


def downgrade() -> None:
    # The upgrade only refuses; it changes no schema or data, so there is nothing to undo.

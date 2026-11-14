"""A job's queue wait is stored as a message token instead of an English sentence

Revision ID: a9d3f1b7c5e2
Revises: d2f6b8a4c7e1
Create Date: 2026-11-14 21:00:00.000000

jobs.queue_reason (Text) becomes jobs.queue_reason_message (JSON, a catalog key and the values
of its gaps). The two sentences a writer ever stored map to their keys through the frozen table
below; any other value becomes NULL, which is a transient hint that the next requeue rewrites.
The downgrade restores the two sentences.
"""
from __future__ import annotations

import logging
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9d3f1b7c5e2"
down_revision: str | Sequence[str] | None = "d2f6b8a4c7e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

# why: frozen on purpose, so the migration never reads the catalog a later revision changes.
STORED_MESSAGE_KEYS: dict[str, str] = {
    "Waiting for LoRA training on this GPU.": "jobWait.voiceTraining",
    "Waiting for queued generations on this GPU.": "jobWait.queuedGenerations",
}
SHAPE_CONSTRAINT = "ck_jobs_queue_reason_message_shape"
SHAPE_CHECK = (
    "queue_reason_message IS NULL OR ("
    "COALESCE(json_typeof(queue_reason_message->'key'), '') = 'string' "
    "AND COALESCE(json_typeof(queue_reason_message->'values'), '') = 'object')"
)

jobs = sa.table(
    "jobs",
    sa.column("queue_reason", sa.Text),
    sa.column("queue_reason_message", sa.JSON(none_as_null=True)),
)


def upgrade() -> None:
    op.add_column(
        "jobs", sa.Column("queue_reason_message", sa.JSON(none_as_null=True), nullable=True),
    )
    connection = op.get_bind()
    for sentence, key in STORED_MESSAGE_KEYS.items():
        connection.execute(
            sa.update(jobs)
            .where(jobs.c.queue_reason == sentence)
            .values(queue_reason_message={"key": key, "values": {}}),
        )
    unrecognized = connection.execute(
        sa.select(sa.func.count())
        .select_from(jobs)
        .where(jobs.c.queue_reason.is_not(None), jobs.c.queue_reason_message.is_(None)),
    ).scalar_one()
    logger.info("Stored queue waits as messages: %d unrecognized waits became NULL", unrecognized)
    op.create_check_constraint(SHAPE_CONSTRAINT, "jobs", SHAPE_CHECK)
    op.drop_column("jobs", "queue_reason")


def downgrade() -> None:
    op.add_column("jobs", sa.Column("queue_reason", sa.Text(), nullable=True))
    connection = op.get_bind()
    for sentence, key in STORED_MESSAGE_KEYS.items():
        connection.execute(
            sa.update(jobs)
            .where(jobs.c.queue_reason_message["key"].as_string() == key)
            .values(queue_reason=sentence),
        )
    op.drop_constraint(SHAPE_CONSTRAINT, "jobs", type_="check")
    op.drop_column("jobs", "queue_reason_message")

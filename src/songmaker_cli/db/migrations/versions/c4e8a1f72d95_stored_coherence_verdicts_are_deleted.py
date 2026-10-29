"""Delete the old judge's stored coherence verdicts from every scores row."""

import logging

import sqlalchemy as sa
from alembic import op

revision = "c4e8a1f72d95"
down_revision = "a1d7c5e93b60"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

VERDICT_KEYS = ("lyrical_coherence", "lyrical_summary")

scores = sa.table(
    "scores",
    sa.column("id", sa.String),
    sa.column("value", sa.JSON),
)


def upgrade() -> None:
    connection = op.get_bind()
    changed = 0
    for row_id, value in connection.execute(sa.select(scores.c.id, scores.c.value)).all():
        if not isinstance(value, dict) or not any(key in value for key in VERDICT_KEYS):
            continue
        remaining = {key: kept for key, kept in value.items() if key not in VERDICT_KEYS}
        connection.execute(sa.update(scores).where(scores.c.id == row_id).values(value=remaining))
        changed += 1
    logger.info("Deleted stored coherence verdicts: changed %d scores rows", changed)


def downgrade() -> None:
    raise RuntimeError(
        "Deleting the stored coherence verdicts is irreversible; restore a backup instead",
    )

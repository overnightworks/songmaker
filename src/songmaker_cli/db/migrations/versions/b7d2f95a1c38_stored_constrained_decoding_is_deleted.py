"""Delete the stored `constrained_decoding` key from every take's generation params."""

import logging

import sqlalchemy as sa
from alembic import op

revision = "b7d2f95a1c38"
down_revision = "a4c7e19b3d52"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

KEY = "constrained_decoding"

generations = sa.table(
    "generations",
    sa.column("id", sa.String),
    sa.column("generation_params", sa.JSON),
)


def upgrade() -> None:
    connection = op.get_bind()
    changed = 0
    rows = connection.execute(sa.select(generations.c.id, generations.c.generation_params)).all()
    for row_id, params in rows:
        if not isinstance(params, dict) or KEY not in params:
            continue
        remaining = {key: kept for key, kept in params.items() if key != KEY}
        connection.execute(
            sa.update(generations)
            .where(generations.c.id == row_id)
            .values(generation_params=remaining),
        )
        changed += 1
    logger.info("Deleted stored constrained_decoding: changed %d generations rows", changed)


def downgrade() -> None:
    raise RuntimeError(
        "Deleting the stored constrained_decoding is irreversible; restore a backup instead",
    )

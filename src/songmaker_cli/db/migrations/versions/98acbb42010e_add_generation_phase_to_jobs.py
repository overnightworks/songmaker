"""Add the generation phase to jobs and rename its estimate anchor.

``running_since`` becomes ``generation_started_at``: the remaining-time
estimate now counts from the first generating phase, not from entering
RUNNING, so a cold model load no longer inflates it. The rename keeps
existing values.

Revision ID: 98acbb42010e
Revises: d52826563268
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "98acbb42010e"
down_revision: str | Sequence[str] | None = "d52826563268"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("running_since", new_column_name="generation_started_at")
        batch_op.add_column(sa.Column("phase", sa.String(20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("phase")
        batch_op.alter_column("generation_started_at", new_column_name="running_since")

"""jobs remember their version

Revision ID: e3a91c5d7f20
Revises: c4d7e1a9b3f6
Create Date: 2026-10-30 00:00:00.000000

"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'e3a91c5d7f20'
down_revision: str | Sequence[str] | None = 'c4d7e1a9b3f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMN = "version_id"
FOREIGN_KEY = "fk_jobs_version_id_versions"
INDEX = "ix_jobs_version_id"


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column(COLUMN, sa.String(length=36), nullable=True))
        batch.create_index(INDEX, [COLUMN])
        batch.create_foreign_key(FOREIGN_KEY, "versions", [COLUMN], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_constraint(FOREIGN_KEY, type_="foreignkey")
        batch.drop_index(INDEX)
        batch.drop_column(COLUMN)

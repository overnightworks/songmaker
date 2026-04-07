"""add acestep_workers table

Revision ID: a7b8c9d0e1f2
Revises: 70d4935df72d
Create Date: 2026-04-07 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "70d4935df72d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "acestep_workers",
        sa.Column("id", sa.String(length=50), primary_key=True),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("gpu_id", sa.Integer(), nullable=True),
        sa.Column("vram_total_gb", sa.Float(), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_register_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("acestep_workers")

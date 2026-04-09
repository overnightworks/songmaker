"""Expand jobs.type from VARCHAR(20) to VARCHAR(40)

The original schema reserved 20 characters for ``jobs.type``. That fits
"generate", "score", "chat", and "load_model_on_worker" (exactly 20), but
"download_model_on_worker" is 24 characters and would fail insert with
``value too long for type character varying(20)``. The download-model admin
endpoint had never been exercised because the UI only exposes the button
when a non-downloaded model is available — raising the column width
unblocks it before the next XL weights release.

Revision ID: c5d6e7f8a9b0
Revises: b2c3d4e5f6a7
Create Date: 2026-04-09 18:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c5d6e7f8a9b0'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.alter_column(
        "jobs",
        "type",
        existing_type=sa.String(20),
        type_=sa.String(40),
        existing_nullable=False,
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.alter_column(
        "jobs",
        "type",
        existing_type=sa.String(40),
        type_=sa.String(20),
        existing_nullable=False,
    )

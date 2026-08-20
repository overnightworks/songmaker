"""add whisper_cues to generations

Revision ID: 202b0514cdde
Revises: e3f4a5b6c7d8
Create Date: 2026-08-21 01:38:25.349425

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "202b0514cdde"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generations",
        sa.Column("whisper_cues", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generations", "whisper_cues")

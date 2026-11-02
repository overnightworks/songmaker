"""users choose their theme

Revision ID: d8b4f2a6c1e9
Revises: e3a91c5d7f20
Create Date: 2026-10-31 00:00:00.000000

"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'd8b4f2a6c1e9'
down_revision: str | Sequence[str] | None = 'e3a91c5d7f20'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_THEME_CHECK = "theme IN ('light', 'dark', 'system')"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("theme", sa.String(length=6), nullable=False, server_default="system"),
    )
    with op.batch_alter_table("users") as batch_op:
        batch_op.create_check_constraint("ck_users_theme", _THEME_CHECK)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_theme", type_="check")
        batch_op.drop_column("theme")

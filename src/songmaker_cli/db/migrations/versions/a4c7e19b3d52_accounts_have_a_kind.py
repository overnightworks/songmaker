"""accounts have a kind

Revision ID: a4c7e19b3d52
Revises: 3d9a6b1e5c80
Create Date: 2026-11-07 00:00:00.000000

"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a4c7e19b3d52'
down_revision: str | Sequence[str] | None = '3d9a6b1e5c80'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KIND_CHECK = "kind IN ('person', 'agent')"


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("kind", sa.String(length=6), nullable=False, server_default="person"),
    )
    op.create_check_constraint("ck_users_kind", "users", _KIND_CHECK)


def downgrade() -> None:
    op.drop_constraint("ck_users_kind", "users", type_="check")
    op.drop_column("users", "kind")

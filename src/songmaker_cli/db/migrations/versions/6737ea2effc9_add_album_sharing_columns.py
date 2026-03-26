"""add album sharing columns

Revision ID: 6737ea2effc9
Revises: 2a5ce2401805
Create Date: 2026-03-26 15:13:51.785375

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "6737ea2effc9"
down_revision: Union[str, Sequence[str], None] = "2a5ce2401805"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("albums", sa.Column("share_slug", sa.String(36), nullable=True))
    op.add_column("albums", sa.Column("is_shared", sa.Boolean, nullable=False, server_default="0"))
    op.create_index(op.f("ix_albums_share_slug"), "albums", ["share_slug"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_albums_share_slug"), table_name="albums")
    op.drop_column("albums", "is_shared")
    op.drop_column("albums", "share_slug")

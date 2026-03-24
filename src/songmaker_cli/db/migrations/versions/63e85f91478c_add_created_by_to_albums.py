"""add created_by to albums

Revision ID: 63e85f91478c
Revises: 2a0ee990833a
Create Date: 2026-03-24 17:44:49.499953

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '63e85f91478c'
down_revision: Union[str, Sequence[str], None] = '2a0ee990833a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('albums', sa.Column('created_by', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_albums_created_by'), 'albums', ['created_by'], unique=False)

    # Assign existing albums to the first admin user
    conn = op.get_bind()
    admin = conn.execute(
        sa.text("SELECT id FROM users WHERE role = 'admin' ORDER BY created_at LIMIT 1")
    ).fetchone()
    if admin:
        conn.execute(
            sa.text("UPDATE albums SET created_by = :uid WHERE created_by IS NULL"),
            {"uid": admin[0]},
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_albums_created_by'), table_name='albums')
    op.drop_column('albums', 'created_by')

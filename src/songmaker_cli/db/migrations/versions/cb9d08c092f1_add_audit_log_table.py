"""add audit_log table

Revision ID: cb9d08c092f1
Revises: dae031c49b2b
Create Date: 2026-03-25 14:36:39.097891

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'cb9d08c092f1'
down_revision: Union[str, Sequence[str], None] = 'dae031c49b2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('audit_log',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=True),
    sa.Column('action', sa.String(length=30), nullable=False),
    sa.Column('resource_type', sa.String(length=30), nullable=False),
    sa.Column('resource_id', sa.String(length=64), nullable=False),
    sa.Column('detail', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_log_action'), 'audit_log', ['action'], unique=False)
    op.create_index(op.f('ix_audit_log_created_at'), 'audit_log', ['created_at'], unique=False)
    op.create_index(op.f('ix_audit_log_user_id'), 'audit_log', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_audit_log_user_id'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_created_at'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_action'), table_name='audit_log')
    op.drop_table('audit_log')

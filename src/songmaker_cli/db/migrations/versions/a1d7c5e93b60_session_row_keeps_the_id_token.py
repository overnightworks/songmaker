"""The session row keeps the sign-in's ID token, so signing out can end the issuer's session."""

import sqlalchemy as sa
from alembic import op

revision = "a1d7c5e93b60"
down_revision = "7c3e91d0a4b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_sessions") as batch_op:
        batch_op.add_column(sa.Column("id_token", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_sessions") as batch_op:
        batch_op.drop_column("id_token")

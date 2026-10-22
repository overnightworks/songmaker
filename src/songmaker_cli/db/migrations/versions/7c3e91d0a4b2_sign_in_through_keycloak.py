"""Sign in through Keycloak: drop the password-era shapes, end old sessions, keep refresh tokens."""

import sqlalchemy as sa
from alembic import op

revision = "7c3e91d0a4b2"
down_revision = "1968214a67b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Every cookie of the 0.14 library is refused by 0.19 anyway; deleting the
    # rows keeps the table from holding sessions nobody can present.
    op.execute("DELETE FROM user_sessions")
    op.drop_table("login_attempts")
    with op.batch_alter_table("user_sessions") as batch_op:
        batch_op.add_column(sa.Column("refresh_token", sa.Text, nullable=True))
        batch_op.drop_column("ip_address")
        batch_op.drop_column("user_agent")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_username")
        batch_op.drop_column("password_hash")
        batch_op.drop_column("is_active")


def downgrade() -> None:
    """Recreate the shapes empty; the data comes back only from a restore.

    The unique username index cannot be recreated once two accounts share a
    username, which the sign-in allows; rolling back is the paired restore.
    """
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        )
        batch_op.add_column(
            sa.Column("password_hash", sa.String(200), nullable=False, server_default=""),
        )
        batch_op.create_index("ix_users_username", ["username"], unique=True)
    with op.batch_alter_table("user_sessions") as batch_op:
        batch_op.drop_column("refresh_token")
        batch_op.add_column(
            sa.Column("user_agent", sa.String(500), nullable=False, server_default=""),
        )
        batch_op.add_column(
            sa.Column("ip_address", sa.String(45), nullable=False, server_default=""),
        )
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_login_attempts_ip_address"), "login_attempts", ["ip_address"])

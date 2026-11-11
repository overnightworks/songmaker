"""The session row keeps the account's language tag from the sign-in."""

from typing import Final

import sqlalchemy as sa
from alembic import op

revision = "c4e8a2d6f913"
down_revision = "7d41e0b9a3c5"
branch_labels = None
depends_on = None

ACCOUNT_LANGUAGE_MAX_CHARS: Final = 35


def upgrade() -> None:
    with op.batch_alter_table("user_sessions") as batch_op:
        batch_op.add_column(
            sa.Column("account_language", sa.String(ACCOUNT_LANGUAGE_MAX_CHARS), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("user_sessions") as batch_op:
        batch_op.drop_column("account_language")

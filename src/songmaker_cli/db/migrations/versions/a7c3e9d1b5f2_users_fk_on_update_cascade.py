"""Let every foreign key to users.id follow a changed users.id.

Each constraint keeps its name and its ON DELETE rule; only ON UPDATE changes.
SQLite cannot alter a constraint in place and is not a deployment target, so
the migration changes nothing there.
"""

from collections.abc import Sequence
from typing import Final, NamedTuple

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e9d1b5f2"
down_revision: str | Sequence[str] | None = "1968214a67b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USERS: Final = "users"
CASCADE: Final = "CASCADE"
SET_NULL: Final = "SET NULL"


class UserForeignKey(NamedTuple):
    table: str
    column: str
    ondelete: str | None


USER_FOREIGN_KEYS: Final = (
    UserForeignKey("albums", "created_by", SET_NULL),
    UserForeignKey("user_song_work", "user_id", CASCADE),
    UserForeignKey("generations", "created_by", SET_NULL),
    UserForeignKey("playlists", "created_by", SET_NULL),
    UserForeignKey("generation_presets", "created_by", SET_NULL),
    UserForeignKey("jobs", "user_id", SET_NULL),
    UserForeignKey("resource_event_cursors", "user_id", CASCADE),
    UserForeignKey("resource_events", "user_id", CASCADE),
    UserForeignKey("user_sessions", "user_id", None),
    UserForeignKey("rate_limit_settings", "user_id", CASCADE),
    UserForeignKey("conversations", "user_id", CASCADE),
    UserForeignKey("cowriter_user_memories", "user_id", CASCADE),
    UserForeignKey("user_loras", "user_id", CASCADE),
    UserForeignKey("audit_log", "user_id", SET_NULL),
)


def _constraint_name(foreign_key: UserForeignKey) -> str:
    inspector = sa.inspect(op.get_bind())
    names = [
        reflected["name"]
        for reflected in inspector.get_foreign_keys(foreign_key.table)
        if reflected["referred_table"] == USERS
        and reflected["constrained_columns"] == [foreign_key.column]
    ]
    if len(names) != 1:
        message = (
            f"expected one foreign key from {foreign_key.table}."
            f"{foreign_key.column} to {USERS}, found {len(names)}"
        )
        raise RuntimeError(message)
    return names[0]


def _recreate(*, onupdate: str | None) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for foreign_key in USER_FOREIGN_KEYS:
        name = _constraint_name(foreign_key)
        op.drop_constraint(name, foreign_key.table, type_="foreignkey")
        op.create_foreign_key(
            name,
            foreign_key.table,
            USERS,
            [foreign_key.column],
            ["id"],
            ondelete=foreign_key.ondelete,
            onupdate=onupdate,
        )


def upgrade() -> None:
    _recreate(onupdate=CASCADE)


def downgrade() -> None:
    _recreate(onupdate=None)

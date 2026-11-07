"""The migration that adds the row recording when the reference countdown was first shown."""

from __future__ import annotations

import uuid

from alembic import command
from sqlalchemy import text
from support.migration_chain import is_on_the_single_chain
from support.reference_link_migration import execute

from songmaker_cli.constants import SETTING_REFERENCE_COUNTDOWN_VISIBLE_SINCE

PREVIOUS_REVISION = "3d9a6b1e5c80"
COUNTDOWN_REVISION = "e8db38b3b46c"


def _rows_of_the_countdown_key(engine) -> list[tuple]:
    with engine.connect() as connection:
        return list(connection.execute(
            text(
                "SELECT id, user_id, value, value_text FROM rate_limit_settings "
                "WHERE setting_key = :key",
            ),
            {"key": SETTING_REFERENCE_COUNTDOWN_VISIBLE_SINCE},
        ))


def test_the_upgrade_adds_one_unpublished_global_row_with_a_fresh_uuid4(
    reference_link_database,
) -> None:
    config, engine = reference_link_database
    command.upgrade(config, PREVIOUS_REVISION)
    assert _rows_of_the_countdown_key(engine) == []

    command.upgrade(config, COUNTDOWN_REVISION)

    [(row_id, user_id, value, value_text)] = _rows_of_the_countdown_key(engine)
    assert uuid.UUID(row_id).version == 4
    assert (user_id, value, value_text) == (None, 0, None)


def test_the_downgrade_removes_the_row_and_the_next_upgrade_starts_a_new_epoch(
    reference_link_database,
) -> None:
    config, engine = reference_link_database
    command.upgrade(config, COUNTDOWN_REVISION)
    [(first_epoch, *_)] = _rows_of_the_countdown_key(engine)
    execute(
        engine,
        "UPDATE rate_limit_settings SET value_text = '2026-11-07T10:00:00+00:00' WHERE id = :id",
        id=first_epoch,
    )

    command.downgrade(config, PREVIOUS_REVISION)
    assert _rows_of_the_countdown_key(engine) == []

    command.upgrade(config, COUNTDOWN_REVISION)
    [(second_epoch, _, _, second_value_text)] = _rows_of_the_countdown_key(engine)
    assert second_epoch != first_epoch
    assert second_value_text is None


def test_the_countdown_revision_is_on_the_single_chain() -> None:
    assert is_on_the_single_chain(COUNTDOWN_REVISION)

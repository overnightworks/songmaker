"""The migration that deletes the stored chat rate limit rows."""

from __future__ import annotations

from alembic import command
from sqlalchemy import text
from support.migration_chain import is_on_the_single_chain, seeded_then_upgraded
from support.reference_link_migration import execute, seed_users

PREVIOUS_REVISION = "e8db38b3b46c"
CHAT_REVISION = "c9fba1723c68"
CHAT_KEY = "chat_rate_limit"


def _seed_limit_rows(engine) -> None:
    seed_users(engine)
    for row_id, user_id, key in (
        ("chat-global", None, CHAT_KEY),
        ("chat-override", "u1", CHAT_KEY),
        ("generation-global", None, "generation_rate_limit"),
        ("scoring-override", "u2", "scoring_rate_limit"),
    ):
        execute(
            engine,
            "INSERT INTO rate_limit_settings (id, user_id, setting_key, value, updated_at) "
            "VALUES (:id, :user_id, :key, 5, CURRENT_TIMESTAMP)",
            id=row_id,
            user_id=user_id,
            key=key,
        )


def _stored_ids(engine) -> set[str]:
    with engine.connect() as connection:
        return {row[0] for row in connection.execute(text("SELECT id FROM rate_limit_settings"))}


def test_the_upgrade_deletes_every_chat_row_and_keeps_the_other_rows(
    reference_link_database,
) -> None:
    engine = seeded_then_upgraded(
        reference_link_database, PREVIOUS_REVISION, CHAT_REVISION, _seed_limit_rows,
    )

    assert {"chat-global", "chat-override"}.isdisjoint(_stored_ids(engine))
    assert {"generation-global", "scoring-override"} <= _stored_ids(engine)


def test_the_upgrade_runs_on_a_database_without_chat_rows(reference_link_database) -> None:
    config, engine = reference_link_database
    command.upgrade(config, PREVIOUS_REVISION)
    before = _stored_ids(engine)

    command.upgrade(config, CHAT_REVISION)

    assert _stored_ids(engine) == before


def test_the_downgrade_restores_no_chat_row(reference_link_database) -> None:
    engine = seeded_then_upgraded(
        reference_link_database, PREVIOUS_REVISION, CHAT_REVISION, _seed_limit_rows,
    )
    config = reference_link_database[0]

    command.downgrade(config, PREVIOUS_REVISION)

    assert {"chat-global", "chat-override"}.isdisjoint(_stored_ids(engine))
    assert {"generation-global", "scoring-override"} <= _stored_ids(engine)


def test_the_chat_revision_is_on_the_single_chain() -> None:
    assert is_on_the_single_chain(CHAT_REVISION)

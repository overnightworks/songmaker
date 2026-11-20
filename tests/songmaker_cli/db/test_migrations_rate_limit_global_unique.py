"""The migration that lets one global row per rate limit key stand."""

from __future__ import annotations

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from support.migration_chain import seeded_then_upgraded
from support.reference_link_migration import execute, seed_users

from songmaker_cli.constants import (
    SETTING_GENERATION_RATE_LIMIT,
    SETTING_MAX_QUEUE_DEPTH,
    SETTING_REFERENCE_COUNTDOWN_VISIBLE_SINCE,
    SETTING_SCORING_RATE_LIMIT,
)

PREVIOUS_REVISION = "b8d3f6a2c915"
UNIQUE_REVISION = "b64e2a7c9d10"


@pytest.fixture
def countdown_text() -> str:
    return "2026-01-02T03:04:05+00:00"


def _insert_row(
    engine,
    row_id: str,
    user_id: str | None,
    key: str,
    value: int,
    updated_at: str,
    value_text: str | None = None,
) -> None:
    execute(
        engine,
        "INSERT INTO rate_limit_settings (id, user_id, setting_key, value, value_text, updated_at) "
        "VALUES (:id, :user_id, :key, :value, :value_text, CAST(:updated_at AS timestamptz))",
        id=row_id,
        user_id=user_id,
        key=key,
        value=value,
        value_text=value_text,
        updated_at=updated_at,
    )


def _seed_duplicates(engine, countdown_text: str) -> None:
    seed_users(engine)
    _insert_row(engine, "key-old", None, SETTING_GENERATION_RATE_LIMIT, 1, "2026-01-01T00:00:00Z")
    _insert_row(
        engine, "key-newest", None, SETTING_GENERATION_RATE_LIMIT, 3, "2026-01-03T00:00:00Z"
    )
    _insert_row(
        engine, "key-middle", None, SETTING_GENERATION_RATE_LIMIT, 2, "2026-01-02T00:00:00Z"
    )
    _insert_row(engine, "tie-a", None, SETTING_SCORING_RATE_LIMIT, 4, "2026-01-01T00:00:00Z")
    _insert_row(engine, "tie-b", None, SETTING_SCORING_RATE_LIMIT, 5, "2026-01-01T00:00:00Z")
    _insert_row(
        engine, "key-override", "u1", SETTING_GENERATION_RATE_LIMIT, 9, "2026-01-01T00:00:00Z"
    )
    _insert_row(engine, "lone", None, SETTING_MAX_QUEUE_DEPTH, 6, "2026-01-01T00:00:00Z")
    execute(
        engine,
        "UPDATE rate_limit_settings SET value_text = :value_text WHERE setting_key = :key",
        value_text=countdown_text,
        key=SETTING_REFERENCE_COUNTDOWN_VISIBLE_SINCE,
    )


def _rate_limit_rows(engine) -> dict[str, tuple]:
    with engine.connect() as connection:
        return {
            row[0]: tuple(row[1:])
            for row in connection.execute(
                text("SELECT id, user_id, setting_key, value, value_text FROM rate_limit_settings")
            )
        }


def _countdown_row(engine) -> tuple:
    rows = [
        (row_id, *rest)
        for row_id, rest in _rate_limit_rows(engine).items()
        if rest[1] == SETTING_REFERENCE_COUNTDOWN_VISIBLE_SINCE
    ]
    assert len(rows) == 1
    return rows[0]


def _upgraded_with_duplicates(reference_link_database, countdown_text: str):
    return seeded_then_upgraded(
        reference_link_database,
        PREVIOUS_REVISION,
        UNIQUE_REVISION,
        lambda engine: _seed_duplicates(engine, countdown_text),
    )


def test_the_upgrade_keeps_the_newest_global_row_of_each_key_and_every_other_row(
    reference_link_database,
    countdown_text,
) -> None:
    engine = _upgraded_with_duplicates(reference_link_database, countdown_text)

    assert set(_rate_limit_rows(engine)) >= {"key-newest", "tie-b", "key-override", "lone"}
    assert {"key-old", "key-middle", "tie-a"}.isdisjoint(_rate_limit_rows(engine))


def test_the_upgrade_leaves_the_countdown_row_untouched(
    reference_link_database,
    countdown_text,
) -> None:
    config, engine = reference_link_database
    command.upgrade(config, PREVIOUS_REVISION)
    _seed_duplicates(engine, countdown_text)
    before = _countdown_row(engine)

    command.upgrade(config, UNIQUE_REVISION)

    assert _countdown_row(engine) == before
    assert before[-1] == countdown_text


def test_a_second_global_row_of_one_key_is_refused_after_the_upgrade(
    reference_link_database,
    countdown_text,
) -> None:
    engine = _upgraded_with_duplicates(reference_link_database, countdown_text)

    with pytest.raises(IntegrityError):
        _insert_row(engine, "again", None, SETTING_GENERATION_RATE_LIMIT, 8, "2026-02-01T00:00:00Z")


def test_a_per_user_row_of_a_key_with_a_global_row_is_still_accepted_after_the_upgrade(
    reference_link_database,
    countdown_text,
) -> None:
    engine = _upgraded_with_duplicates(reference_link_database, countdown_text)

    _insert_row(
        engine, "other-override", "u2", SETTING_GENERATION_RATE_LIMIT, 8, "2026-02-01T00:00:00Z"
    )

    assert "other-override" in _rate_limit_rows(engine)


def test_the_downgrade_allows_a_second_global_row_again_and_restores_no_deleted_row(
    reference_link_database,
    countdown_text,
) -> None:
    engine = _upgraded_with_duplicates(reference_link_database, countdown_text)
    config = reference_link_database[0]

    command.downgrade(config, PREVIOUS_REVISION)
    _insert_row(engine, "again", None, SETTING_GENERATION_RATE_LIMIT, 8, "2026-02-01T00:00:00Z")

    assert set(_rate_limit_rows(engine)) >= {"key-newest", "tie-b", "key-override", "lone", "again"}
    assert {"key-old", "key-middle", "tie-a"}.isdisjoint(_rate_limit_rows(engine))

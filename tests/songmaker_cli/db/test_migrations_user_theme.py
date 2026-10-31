"""The migration that lets a person choose their theme."""

from __future__ import annotations

import importlib

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from support.migration_chain import is_on_the_single_chain
from support.reference_link_migration import execute, seed_users

MIGRATION_MODULE = "songmaker_cli.db.migrations.versions.d8b4f2a6c1e9_users_choose_their_theme"
PREVIOUS_REVISION = "e3a91c5d7f20"
COLUMN = "theme"


def _theme_migration():
    return importlib.import_module(MIGRATION_MODULE)


def _users_table_columns(engine) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("users")}


def _themes(engine) -> list[str]:
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT {COLUMN} FROM users ORDER BY id")).scalars().all()


def _upgraded_with_two_people(database):
    config, engine = database
    command.upgrade(config, PREVIOUS_REVISION)
    seed_users(engine)
    command.upgrade(config, _theme_migration().revision)
    return config, engine


def test_the_migration_follows_the_previous_revision_on_the_single_chain():
    assert _theme_migration().down_revision == PREVIOUS_REVISION
    assert is_on_the_single_chain(_theme_migration().revision)


def test_upgrade_gives_every_existing_person_the_device_choice(reference_link_database):
    _, engine = _upgraded_with_two_people(reference_link_database)
    assert _themes(engine) == ["system", "system"]


def test_a_person_added_afterwards_without_a_theme_gets_the_device_choice(reference_link_database):
    _, engine = _upgraded_with_two_people(reference_link_database)
    execute(
        engine,
        "INSERT INTO users (id, username, role, created_at, updated_at) "
        "VALUES ('u3', 'u3', 'user', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
    )
    assert _themes(engine) == ["system", "system", "system"]


def test_the_database_refuses_a_value_outside_the_three_ways(reference_link_database):
    _, engine = _upgraded_with_two_people(reference_link_database)
    with pytest.raises(IntegrityError):
        execute(engine, f"UPDATE users SET {COLUMN} = 'auto' WHERE id = 'u1'")


def test_the_database_refuses_no_theme(reference_link_database):
    _, engine = _upgraded_with_two_people(reference_link_database)
    with pytest.raises(IntegrityError):
        execute(engine, f"UPDATE users SET {COLUMN} = NULL WHERE id = 'u1'")


def test_downgrade_drops_the_column_and_its_check_and_keeps_the_people(reference_link_database):
    config, engine = _upgraded_with_two_people(reference_link_database)
    command.downgrade(config, PREVIOUS_REVISION)
    assert COLUMN not in _users_table_columns(engine)
    assert not any(
        constraint["name"] == "ck_users_theme"
        for constraint in inspect(engine).get_check_constraints("users")
    )
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM users")).scalar_one() == 2
    command.upgrade(config, _theme_migration().revision)
    assert COLUMN in _users_table_columns(engine)

"""The migration that gives every account a kind."""

from __future__ import annotations

import importlib

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from support.migration_chain import column_names, is_on_the_single_chain, seeded_then_upgraded
from support.reference_link_migration import execute, seed_users

MIGRATION_MODULE = "songmaker_cli.db.migrations.versions.a4c7e19b3d52_accounts_have_a_kind"
PREVIOUS_REVISION = "3d9a6b1e5c80"
COLUMN = "kind"
MIGRATION = importlib.import_module(MIGRATION_MODULE)


def _stored_kinds(engine) -> list[str]:
    with engine.connect() as connection:
        return list(connection.execute(text("SELECT kind FROM users ORDER BY id")).scalars())


def _set_kind_of_u1(engine, kind: str | None) -> None:
    execute(engine, "UPDATE users SET kind = :kind WHERE id = 'u1'", kind=kind)


def _upgraded_with_two_accounts(database):
    return seeded_then_upgraded(database, PREVIOUS_REVISION, MIGRATION.revision, seed_users)


def test_the_migration_follows_the_previous_revision_on_the_single_chain():
    assert MIGRATION.down_revision == PREVIOUS_REVISION
    assert is_on_the_single_chain(MIGRATION.revision)


def test_upgrade_makes_every_existing_account_a_person(reference_link_database):
    engine = _upgraded_with_two_accounts(reference_link_database)
    assert _stored_kinds(engine) == ["person", "person"]


def test_an_account_added_afterwards_without_a_kind_is_a_person(reference_link_database):
    engine = _upgraded_with_two_accounts(reference_link_database)
    execute(
        engine,
        "INSERT INTO users (id, username, role, created_at, updated_at) "
        "VALUES ('u3', 'u3', 'user', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
    )
    assert _stored_kinds(engine) == ["person", "person", "person"]


def test_the_database_accepts_an_agent_and_refuses_any_other_value(reference_link_database):
    engine = _upgraded_with_two_accounts(reference_link_database)
    _set_kind_of_u1(engine, "agent")
    assert _stored_kinds(engine) == ["agent", "person"]
    with pytest.raises(IntegrityError):
        _set_kind_of_u1(engine, "robot")


def test_the_database_refuses_no_kind(reference_link_database):
    engine = _upgraded_with_two_accounts(reference_link_database)
    with pytest.raises(IntegrityError):
        _set_kind_of_u1(engine, None)


def test_downgrade_drops_the_column_and_its_check_and_keeps_the_accounts(reference_link_database):
    config, _ = reference_link_database
    engine = _upgraded_with_two_accounts(reference_link_database)
    with engine.connect() as connection:
        accounts_before = connection.execute(text("SELECT id FROM users ORDER BY id")).all()

    command.downgrade(config, PREVIOUS_REVISION)

    checks = {check["name"] for check in inspect(engine).get_check_constraints("users")}
    assert (COLUMN in column_names(engine, "users"), "ck_users_kind" in checks) == (False, False)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM users ORDER BY id")).all() == accounts_before
    command.upgrade(config, MIGRATION.revision)
    assert COLUMN in column_names(engine, "users")

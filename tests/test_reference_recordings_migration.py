"""The migration that creates reference_recordings, on SQLite and PostgreSQL."""

from __future__ import annotations

import importlib
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from support.migration_chain import is_on_the_single_chain

MIGRATION = "songmaker_cli.db.migrations.versions.5b2e9d4a7c31_reference_recordings_are_records"
PREVIOUS_REVISION = "c4e8a1f72d95"
TABLE = "reference_recordings"


def _alembic_config() -> Config:
    return Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


@pytest.fixture(params=["sqlite", "postgresql"])
def database(request, tmp_path, isolated_logging):
    """Yield (config, engine) of an empty database; PostgreSQL gets its own schema."""
    if request.param == "sqlite":
        url = make_url(f"sqlite:///{tmp_path / 'reference.db'}")
        schema = None
    else:
        base_url = os.environ.get("TEST_DATABASE_URL", "")
        if not base_url.startswith("postgresql"):
            pytest.skip("TEST_DATABASE_URL not set to PostgreSQL")
        schema = "reference_recordings_" + uuid.uuid4().hex
        admin = create_engine(base_url)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = make_url(base_url).update_query_dict({"options": f"-csearch_path={schema}"})
    config = _alembic_config()
    config.set_main_option(
        "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    engine = create_engine(url)
    if request.param == "sqlite":
        # Alembic's engine does not enable foreign keys; this connection does, as init_test_db does.
        event.listen(
            engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
        )
    yield config, engine
    engine.dispose()
    if schema is not None:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def migration():
    return importlib.import_module(MIGRATION)


def _insert_user(connection, user_id="u1"):
    connection.execute(
        text(
            "INSERT INTO users (id, username, role, created_at, updated_at) "
            "VALUES (:id, :id, 'user', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"id": user_id},
    )


def _insert_recording(connection, user_id="u1", storage_path="u1/refs/a.wav"):
    connection.execute(
        text(
            "INSERT INTO reference_recordings "
            "(id, user_id, storage_path, original_filename, size_bytes, created_at) "
            "VALUES (:id, :user_id, :path, 'a.wav', 10, CURRENT_TIMESTAMP)"
        ),
        {"id": uuid.uuid4().hex, "user_id": user_id, "path": storage_path},
    )


def test_the_migration_follows_the_coherence_verdict_revision_on_the_single_chain(migration):
    assert migration.down_revision == PREVIOUS_REVISION
    assert is_on_the_single_chain(migration.revision)


def test_upgrade_creates_the_table_with_its_unique_and_foreign_key_constraints(
    database, migration,
):
    config, engine = database
    command.upgrade(config, migration.revision)
    inspector = inspect(engine)
    assert TABLE in inspector.get_table_names()
    columns = {column["name"]: column for column in inspector.get_columns(TABLE)}
    assert set(columns) == {
        "id", "user_id", "storage_path", "original_filename", "size_bytes",
        "duration_sec", "created_at",
    }
    assert columns["duration_sec"]["nullable"] is True
    assert not any(
        column["nullable"] for name, column in columns.items() if name != "duration_sec"
    )
    assert [c["column_names"] for c in inspector.get_unique_constraints(TABLE)] == [
        ["storage_path"]
    ]
    [foreign_key] = inspector.get_foreign_keys(TABLE)
    assert foreign_key["referred_table"] == "users"
    assert foreign_key["options"]["ondelete"].upper() == "RESTRICT"
    assert any(index["column_names"] == ["user_id"] for index in inspector.get_indexes(TABLE))


def test_the_constraints_are_enforced_by_the_database(database, migration):
    config, engine = database
    command.upgrade(config, migration.revision)
    with engine.begin() as connection:
        _insert_user(connection)
        _insert_recording(connection)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_recording(connection)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_recording(connection, user_id="missing", storage_path="missing/refs/a.wav")
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("DELETE FROM users WHERE id = 'u1'"))
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM users")).scalar() == 1
        if engine.dialect.name == "sqlite":
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
            [foreign_key] = connection.execute(text(f"PRAGMA foreign_key_list({TABLE})")).all()
            assert "RESTRICT" in tuple(foreign_key)


def test_downgrade_removes_the_table_and_the_previous_head_still_works(database, migration):
    config, engine = database
    command.upgrade(config, migration.revision)
    command.downgrade(config, PREVIOUS_REVISION)
    assert TABLE not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert connection.execute(text("SELECT count(*) FROM users")).scalar() == 0
    assert version == PREVIOUS_REVISION
    command.upgrade(config, migration.revision)
    assert TABLE in inspect(engine).get_table_names()

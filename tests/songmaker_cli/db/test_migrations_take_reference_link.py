"""The migration that links takes to their reference recording, on SQLite and PostgreSQL."""

from __future__ import annotations

import importlib
import json
import os
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from support.migration_chain import is_on_the_single_chain

MIGRATION = (
    "songmaker_cli.db.migrations.versions.c4d7e1a9b3f6_takes_link_their_reference_recording"
)
PREVIOUS_REVISION = "ea28bf0de7cc"
COLUMN = "reference_recording_id"
PATH = "u1/refs/a.wav"


def _alembic_config() -> Config:
    return Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))


def _config_for(url) -> Config:
    config = _alembic_config()
    config.set_main_option(
        "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    return config


@pytest.fixture
def sqlite_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'take-link.db'}")
    # Alembic's engine does not enable foreign keys; this connection does, as init_test_db does.
    event.listen(
        engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    yield _config_for(engine.url), engine
    engine.dispose()


@pytest.fixture
def postgresql_database():
    base_url = os.environ.get("TEST_DATABASE_URL", "")
    if not base_url.startswith("postgresql"):
        pytest.skip("TEST_DATABASE_URL not set to PostgreSQL")
    schema = "take_reference_link_" + uuid.uuid4().hex
    admin = create_engine(base_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(base_url).update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(url)
    yield _config_for(url), engine
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


@pytest.fixture(params=["sqlite_database", "postgresql_database"])
def database(request, isolated_logging):
    """Yield (config, engine) of an empty database."""
    return request.getfixturevalue(request.param)


@pytest.fixture
def migration():
    return importlib.import_module(MIGRATION)


def _execute_sql(engine, statement: str, **values) -> None:
    json_values = {key for key, value in values.items() if isinstance(value, dict)}
    prepared = text(statement).bindparams(
        *(sa.bindparam(key, type_=sa.JSON(none_as_null=True)) for key in json_values)
    )
    with engine.begin() as connection:
        connection.execute(prepared, values)


def _seed_users(engine) -> None:
    for user in ("u1", "u2"):
        _execute_sql(
            engine,
            "INSERT INTO users (id, username, role, created_at, updated_at) "
            "VALUES (:id, :id, 'user', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            id=user,
        )


def _insert_take(engine, take_id: str, params: dict | None, created_by: str | None) -> None:
    _execute_sql(
        engine,
        "INSERT INTO generations (id, song_id, version_id, generation_number, mp3_path, "
        "generation_params, status, is_archived, is_picked, is_kept, model_mode, created_by, "
        "created_at, is_shared) VALUES (:id, 'song', 'version', :number, :id, :params, "
        "'completed', :off, :off, :off, 'sft', :created_by, CURRENT_TIMESTAMP, :off)",
        id=take_id,
        number=int(take_id.removeprefix("take") or 0),
        params=params,
        off=False,
        created_by=created_by,
    )


def _seed_song_with_take(
    engine, take_params, *, take_owner="u1", recording_owner="u1", recording_path=PATH,
) -> None:
    """One song, one version, a take holding ``take_params`` and a recording, at the old head."""
    _seed_users(engine)
    _execute_sql(
        engine,
        "INSERT INTO albums (id, title, artist, subtitle, year, colors, created_at, created_by) "
        "VALUES ('album', 'A', 'B', '', 0, '{}', CURRENT_TIMESTAMP, 'u1')",
    )
    _execute_sql(
        engine,
        "INSERT INTO songs (id, title, album_id, vocal_language, track_number, created_at, "
        "updated_at, slug) VALUES ('song', 'S', 'album', '', 1, CURRENT_TIMESTAMP, "
        "CURRENT_TIMESTAMP, 's')",
    )
    _execute_sql(
        engine,
        "INSERT INTO versions (id, song_id, version_number, lyrics, prompt, bpm, audio_duration, "
        "key_scale, created_at) VALUES ('version', 'song', 1, '', '', 0, 0, '', CURRENT_TIMESTAMP)",
    )
    _execute_sql(
        engine,
        "INSERT INTO reference_recordings (id, user_id, storage_path, original_filename, "
        "size_bytes, created_at) VALUES ('recording', :owner, :path, 'a.wav', 10, "
        "CURRENT_TIMESTAMP)",
        owner=recording_owner,
        path=recording_path,
    )
    _insert_take(engine, "take1", take_params, take_owner)


def _decoded_json(value):
    return json.loads(value) if isinstance(value, str) else value


def _take(engine, take_id: str = "take1") -> tuple[str | None, dict | None]:
    with engine.connect() as connection:
        key, params = connection.execute(
            text(f"SELECT {COLUMN}, generation_params FROM generations WHERE id = :id"),
            {"id": take_id},
        ).one()
    return key, _decoded_json(params)


def _upgraded_with_seeded_take(database, migration, **seed):
    config, engine = database
    command.upgrade(config, PREVIOUS_REVISION)
    _seed_song_with_take(engine, **seed)
    command.upgrade(config, migration.revision)
    return engine


def test_the_migration_follows_the_version_link_revision_on_the_single_chain(migration):
    assert migration.down_revision == PREVIOUS_REVISION
    assert is_on_the_single_chain(migration.revision)


def test_upgrade_adds_an_indexed_nullable_key_that_the_database_restricts(database, migration):
    config, engine = database
    command.upgrade(config, migration.revision)
    inspector = inspect(engine)
    column = next(c for c in inspector.get_columns("generations") if c["name"] == COLUMN)
    assert column["nullable"] is True
    assert any(index["column_names"] == [COLUMN] for index in inspector.get_indexes("generations"))
    [foreign_key] = [
        fk
        for fk in inspector.get_foreign_keys("generations")
        if fk["constrained_columns"] == [COLUMN]
    ]
    assert foreign_key["referred_table"] == "reference_recordings"
    assert foreign_key["options"]["ondelete"].upper() == "RESTRICT"


def test_deleting_a_recording_an_archived_take_links_is_refused_by_the_database(
    database, migration,
):
    engine = _upgraded_with_seeded_take(database, migration, take_params=None)
    _execute_sql(engine, f"UPDATE generations SET {COLUMN} = 'recording', is_archived = :archived",
             archived=True)
    delete_recordings = text("DELETE FROM reference_recordings")
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(delete_recordings)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM reference_recordings")).scalar() == 1
        if engine.dialect.name == "sqlite":
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
            keys = connection.execute(text("PRAGMA foreign_key_list(generations)")).all()
            assert any("RESTRICT" in tuple(key) for key in keys)


def test_upgrade_links_a_mapped_path_and_strips_the_json_key(database, migration):
    engine = _upgraded_with_seeded_take(
        database, migration, take_params={"reference_audio_path": PATH, "shift": 3.0},
    )
    assert _take(engine) == ("recording", {"shift": 3.0})


@pytest.mark.parametrize(
    "params",
    [None, {}, {"shift": 3.0}, {"reference_audio_path": ""}, {"reference_audio_path": None}],
    ids=["no-params", "empty-object", "absent-key", "empty-string", "null"],
)
def test_upgrade_links_nothing_for_an_absent_null_or_empty_path(database, migration, params):
    engine = _upgraded_with_seeded_take(database, migration, take_params=params)
    key, stored = _take(engine)
    assert key is None
    assert "reference_audio_path" not in (stored or {})


FAILING_WORLDS = {
    "unmapped path": {
        "take_params": {"reference_audio_path": "u1/refs/missing.wav"},
    },
    "owner mismatch": {
        "take_params": {"reference_audio_path": "u2/refs/a.wav"},
        "recording_owner": "u2",
        "recording_path": "u2/refs/a.wav",
    },
    "NULL owner": {
        "take_params": {"reference_audio_path": PATH},
        "take_owner": None,
    },
}


@pytest.mark.parametrize("failure", FAILING_WORLDS)
def test_upgrade_fails_loud_with_counts_and_ids_and_changes_nothing(database, migration, failure):
    config, engine = database
    command.upgrade(config, PREVIOUS_REVISION)
    _seed_song_with_take(engine, **FAILING_WORLDS[failure])

    with pytest.raises(RuntimeError) as refusal:
        command.upgrade(config, migration.revision)

    assert f"{failure}: 1 (ids take1)" in str(refusal.value)
    assert "nothing was changed" in str(refusal.value)
    assert "refs/" not in str(refusal.value)
    assert COLUMN not in {c["name"] for c in inspect(engine).get_columns("generations")}


def test_downgrade_writes_the_path_back_to_linked_takes_and_drops_the_column(
    database, migration,
):
    config, _ = database
    engine = _upgraded_with_seeded_take(
        database, migration, take_params={"reference_audio_path": PATH, "shift": 3.0},
    )
    _insert_take(engine, "take2", None, "u1")
    command.downgrade(config, PREVIOUS_REVISION)
    with engine.connect() as connection:
        rows = dict(connection.execute(text("SELECT id, generation_params FROM generations")).all())
    assert COLUMN not in {c["name"] for c in inspect(engine).get_columns("generations")}
    assert _decoded_json(rows["take1"]) == {"reference_audio_path": PATH, "shift": 3.0}
    assert _decoded_json(rows["take2"]) is None
    command.upgrade(config, migration.revision)
    assert _take(engine) == ("recording", {"shift": 3.0})

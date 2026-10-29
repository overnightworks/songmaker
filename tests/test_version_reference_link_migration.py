"""The migration that links versions to their reference recording, on SQLite and PostgreSQL."""

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
    "songmaker_cli.db.migrations.versions.ea28bf0de7cc_versions_link_their_reference_recording"
)
PREVIOUS_REVISION = "5b2e9d4a7c31"
COLUMN = "reference_recording_id"
PATH = "u1/refs/a.wav"


def _alembic_config() -> Config:
    return Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


@pytest.fixture(params=["sqlite", "postgresql"])
def database(request, tmp_path, isolated_logging):
    """Yield (config, engine) of an empty database; PostgreSQL gets its own schema."""
    if request.param == "sqlite":
        url = make_url(f"sqlite:///{tmp_path / 'version-link.db'}")
        schema = None
    else:
        base_url = os.environ.get("TEST_DATABASE_URL", "")
        if not base_url.startswith("postgresql"):
            pytest.skip("TEST_DATABASE_URL not set to PostgreSQL")
        schema = "version_reference_link_" + uuid.uuid4().hex
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


def _execute(engine, statement: str, **values) -> None:
    json_values = {key for key, value in values.items() if isinstance(value, dict)}
    prepared = text(statement).bindparams(
        *(sa.bindparam(key, type_=sa.JSON(none_as_null=True)) for key in json_values)
    )
    with engine.begin() as connection:
        connection.execute(prepared, values)


def _seed_users(engine) -> None:
    for user in ("u1", "u2"):
        _execute(
            engine,
            "INSERT INTO users (id, username, role, created_at, updated_at) "
            "VALUES (:id, :id, 'user', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            id=user,
        )


def _seed_world(
    engine, version_params, *, album_owner="u1", recording_owner="u1", recording_path=PATH,
) -> None:
    """One album with one song and a version holding ``version_params``, at the old revision."""
    _seed_users(engine)
    _execute(
        engine,
        "INSERT INTO albums (id, title, artist, subtitle, year, colors, created_at, created_by) "
        "VALUES ('album', 'A', 'B', '', 0, '', CURRENT_TIMESTAMP, :owner)",
        owner=album_owner,
    )
    _execute(
        engine,
        "INSERT INTO songs (id, title, album_id, vocal_language, track_number, created_at, "
        "updated_at, slug) VALUES ('song', 'S', 'album', '', 1, CURRENT_TIMESTAMP, "
        "CURRENT_TIMESTAMP, 's')",
    )
    _execute(
        engine,
        "INSERT INTO versions (id, song_id, version_number, lyrics, prompt, bpm, audio_duration, "
        "key_scale, generation_params, created_at) VALUES ('version', 'song', 1, '', '', 0, 0, "
        "'', :params, CURRENT_TIMESTAMP)",
        params=version_params,
    )
    _execute(
        engine,
        "INSERT INTO reference_recordings (id, user_id, storage_path, original_filename, "
        "size_bytes, created_at) VALUES ('recording', :owner, :path, 'a.wav', 10, "
        "CURRENT_TIMESTAMP)",
        owner=recording_owner,
        path=recording_path,
    )


def _insert_preset(engine, preset_id: str, params: dict, created_by: str | None) -> None:
    _execute(
        engine,
        "INSERT INTO generation_presets (id, name, model_mode, params, is_default, created_at, "
        "updated_at, created_by) VALUES (:id, :id, 'sft', :params, :flag, CURRENT_TIMESTAMP, "
        "CURRENT_TIMESTAMP, :created_by)",
        id=preset_id,
        params=params,
        flag=False,
        created_by=created_by,
    )


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _version(engine) -> tuple[str | None, dict | None]:
    with engine.connect() as connection:
        key, params = connection.execute(
            text(f"SELECT {COLUMN}, generation_params FROM versions")
        ).one()
    return key, _json(params)


def _upgraded_after_seeding(database, migration, **seed):
    config, engine = database
    command.upgrade(config, PREVIOUS_REVISION)
    _seed_world(engine, **seed)
    command.upgrade(config, migration.revision)
    return engine


def test_the_migration_follows_the_reference_recordings_revision_on_the_single_chain(migration):
    assert migration.down_revision == PREVIOUS_REVISION
    assert is_on_the_single_chain(migration.revision)


def test_upgrade_adds_an_indexed_nullable_key_that_the_database_restricts(database, migration):
    config, engine = database
    command.upgrade(config, migration.revision)
    inspector = inspect(engine)
    column = next(c for c in inspector.get_columns("versions") if c["name"] == COLUMN)
    assert column["nullable"] is True
    assert any(index["column_names"] == [COLUMN] for index in inspector.get_indexes("versions"))
    [foreign_key] = [
        fk for fk in inspector.get_foreign_keys("versions") if fk["constrained_columns"] == [COLUMN]
    ]
    assert foreign_key["referred_table"] == "reference_recordings"
    assert foreign_key["options"]["ondelete"].upper() == "RESTRICT"


def test_deleting_a_linked_recording_is_refused_by_the_database(database, migration):
    engine = _upgraded_after_seeding(database, migration, version_params=None)
    _execute(engine, f"UPDATE versions SET {COLUMN} = 'recording'")
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("DELETE FROM reference_recordings"))
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM reference_recordings")).scalar() == 1
        if engine.dialect.name == "sqlite":
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
            keys = connection.execute(text("PRAGMA foreign_key_list(versions)")).all()
            assert any("RESTRICT" in tuple(key) for key in keys)


def test_upgrade_links_a_mapped_path_and_strips_the_json_key(database, migration):
    engine = _upgraded_after_seeding(
        database, migration, version_params={"reference_audio_path": PATH, "shift": 3.0},
    )
    assert _version(engine) == ("recording", {"shift": 3.0})


@pytest.mark.parametrize(
    "params",
    [None, {}, {"shift": 3.0}, {"reference_audio_path": ""}, {"reference_audio_path": None}],
    ids=["no-params", "empty-object", "absent-key", "empty-string", "null"],
)
def test_upgrade_links_nothing_for_an_absent_null_or_empty_path(database, migration, params):
    engine = _upgraded_after_seeding(database, migration, version_params=params)
    key, stored = _version(engine)
    assert key is None
    assert "reference_audio_path" not in (stored or {})


FAILING_WORLDS = {
    "unmapped path": {
        "version_params": {"reference_audio_path": "u1/refs/missing.wav"},
    },
    "owner mismatch": {
        "version_params": {"reference_audio_path": "u2/refs/a.wav"},
        "recording_owner": "u2",
        "recording_path": "u2/refs/a.wav",
    },
    "NULL owner": {
        "version_params": {"reference_audio_path": PATH},
        "album_owner": None,
    },
}


@pytest.mark.parametrize("failure", FAILING_WORLDS)
def test_upgrade_fails_loud_with_counts_and_ids_and_changes_nothing(database, migration, failure):
    config, engine = database
    command.upgrade(config, PREVIOUS_REVISION)
    _seed_world(engine, **FAILING_WORLDS[failure])

    with pytest.raises(RuntimeError) as refusal:
        command.upgrade(config, migration.revision)

    assert f"{failure}: 1 (ids version)" in str(refusal.value)
    assert "nothing was changed" in str(refusal.value)
    assert "refs/" not in str(refusal.value)
    assert COLUMN not in {c["name"] for c in inspect(engine).get_columns("versions")}


def test_upgrade_fails_loud_for_a_path_on_a_preset_or_a_global_default(database, migration):
    config, engine = database
    command.upgrade(config, PREVIOUS_REVISION)
    _seed_users(engine)
    _insert_preset(engine, "preset", {"reference_audio_path": PATH}, "u1")
    _insert_preset(engine, "default", {"reference_audio_path": PATH}, None)

    with pytest.raises(RuntimeError) as refusal:
        command.upgrade(config, migration.revision)

    assert "preset or default: 2 (ids " in str(refusal.value)
    assert PATH not in str(refusal.value)


def test_upgrade_strips_an_empty_path_from_a_preset(database, migration):
    config, engine = database
    command.upgrade(config, PREVIOUS_REVISION)
    _insert_preset(engine, "preset", {"reference_audio_path": "", "shift": 3.0}, None)
    command.upgrade(config, migration.revision)
    with engine.connect() as connection:
        stored = connection.execute(text("SELECT params FROM generation_presets")).scalar()
    assert _json(stored) == {"shift": 3.0}


def test_downgrade_writes_the_path_back_and_drops_the_column(database, migration):
    config, _ = database
    engine = _upgraded_after_seeding(
        database, migration, version_params={"reference_audio_path": PATH, "shift": 3.0},
    )
    command.downgrade(config, PREVIOUS_REVISION)
    with engine.connect() as connection:
        params = connection.execute(text("SELECT generation_params FROM versions")).scalar()
    assert COLUMN not in {c["name"] for c in inspect(engine).get_columns("versions")}
    assert _json(params) == {"reference_audio_path": PATH, "shift": 3.0}
    command.upgrade(config, migration.revision)
    assert _version(engine) == ("recording", {"shift": 3.0})

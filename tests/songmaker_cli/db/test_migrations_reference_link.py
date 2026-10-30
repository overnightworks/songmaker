"""The migrations that link versions and takes to their reference recording."""

from __future__ import annotations

import json

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from support.migration_chain import is_on_the_single_chain
from support.reference_link_migration import (
    RECORDING_COLUMN,
    RECORDING_PATH,
    LinkCase,
    execute,
    seed_users,
    upgraded_after_seeding,
)


def _seed_recording(engine, *, recording_owner="u1", recording_path=RECORDING_PATH) -> None:
    execute(
        engine,
        "INSERT INTO reference_recordings (id, user_id, storage_path, original_filename, "
        "size_bytes, created_at) VALUES ('recording', :owner, :path, 'a.wav', 10, "
        "CURRENT_TIMESTAMP)",
        owner=recording_owner,
        path=recording_path,
    )


def _seed_song(engine, *, album_owner="u1") -> None:
    seed_users(engine)
    execute(
        engine,
        "INSERT INTO albums (id, title, artist, subtitle, year, colors, created_at, created_by) "
        "VALUES ('album', 'A', 'B', '', 0, '{}', CURRENT_TIMESTAMP, :owner)",
        owner=album_owner,
    )
    execute(
        engine,
        "INSERT INTO songs (id, title, album_id, vocal_language, track_number, created_at, "
        "updated_at, slug) VALUES ('song', 'S', 'album', '', 1, CURRENT_TIMESTAMP, "
        "CURRENT_TIMESTAMP, 's')",
    )


def _seed_version_with_params(engine, params, *, owner="u1", **recording) -> None:
    """One album owned by ``owner`` with a version holding ``params``, at the old revision."""
    _seed_song(engine, album_owner=owner)
    execute(
        engine,
        "INSERT INTO versions (id, song_id, version_number, lyrics, prompt, bpm, audio_duration, "
        "key_scale, generation_params, created_at) VALUES ('version', 'song', 1, '', '', 0, 0, "
        "'', :params, CURRENT_TIMESTAMP)",
        params=params,
    )
    _seed_recording(engine, **recording)


def _insert_take(engine, take_id: str, params: dict | None, created_by: str | None) -> None:
    execute(
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


def _seed_take_with_params(engine, params, *, owner="u1", **recording) -> None:
    """One song, one version, a take created by ``owner`` holding ``params``, at the old head."""
    _seed_song(engine)
    execute(
        engine,
        "INSERT INTO versions (id, song_id, version_number, lyrics, prompt, bpm, audio_duration, "
        "key_scale, created_at) VALUES ('version', 'song', 1, '', '', 0, 0, '', CURRENT_TIMESTAMP)",
    )
    _seed_recording(engine, **recording)
    _insert_take(engine, "take1", params, owner)


VERSIONS = LinkCase(
    table="versions",
    migration_module=(
        "songmaker_cli.db.migrations.versions.ea28bf0de7cc_versions_link_their_reference_recording"
    ),
    previous_revision="5b2e9d4a7c31",
    failing_id="version",
    seed=_seed_version_with_params,
    link_statement=f"UPDATE versions SET {RECORDING_COLUMN} = 'recording'",
    link_values={},
)
TAKES = LinkCase(
    table="generations",
    migration_module=(
        "songmaker_cli.db.migrations.versions.c4d7e1a9b3f6_takes_link_their_reference_recording"
    ),
    previous_revision="ea28bf0de7cc",
    failing_id="take1",
    seed=_seed_take_with_params,
    link_statement=(
        f"UPDATE generations SET {RECORDING_COLUMN} = 'recording', is_archived = :archived"
    ),
    link_values={"archived": True},
)
link_cases = pytest.mark.parametrize("case", [VERSIONS, TAKES], ids=lambda case: case.table)


def _decoded_json(value):
    return json.loads(value) if isinstance(value, str) else value


def _linked_row(engine, case: LinkCase) -> tuple[str | None, dict | None]:
    with engine.connect() as connection:
        key, params = connection.execute(
            text(f"SELECT {RECORDING_COLUMN}, generation_params FROM {case.table} LIMIT 1")
        ).one()
    return key, _decoded_json(params)


def _column_names(engine, case: LinkCase) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(case.table)}


@link_cases
def test_the_migration_follows_the_previous_link_revision_on_the_single_chain(case):
    assert case.migration.down_revision == case.previous_revision
    assert is_on_the_single_chain(case.migration.revision)


@link_cases
def test_upgrade_adds_an_indexed_nullable_key_that_the_database_restricts(
    reference_link_database,
    case,
):
    config, engine = reference_link_database
    command.upgrade(config, case.migration.revision)
    inspector = inspect(engine)
    column = next(c for c in inspector.get_columns(case.table) if c["name"] == RECORDING_COLUMN)
    assert column["nullable"] is True
    assert any(
        index["column_names"] == [RECORDING_COLUMN] for index in inspector.get_indexes(case.table)
    )
    [foreign_key] = [
        fk
        for fk in inspector.get_foreign_keys(case.table)
        if fk["constrained_columns"] == [RECORDING_COLUMN]
    ]
    assert foreign_key["referred_table"] == "reference_recordings"
    assert foreign_key["options"]["ondelete"].upper() == "RESTRICT"


@link_cases
def test_deleting_a_linked_recording_is_refused_by_the_database(reference_link_database, case):
    engine = upgraded_after_seeding(reference_link_database, case, params=None)
    execute(engine, case.link_statement, **case.link_values)
    delete_recordings = text("DELETE FROM reference_recordings")
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(delete_recordings)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM reference_recordings")).scalar() == 1
        if engine.dialect.name == "sqlite":
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
            keys = connection.execute(text(f"PRAGMA foreign_key_list({case.table})")).all()
            assert any("RESTRICT" in tuple(key) for key in keys)


@link_cases
def test_upgrade_links_a_mapped_path_and_strips_the_json_key(reference_link_database, case):
    engine = upgraded_after_seeding(
        reference_link_database,
        case,
        params={"reference_audio_path": RECORDING_PATH, "shift": 3.0},
    )
    assert _linked_row(engine, case) == ("recording", {"shift": 3.0})


@link_cases
@pytest.mark.parametrize(
    "params",
    [None, {}, {"shift": 3.0}, {"reference_audio_path": ""}, {"reference_audio_path": None}],
    ids=["no-params", "empty-object", "absent-key", "empty-string", "null"],
)
def test_upgrade_links_nothing_for_an_absent_null_or_empty_path(
    reference_link_database,
    case,
    params,
):
    engine = upgraded_after_seeding(reference_link_database, case, params=params)
    key, stored = _linked_row(engine, case)
    assert key is None
    assert "reference_audio_path" not in (stored or {})


FAILING_WORLDS = {
    "unmapped path": {"params": {"reference_audio_path": "u1/refs/missing.wav"}},
    "owner mismatch": {
        "params": {"reference_audio_path": "u2/refs/a.wav"},
        "recording_owner": "u2",
        "recording_path": "u2/refs/a.wav",
    },
    "NULL owner": {"params": {"reference_audio_path": RECORDING_PATH}, "owner": None},
}


@link_cases
@pytest.mark.parametrize("failure", FAILING_WORLDS)
def test_upgrade_fails_loud_with_counts_and_ids_and_changes_nothing(
    reference_link_database,
    case,
    failure,
):
    config, engine = reference_link_database
    command.upgrade(config, case.previous_revision)
    case.seed(engine, **FAILING_WORLDS[failure])

    with pytest.raises(RuntimeError) as refusal:
        command.upgrade(config, case.migration.revision)

    assert f"{failure}: 1 (ids {case.failing_id})" in str(refusal.value)
    assert "nothing was changed" in str(refusal.value)
    assert "refs/" not in str(refusal.value)
    assert RECORDING_COLUMN not in _column_names(engine, case)


@link_cases
def test_downgrade_writes_the_path_back_and_drops_the_column(reference_link_database, case):
    config, _ = reference_link_database
    engine = upgraded_after_seeding(
        reference_link_database,
        case,
        params={"reference_audio_path": RECORDING_PATH, "shift": 3.0},
    )
    command.downgrade(config, case.previous_revision)
    with engine.connect() as connection:
        params = connection.execute(text(f"SELECT generation_params FROM {case.table}")).scalar()
    assert RECORDING_COLUMN not in _column_names(engine, case)
    assert _decoded_json(params) == {"reference_audio_path": RECORDING_PATH, "shift": 3.0}
    command.upgrade(config, case.migration.revision)
    assert _linked_row(engine, case) == ("recording", {"shift": 3.0})


def test_downgrade_leaves_a_take_without_parameters_without_a_path(reference_link_database):
    config, _ = reference_link_database
    engine = upgraded_after_seeding(
        reference_link_database,
        TAKES,
        params={"reference_audio_path": RECORDING_PATH},
    )
    _insert_take(engine, "take2", None, "u1")
    command.downgrade(config, TAKES.previous_revision)
    with engine.connect() as connection:
        rows = dict(connection.execute(text("SELECT id, generation_params FROM generations")).all())
    assert _decoded_json(rows["take2"]) is None


def test_upgrade_fails_loud_for_a_path_on_a_preset_or_a_global_default(reference_link_database):
    config, engine = reference_link_database
    command.upgrade(config, VERSIONS.previous_revision)
    seed_users(engine)
    _insert_preset(engine, "preset", {"reference_audio_path": RECORDING_PATH}, "u1")
    _insert_preset(engine, "default", {"reference_audio_path": RECORDING_PATH}, None)

    with pytest.raises(RuntimeError) as refusal:
        command.upgrade(config, VERSIONS.migration.revision)

    assert "preset or default: 2 (ids " in str(refusal.value)
    assert RECORDING_PATH not in str(refusal.value)


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"reference_audio_path": "", "shift": 3.0}, {"shift": 3.0}),
        ({"reference_audio_path": ""}, {}),
        ({"reference_audio_path": None}, {}),
    ],
)
def test_upgrade_strips_an_empty_path_from_a_preset(reference_link_database, params, expected):
    config, engine = reference_link_database
    command.upgrade(config, VERSIONS.previous_revision)
    _insert_preset(engine, "preset", params, None)
    command.upgrade(config, VERSIONS.migration.revision)
    with engine.connect() as connection:
        stored = connection.execute(text("SELECT params FROM generation_presets")).scalar()
    assert _decoded_json(stored) == expected


def _insert_preset(engine, preset_id: str, params: dict, created_by: str | None) -> None:
    execute(
        engine,
        "INSERT INTO generation_presets (id, name, model_mode, params, is_default, created_at, "
        "updated_at, created_by) VALUES (:id, :id, 'sft', :params, :flag, CURRENT_TIMESTAMP, "
        "CURRENT_TIMESTAMP, :created_by)",
        id=preset_id,
        params=params,
        flag=False,
        created_by=created_by,
    )

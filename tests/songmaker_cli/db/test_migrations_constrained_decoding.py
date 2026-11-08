"""The data migration that deletes the stored `constrained_decoding` key from takes."""

from __future__ import annotations

import importlib
import json
import logging
from datetime import UTC, datetime

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from support.migration_chain import is_on_the_single_chain, seeded_then_upgraded
from support.reference_link_migration import seed_users

from songmaker_cli.db.models import Album, Generation, Song, Version

MIGRATION = (
    "songmaker_cli.db.migrations.versions.b7d2f95a1c38_stored_constrained_decoding_is_deleted"
)
PREVIOUS_REVISION = "a4c7e19b3d52"
UNRELATED = {"guidance_scale": 7.0, "bpm": 96}


@pytest.fixture
def migration():
    return importlib.import_module(MIGRATION)


def _seed_params_of_takes(engine, values: dict[str, dict | list | None]) -> None:
    seed_users(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(Album(id="a1", title="Album", artist="Band", created_by="u1"))
        session.add(Song(id="s1", title="Song", album_id="a1", track_number=1))
        session.flush()
        session.execute(Version.__table__.insert().values(
            id="v1", song_id="s1", version_number=1, lyrics="x", prompt="y", bpm=120,
            audio_duration=0, key_scale="", created_at=datetime.now(UTC),
        ))
        for number, (name, params) in enumerate(values.items(), start=1):
            session.execute(Generation.__table__.insert().values(
                id=name, song_id="s1", version_id="v1", generation_number=number,
                mp3_path=f"{name}.mp3", seed=number, status="completed", is_archived=False,
                is_picked=False, is_kept=False, model_mode="sft", is_shared=False,
                created_at=datetime.now(UTC), generation_params=params,
            ))
        session.commit()


def _migration_log(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name.startswith("alembic")]


def _stored_params(engine) -> dict[str, str | None]:
    query = text("SELECT id, CAST(generation_params AS TEXT) FROM generations")
    with engine.connect() as connection:
        return dict(connection.execute(query).tuples().all())


def _stored_documents(engine) -> dict:
    return {
        name: (None if raw is None else json.loads(raw))
        for name, raw in _stored_params(engine).items()
    }


def _upgraded_with_params(database, migration, values):
    engine = database[1]
    versions = []

    def seed(engine_at_previous):
        _seed_params_of_takes(engine_at_previous, values)
        versions.append(_stored_params(engine_at_previous))

    seeded_then_upgraded(database, migration.down_revision, migration.revision, seed)
    return versions[0], _stored_params(engine)


def test_the_migration_follows_the_accounts_kind_revision_on_the_single_chain(migration):
    assert migration.down_revision == PREVIOUS_REVISION
    assert is_on_the_single_chain(migration.revision)


def test_upgrade_deletes_the_key_and_keeps_every_other_key(reference_link_database, migration):
    _upgraded_with_params(reference_link_database, migration, {
        "beside": {"constrained_decoding": True, **UNRELATED},
        "alone": {"constrained_decoding": True},
        "switched_off": {"constrained_decoding": False, **UNRELATED},
    })
    stored = _stored_documents(reference_link_database[1])
    assert stored["beside"] == UNRELATED
    assert stored["alone"] == {}
    assert stored["switched_off"] == UNRELATED


def test_rows_without_the_key_stay_byte_equal(reference_link_database, migration):
    before, after = _upgraded_with_params(reference_link_database, migration, {
        "plain": dict(UNRELATED), "empty": {}, "json_null": None,
        "listed": ["constrained_decoding"],
    })
    assert after == before


def test_upgrade_logs_how_many_rows_it_changed(
    reference_link_database, migration, caplog,
):
    with caplog.at_level(logging.INFO, logger="alembic"):
        _upgraded_with_params(reference_link_database, migration, {
            "one": {"constrained_decoding": True, **UNRELATED},
            "two": {"constrained_decoding": True},
            "three": dict(UNRELATED), "four": {}, "five": None,
        })
    assert any("changed 2 generations rows" in message for message in _migration_log(caplog))


def test_a_second_upgrade_changes_nothing_and_logs_zero(
    reference_link_database, migration, caplog,
):
    config, engine = reference_link_database
    _, once = _upgraded_with_params(reference_link_database, migration, {
        "one": {"constrained_decoding": True, **UNRELATED}, "plain": dict(UNRELATED),
    })
    command.stamp(config, migration.down_revision)
    with caplog.at_level(logging.INFO, logger="alembic"):
        command.upgrade(config, migration.revision)
    assert _stored_params(engine) == once
    assert any("changed 0 generations rows" in message for message in _migration_log(caplog))


def test_downgrade_raises_and_leaves_database_and_rows_as_upgraded(
    reference_link_database, migration,
):
    config, engine = reference_link_database
    _, once = _upgraded_with_params(reference_link_database, migration, {
        "one": {"constrained_decoding": True, **UNRELATED}, "plain": dict(UNRELATED),
    })
    with pytest.raises(RuntimeError, match="irreversible"):
        command.downgrade(config, migration.down_revision)
    assert _stored_params(engine) == once
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == migration.revision


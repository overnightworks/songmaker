"""The data migration that deletes the old judge's stored coherence verdicts."""

from __future__ import annotations

import importlib
import json
import logging
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from support.migration_chain import is_on_the_single_chain

from songmaker_cli.db.models import Album, Generation, Score, Song, User, Version

MIGRATION = (
    "songmaker_cli.db.migrations.versions.c4e8a1f72d95_stored_coherence_verdicts_are_deleted"
)
PREVIOUS_REVISION = "a1d7c5e93b60"
KEYS = {"lyrical_coherence": 8, "lyrical_summary": "a summary"}
UNRELATED = {"bpm_detected": 96.0, "silence_ratio": 0.0}


def _alembic_config() -> Config:
    return Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


@pytest.fixture(params=["sqlite", "postgresql"])
def database(request, tmp_path, isolated_logging):
    """Yield (config, engine) of an empty database; PostgreSQL gets its own schema."""
    if request.param == "sqlite":
        url = make_url(f"sqlite:///{tmp_path / 'coherence.db'}")
        schema = None
    else:
        base_url = os.environ.get("TEST_DATABASE_URL", "")
        if not base_url.startswith("postgresql"):
            pytest.skip("TEST_DATABASE_URL not set to PostgreSQL")
        schema = "coherence_verdicts_" + uuid.uuid4().hex
        admin = create_engine(base_url)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = make_url(base_url).update_query_dict({"options": f"-csearch_path={schema}"})
    config = _alembic_config()
    rendered_url = url.render_as_string(hide_password=False).replace("%", "%%")
    config.set_main_option("sqlalchemy.url", rendered_url)
    engine = create_engine(url)
    yield config, engine
    engine.dispose()
    if schema is not None:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def migration():
    return importlib.import_module(MIGRATION)


def _seed(
    engine, values: dict[str, dict | list | None], scorers: dict[str, str] | None = None,
) -> None:
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(User(id="u1", username="u1"))
        session.flush()
        session.add(Album(id="a1", title="Album", artist="Band", created_by="u1"))
        session.add(Song(id="s1", title="Song", album_id="a1", track_number=1))
        session.add(Version(
            id="v1", song_id="s1", version_number=1, lyrics="x", prompt="y", bpm=120,
        ))
        session.add(Generation(
            id="g1", song_id="s1", version_id="v1", generation_number=1, mp3_path="g1.mp3", seed=1,
        ))
        session.flush()
        for name, value in values.items():
            session.add(Score(
                id=name, generation_id="g1", scorer=(scorers or {}).get(name, "batch"), value=value,
            ))
        session.commit()


def _alembic_messages(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name.startswith("alembic")]


def _stored_text(engine) -> dict[str, str]:
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, CAST(value AS TEXT) FROM scores")).all()
    return {row[0]: row[1] for row in rows}


def _stored_json(engine) -> dict:
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, value FROM scores")).all()
    return {row[0]: (json.loads(row[1]) if isinstance(row[1], str) else row[1]) for row in rows}


def _upgrade_with(database, migration, values, scorers=None):
    config, engine = database
    command.upgrade(config, migration.down_revision)
    _seed(engine, values, scorers)
    before = _stored_text(engine)
    command.upgrade(config, migration.revision)
    return before, _stored_text(engine)


def test_the_migration_follows_the_session_token_revision_on_the_single_chain(migration):
    assert migration.down_revision == PREVIOUS_REVISION
    assert is_on_the_single_chain(migration.revision)


def test_upgrade_deletes_both_keys_and_keeps_every_other_key(database, migration):
    _upgrade_with(database, migration, {
        "both": {**KEYS, "bpm_detected": 96.0},
        "coherence_only": {"lyrical_coherence": 0, **UNRELATED},
        "summary_only": {"lyrical_summary": "x", **UNRELATED},
        "others_beside": {**KEYS, **UNRELATED},
    })
    stored = _stored_json(database[1])
    assert stored["both"] == {"bpm_detected": 96.0}
    assert stored["coherence_only"] == UNRELATED
    assert stored["summary_only"] == UNRELATED
    assert stored["others_beside"] == UNRELATED


def test_rows_without_a_verdict_key_stay_byte_equal(database, migration):
    before, after = _upgrade_with(database, migration, {
        "plain": {"bpm_detected": 96.0}, "empty": {}, "json_null": None,
        "listed": ["lyrical_coherence"],
    })
    assert after == before


def test_a_row_of_any_scorer_name_loses_the_pair(database, migration):
    _upgrade_with(database, migration, {"other": dict(KEYS)}, scorers={"other": "other"})
    assert _stored_json(database[1])["other"] == {}


def test_upgrade_logs_how_many_rows_it_changed(database, migration, caplog):
    with caplog.at_level(logging.INFO, logger="alembic"):
        _upgrade_with(database, migration, {
            "one": dict(KEYS), "two": {"lyrical_coherence": 3}, "three": {"lyrical_summary": "s"},
            "four": dict(UNRELATED), "five": {}, "six": None, "seven": [],
        })
    messages = _alembic_messages(caplog)
    assert any("changed 3 scores rows" in message for message in messages)


def test_a_second_upgrade_changes_nothing_and_logs_zero(database, migration, caplog):
    config, engine = database
    _, once = _upgrade_with(database, migration, {"one": dict(KEYS), "plain": dict(UNRELATED)})
    command.stamp(config, migration.down_revision)
    with caplog.at_level(logging.INFO, logger="alembic"):
        command.upgrade(config, migration.revision)
    assert _stored_text(engine) == once
    assert any("changed 0 scores rows" in message for message in _alembic_messages(caplog))


def test_downgrade_raises_and_leaves_database_and_rows_as_upgraded(database, migration):
    config, engine = database
    _, once = _upgrade_with(database, migration, {"one": dict(KEYS), "plain": dict(UNRELATED)})
    with pytest.raises(RuntimeError, match="irreversible"):
        command.downgrade(config, migration.down_revision)
    assert _stored_text(engine) == once
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == migration.revision


def test_upgrade_changes_no_table_and_no_column(database, migration):
    config, engine = database
    command.upgrade(config, migration.down_revision)

    def shape():
        inspector = inspect(engine)
        return {
            table: [
                (c["name"], str(c["type"]), c["nullable"]) for c in inspector.get_columns(table)
            ]
            for table in inspector.get_table_names()
        }

    before = shape()
    command.upgrade(config, migration.revision)
    assert shape() == before

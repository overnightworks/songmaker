"""The migration that stores a job's queue wait as a message token, not an English sentence."""

from __future__ import annotations

import importlib
import json
import logging

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import IntegrityError
from support.migration_chain import (
    column_names,
    frozen_table,
    is_on_the_single_chain,
    seeded_then_upgraded,
    stored_values,
)
from support.repository_root import REPOSITORY_ROOT

from songmaker_cli.words import SOURCE_LANGUAGE, text

MIGRATION = importlib.import_module(
    "songmaker_cli.db.migrations.versions.a9d3f1b7c5e2_a_queue_wait_is_stored_as_a_message"
)
PREVIOUS_REVISION = "d2f6b8a4c7e1"
OLD_COLUMN = "queue_reason"
NEW_COLUMN = "queue_reason_message"
STORED_KEYS_FILE = REPOSITORY_ROOT / "scripts" / "stored_message_keys.txt"
UNKNOWN_SENTENCE = "Waiting for the next GPU slot."
SENTENCES = list(MIGRATION.STORED_MESSAGE_KEYS)
JOB_COLUMNS = ("id", "type", "status", "progress", "heartbeat_at", "started_at")


def _insert_job(engine, job_id: str, column: str, value: object) -> None:
    stored = value if column == OLD_COLUMN else sa.cast(json.dumps(value), sa.JSON)
    jobs = frozen_table("jobs", JOB_COLUMNS, column)
    with engine.begin() as connection:
        connection.execute(sa.insert(jobs).values(
            id=job_id, type="generate", status="queued", progress=0.0,
            heartbeat_at=sa.func.current_timestamp(), started_at=sa.func.current_timestamp(),
            **{column: stored},
        ))


def _seed_waits(engine) -> None:
    for number, sentence in enumerate(SENTENCES):
        _insert_job(engine, f"known-{number}", OLD_COLUMN, sentence)
    _insert_job(engine, "unknown", OLD_COLUMN, UNKNOWN_SENTENCE)
    _insert_job(engine, "none", OLD_COLUMN, None)


@pytest.fixture
def upgraded(reference_link_database, caplog):
    caplog.set_level(logging.INFO, logger="alembic.runtime.migration")
    engine = seeded_then_upgraded(
        reference_link_database, PREVIOUS_REVISION, MIGRATION.revision, _seed_waits,
    )
    return reference_link_database[0], engine


def test_the_migration_follows_the_previous_revision_on_the_single_chain():
    assert MIGRATION.down_revision == PREVIOUS_REVISION
    assert is_on_the_single_chain(MIGRATION.revision)


def test_every_known_sentence_becomes_the_token_that_words_it_again(upgraded):
    _, engine = upgraded
    stored = stored_values(engine, "jobs", NEW_COLUMN)
    for number, sentence in enumerate(SENTENCES):
        token = stored[f"known-{number}"]
        assert token == {"key": MIGRATION.STORED_MESSAGE_KEYS[sentence], "values": {}}
        assert text(SOURCE_LANGUAGE, token["key"]) == sentence


def test_an_unknown_sentence_becomes_sql_null_and_its_count_is_logged(upgraded, caplog):
    _, engine = upgraded
    jobs = frozen_table("jobs", JOB_COLUMNS, NEW_COLUMN)
    with engine.connect() as connection:
        null_ids = set(connection.execute(
            sa.select(jobs.c.id).where(jobs.c[NEW_COLUMN].is_(None))
        ).scalars())
    assert null_ids == {"unknown", "none"}
    logged = [r.getMessage() for r in caplog.get_records("setup") if r.name.startswith("alembic")]
    assert any("1 unrecognized" in line for line in logged)


def test_upgrade_replaces_the_sentence_column_by_the_token_column(upgraded):
    _, engine = upgraded
    names = column_names(engine, "jobs")
    assert NEW_COLUMN in names
    assert OLD_COLUMN not in names


@pytest.mark.parametrize(
    "token",
    [
        pytest.param({"key": 7, "values": {}}, id="key-not-a-string"),
        pytest.param({"values": {}}, id="key-missing"),
        pytest.param({"key": "jobWait.voiceTraining", "values": []}, id="values-not-an-object"),
        pytest.param({"key": "jobWait.voiceTraining"}, id="values-missing"),
    ],
)
def test_the_database_refuses_a_value_that_is_not_a_token(upgraded, token):
    _, engine = upgraded
    with pytest.raises(IntegrityError):
        _insert_job(engine, "bad", NEW_COLUMN, token)


def test_downgrade_restores_the_sentences_and_keeps_the_jobs_without_a_wait(upgraded):
    config, engine = upgraded
    command.downgrade(config, PREVIOUS_REVISION)
    assert NEW_COLUMN not in column_names(engine, "jobs")
    stored = stored_values(engine, "jobs", OLD_COLUMN)
    for number, sentence in enumerate(SENTENCES):
        assert stored[f"known-{number}"] == sentence
    assert stored["unknown"] is None
    assert stored["none"] is None


def test_the_migration_upgrades_again_after_a_downgrade(upgraded):
    config, engine = upgraded
    command.downgrade(config, PREVIOUS_REVISION)
    command.upgrade(config, MIGRATION.revision)
    assert stored_values(engine, "jobs", NEW_COLUMN)["known-0"] == {
        "key": MIGRATION.STORED_MESSAGE_KEYS[SENTENCES[0]], "values": {},
    }


def test_the_keys_the_migration_stores_are_in_the_committed_set_of_stored_keys():
    committed = {
        line.strip() for line in STORED_KEYS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    assert set(MIGRATION.STORED_MESSAGE_KEYS.values()) <= committed

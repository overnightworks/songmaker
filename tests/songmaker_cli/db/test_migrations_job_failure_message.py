"""The migration that stores a job's failure as a message token plus the takes that completed."""

from __future__ import annotations

import importlib
import json
import logging
import re
from dataclasses import dataclass
from functools import partial

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import Engine
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
    "songmaker_cli.db.migrations.versions.c7e1a4d9b2f8_a_job_failure_is_stored_as_a_message"
)
PREVIOUS_REVISION = "b3a8d5e1f7c2"
OLD_COLUMN = "error"
NEW_COLUMN = "error_message"
TAKES_COLUMN = "completed_takes"
STORED_KEYS_FILE = REPOSITORY_ROOT / "scripts" / "stored_message_keys.txt"
WORKER_REPORTED_KEY = "jobFailure.workerReported"
RECORDED_KEY = "jobFailure.recorded"
GENERATION_FAILED_KEY = "jobFailure.generationFailed"
CHAT_PROBLEM_KEY = "chatFailure.problem"
ADMIN_ERROR_TYPE = "worker_error"
GENERATE_ERROR_TYPE = "generation_error"
JOB_COLUMNS = (
    "id", "type", "status", "progress", "heartbeat_at", "started_at", "error_type", "take_count",
)
SENTENCES = list(MIGRATION.STORED_MESSAGE_KEYS)
KNOWN_SENTENCE = SENTENCES[0]


@dataclass(frozen=True)
class SeededTexts:
    """The texts the seeded old rows carry, as a scenario owns them."""

    raw_worker: str = "CUDA error: device-side assert triggered at /srv/acestep/model.py:412"
    raw_admin: str = "Model weights file is corrupt: /srv/models/base.safetensors"
    unknown: str = "Somebody typed this into a row by hand."
    unsupported_mode: str = "Worker completed LoRA training with unsupported model mode: 'bogus'"
    chat_shaped_worker: str = "busy: private worker detail"
    mode_shaped_worker: str = (
        "Worker completed LoRA training with unsupported model mode: 'private worker detail'"
    )


@pytest.fixture
def texts() -> SeededTexts:
    return SeededTexts()


def _insert_failed_job(
    engine,
    job_id: str,
    column: str,
    value: object,
    *,
    error_type: str | None = None,
    job_type: str = "generate",
    take_count: int | None = None,
    extra: dict[str, object] | None = None,
) -> None:
    stored = value if column == OLD_COLUMN else sa.cast(json.dumps(value), sa.JSON)
    jobs = frozen_table("jobs", JOB_COLUMNS, column)
    with engine.begin() as connection:
        connection.execute(sa.insert(jobs).values(
            id=job_id, type=job_type, status="failed", progress=0.0,
            heartbeat_at=sa.func.current_timestamp(), started_at=sa.func.current_timestamp(),
            error_type=error_type, take_count=take_count, **{column: stored}, **(extra or {}),
        ))


def _partial(completed: int, count: int, failed: int, cause: str) -> str:
    return f"{completed}/{count} completed, {failed} failed: {cause}"


def _seed_failures(engine, texts: SeededTexts) -> None:
    for number, sentence in enumerate(SENTENCES):
        _insert_failed_job(engine, f"known-{number}", OLD_COLUMN, sentence)
    for job_id, sentence in (
        ("partial-known", _partial(3, 4, 1, KNOWN_SENTENCE)),
        ("partial-raw", _partial(1, 4, 3, texts.raw_worker)),
        ("partial-miscounted", _partial(3, 4, 2, KNOWN_SENTENCE)),
    ):
        _insert_failed_job(engine, job_id, OLD_COLUMN, sentence, error_type=GENERATE_ERROR_TYPE)
    _insert_failed_job(
        engine, "chat-known", OLD_COLUMN, "busy: the gateway is full",
        error_type="busy", job_type="chat",
    )
    _insert_failed_job(
        engine, "chat-unknown", OLD_COLUMN, "mood: the gateway is sad",
        error_type="mood", job_type="chat",
    )
    _insert_failed_job(
        engine, "mode", OLD_COLUMN, texts.unsupported_mode,
        error_type="lora_training_error", job_type="lora_training",
    )
    _insert_failed_job(
        engine, "admin", OLD_COLUMN, texts.raw_admin,
        error_type=ADMIN_ERROR_TYPE, job_type="load_model_on_worker",
    )
    _insert_failed_job(
        engine, "generate-raw", OLD_COLUMN, texts.raw_worker, error_type=GENERATE_ERROR_TYPE,
    )
    _insert_failed_job(
        engine, "generate-chat-shaped", OLD_COLUMN, texts.chat_shaped_worker,
        error_type=GENERATE_ERROR_TYPE,
    )
    _insert_failed_job(
        engine, "generate-mode-shaped", OLD_COLUMN, texts.mode_shaped_worker,
        error_type=GENERATE_ERROR_TYPE,
    )
    _insert_failed_job(
        engine, "other", OLD_COLUMN, texts.unknown, error_type="scoring_error", job_type="score",
    )
    _insert_failed_job(engine, "none", OLD_COLUMN, None)


def _upgrade(database, texts: SeededTexts) -> Engine:
    return seeded_then_upgraded(
        database, PREVIOUS_REVISION, MIGRATION.revision, partial(_seed_failures, texts=texts),
    )


@pytest.fixture
def upgraded(reference_link_database, texts):
    return reference_link_database[0], _upgrade(reference_link_database, texts)


def _token(engine, job_id: str) -> dict:
    return stored_values(engine, "jobs", NEW_COLUMN)[job_id]


def _worded(token: dict) -> str:
    return text(SOURCE_LANGUAGE, token["key"], **token["values"])


def test_the_migration_follows_the_previous_revision_on_the_single_chain():
    assert MIGRATION.down_revision == PREVIOUS_REVISION
    assert is_on_the_single_chain(MIGRATION.revision)


@pytest.mark.parametrize("number", range(len(SENTENCES)))
def test_a_known_sentence_becomes_the_token_that_words_it_again(upgraded, number):
    _, engine = upgraded
    token = _token(engine, f"known-{number}")
    assert token == {"key": MIGRATION.STORED_MESSAGE_KEYS[SENTENCES[number]], "values": {}}
    assert _worded(token) == SENTENCES[number]


def test_a_partial_whose_counts_agree_keeps_them_and_its_cause_becomes_a_token(upgraded):
    _, engine = upgraded
    token = _token(engine, "partial-known")
    assert token == {"key": MIGRATION.STORED_MESSAGE_KEYS[KNOWN_SENTENCE], "values": {}}
    assert stored_values(engine, "jobs", TAKES_COLUMN)["partial-known"] == 3
    assert stored_values(engine, "jobs", "take_count")["partial-known"] == 4


def test_a_partial_with_a_raw_generate_cause_keeps_its_counts_and_drops_the_raw_text(upgraded):
    _, engine = upgraded
    token = _token(engine, "partial-raw")
    assert token == {"key": GENERATION_FAILED_KEY, "values": {}}
    assert stored_values(engine, "jobs", TAKES_COLUMN)["partial-raw"] == 1
    assert stored_values(engine, "jobs", "take_count")["partial-raw"] == 4


def test_a_partial_whose_counts_disagree_is_recorded_whole_without_takes(upgraded):
    _, engine = upgraded
    whole = _partial(3, 4, 2, KNOWN_SENTENCE)
    assert _token(engine, "partial-miscounted") == {"key": RECORDED_KEY, "values": {"cause": whole}}
    assert stored_values(engine, "jobs", TAKES_COLUMN)["partial-miscounted"] is None
    assert _worded(_token(engine, "partial-miscounted")) == whole


def test_a_chat_problem_keeps_its_problem_and_detail_as_gap_values(upgraded):
    _, engine = upgraded
    token = _token(engine, "chat-known")
    assert token == {
        "key": CHAT_PROBLEM_KEY, "values": {"problem": "busy", "detail": "the gateway is full"},
    }
    assert _worded(token) == "busy: the gateway is full"


def test_a_chat_text_with_an_unknown_problem_is_recorded_whole(upgraded):
    _, engine = upgraded
    token = _token(engine, "chat-unknown")
    assert token == {"key": RECORDED_KEY, "values": {"cause": "mood: the gateway is sad"}}
    assert _worded(token) == "mood: the gateway is sad"


def test_a_mode_error_keeps_the_quoted_mode_as_a_gap_value(upgraded, texts):
    _, engine = upgraded
    token = _token(engine, "mode")
    assert token == {"key": "voiceFailure.modeUnsupported", "values": {"workerMode": "'bogus'"}}
    assert _worded(token) == texts.unsupported_mode


def test_an_admin_model_job_keeps_the_worker_text_as_the_cause_it_reported(upgraded, texts):
    _, engine = upgraded
    token = _token(engine, "admin")
    assert token == {"key": WORKER_REPORTED_KEY, "values": {"cause": texts.raw_admin}}
    assert texts.raw_admin in _worded(token)


def test_a_raw_generate_cause_becomes_the_generation_failed_token_and_the_raw_text_is_gone(
    upgraded, texts,
):
    _, engine = upgraded
    token = _token(engine, "generate-raw")
    assert token == {"key": GENERATION_FAILED_KEY, "values": {}}
    assert texts.raw_worker not in json.dumps(stored_values(engine, "jobs", NEW_COLUMN))


@pytest.mark.parametrize("job_id", ["generate-chat-shaped", "generate-mode-shaped"])
def test_a_raw_generate_cause_shaped_like_a_chat_or_mode_text_is_dropped_too(
    upgraded, job_id,
):
    _, engine = upgraded
    assert _token(engine, job_id) == {"key": GENERATION_FAILED_KEY, "values": {}}
    assert "private worker detail" not in json.dumps(stored_values(engine, "jobs", NEW_COLUMN))


def test_any_other_text_is_recorded_with_the_text_as_its_cause(upgraded, texts):
    _, engine = upgraded
    token = _token(engine, "other")
    assert token == {"key": RECORDED_KEY, "values": {"cause": texts.unknown}}
    assert _worded(token) == texts.unknown


def test_a_job_without_a_failure_stays_sql_null(upgraded):
    _, engine = upgraded
    with engine.connect() as connection:
        unset = connection.execute(
            sa.text("SELECT id FROM jobs WHERE error_message IS NULL"),
        ).scalars().all()
    assert unset == ["none"]


def test_a_job_that_is_not_a_partial_gets_no_completed_takes(upgraded):
    _, engine = upgraded
    with_takes = {
        job_id for job_id, takes in stored_values(engine, "jobs", TAKES_COLUMN).items()
        if takes is not None
    }
    assert with_takes == {"partial-known", "partial-raw"}


def test_every_bucket_count_is_logged(reference_link_database, texts, caplog):
    caplog.set_level(logging.INFO, logger="alembic.runtime.migration")
    _upgrade(reference_link_database, texts)
    logged = " ".join(
        record.getMessage() for record in caplog.records if record.name.startswith("alembic")
    )
    assert {bucket: int(count) for bucket, count in re.findall(r"(\w+)=(\d+)", logged)} == {
        "exact": len(SENTENCES), "partial": 2, "mode": 1, "chat": 1, "workerReported": 1,
        "generationFailed": 3, "recorded": 3, "null": 1,
    }


def test_upgrade_replaces_the_sentence_column_by_the_token_and_takes_columns(upgraded):
    _, engine = upgraded
    names = column_names(engine, "jobs")
    assert {NEW_COLUMN, TAKES_COLUMN} <= names
    assert OLD_COLUMN not in names


@pytest.mark.parametrize(
    "token",
    [
        pytest.param({"key": 7, "values": {}}, id="key-not-a-string"),
        pytest.param({"values": {}}, id="key-missing"),
        pytest.param({"key": "jobFailure.internal", "values": []}, id="values-not-an-object"),
        pytest.param({"key": "jobFailure.internal"}, id="values-missing"),
    ],
)
def test_the_database_refuses_a_value_that_is_not_a_token(upgraded, token):
    _, engine = upgraded
    with pytest.raises(IntegrityError):
        _insert_failed_job(engine, "bad", NEW_COLUMN, token)


def test_downgrade_raises_and_names_the_backup(upgraded):
    config, _ = upgraded
    with pytest.raises(Exception, match="restore a backup"):
        command.downgrade(config, PREVIOUS_REVISION)


def test_the_keys_the_migration_stores_are_in_the_committed_set_of_stored_keys():
    committed = {
        line.strip() for line in STORED_KEYS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    stored = {
        *MIGRATION.STORED_MESSAGE_KEYS.values(),
        WORKER_REPORTED_KEY, RECORDED_KEY, GENERATION_FAILED_KEY, CHAT_PROBLEM_KEY,
        *MIGRATION.MODE_TEMPLATES,
    }
    assert stored <= committed
    assert not (MIGRATION.RETIRED_STORED_KEYS & committed)

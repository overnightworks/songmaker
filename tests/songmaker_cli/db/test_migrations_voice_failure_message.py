"""The migration that stores a failed voice's reason as a message token, not an English sentence."""

from __future__ import annotations

import importlib
import json

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
from support.reference_link_migration import seed_users
from support.repository_root import REPOSITORY_ROOT

from songmaker_cli.words import SOURCE_LANGUAGE, text

MIGRATION = importlib.import_module(
    "songmaker_cli.db.migrations.versions.b3a8d5e1f7c2_a_failed_voice_is_stored_as_a_message"
)
PREVIOUS_REVISION = "a9d3f1b7c5e2"
OLD_COLUMN = "error"
NEW_COLUMN = "error_message"
STORED_KEYS_FILE = REPOSITORY_ROOT / "scripts" / "stored_message_keys.txt"
RECORDED_KEY = "voiceFailure.recorded"
CANCELLED_KEY = "voiceFailure.cancelled"
HISTORIC_CANCEL_SENTENCE = "Job cancelled: exceeded ARQ_JOB_TIMEOUT or worker shutdown"
UNSUPPORTED_SENTENCE = (
    "Worker completed LoRA training with unsupported model mode: 'bogus'"
)
MISMATCH_SENTENCE = (
    "Worker completed LoRA training with model mode 'sft', expected 'turbo'"
)
MODE_TOKENS = {
    UNSUPPORTED_SENTENCE: {
        "key": "voiceFailure.modeUnsupported",
        "values": {"workerMode": "'bogus'"},
    },
    MISMATCH_SENTENCE: {
        "key": "voiceFailure.modeMismatch",
        "values": {"workerMode": "'sft'", "requestedMode": "'turbo'"},
    },
}
UNKNOWN_SENTENCE = "The worker restarted before epoch 31 could finish."
SENTENCES = list(MIGRATION.STORED_MESSAGE_KEYS)
USER_LORA_COLUMNS = ("id", "user_id", "name", "slug", "status", "model_mode", "created_at")


def _insert_lora(engine, lora_id: str, column: str, value: object) -> None:
    stored = value if column == OLD_COLUMN else sa.cast(json.dumps(value), sa.JSON)
    with engine.begin() as connection:
        connection.execute(sa.insert(frozen_table("user_loras", USER_LORA_COLUMNS, column)).values(
            id=lora_id, user_id="u1", name=lora_id, slug=lora_id, status="failed",
            model_mode="turbo", created_at=sa.func.current_timestamp(), **{column: stored},
        ))


def _seed_voices(engine) -> None:
    seed_users(engine)
    for number, sentence in enumerate(SENTENCES):
        _insert_lora(engine, f"known-{number}", OLD_COLUMN, sentence)
    for number, sentence in enumerate(MODE_TOKENS):
        _insert_lora(engine, f"mode-{number}", OLD_COLUMN, sentence)
    _insert_lora(engine, "unknown", OLD_COLUMN, UNKNOWN_SENTENCE)
    _insert_lora(engine, "none", OLD_COLUMN, None)


@pytest.fixture
def upgraded(reference_link_database):
    engine = seeded_then_upgraded(
        reference_link_database, PREVIOUS_REVISION, MIGRATION.revision, _seed_voices,
    )
    return reference_link_database[0], engine


def test_the_migration_follows_the_previous_revision_on_the_single_chain():
    assert MIGRATION.down_revision == PREVIOUS_REVISION
    assert is_on_the_single_chain(MIGRATION.revision)


def test_every_known_sentence_becomes_the_token_that_words_it_again(upgraded):
    _, engine = upgraded
    stored = stored_values(engine, "user_loras", NEW_COLUMN)
    for number, sentence in enumerate(SENTENCES):
        token = stored[f"known-{number}"]
        assert token == {"key": MIGRATION.STORED_MESSAGE_KEYS[sentence], "values": {}}
        if sentence != HISTORIC_CANCEL_SENTENCE:
            assert text(SOURCE_LANGUAGE, token["key"]) == sentence


def test_the_historic_cancel_sentence_becomes_the_cancelled_token(upgraded):
    _, engine = upgraded
    stored = stored_values(engine, "user_loras", NEW_COLUMN)
    token = stored[f"known-{SENTENCES.index(HISTORIC_CANCEL_SENTENCE)}"]
    assert token == {"key": CANCELLED_KEY, "values": {}}


@pytest.mark.parametrize("number", range(len(MODE_TOKENS)))
def test_a_mode_error_becomes_its_token_with_the_gap_values_it_quoted(upgraded, number):
    _, engine = upgraded
    sentence = list(MODE_TOKENS)[number]
    token = stored_values(engine, "user_loras", NEW_COLUMN)[f"mode-{number}"]
    assert token == MODE_TOKENS[sentence]
    assert text(SOURCE_LANGUAGE, token["key"], **token["values"]) == sentence


def test_an_unknown_sentence_is_kept_as_the_recorded_token_with_its_text_as_the_cause(upgraded):
    _, engine = upgraded
    token = stored_values(engine, "user_loras", NEW_COLUMN)["unknown"]
    assert token == {"key": RECORDED_KEY, "values": {"cause": UNKNOWN_SENTENCE}}
    assert text(SOURCE_LANGUAGE, token["key"], **token["values"]) == UNKNOWN_SENTENCE


def test_a_voice_without_a_reason_stays_sql_null(upgraded):
    _, engine = upgraded
    loras = frozen_table("user_loras", USER_LORA_COLUMNS, NEW_COLUMN)
    with engine.connect() as connection:
        null_ids = set(connection.execute(
            sa.select(loras.c.id).where(loras.c[NEW_COLUMN].is_(None))
        ).scalars())
    assert null_ids == {"none"}


def test_upgrade_replaces_the_sentence_column_by_the_token_column(upgraded):
    _, engine = upgraded
    names = column_names(engine, "user_loras")
    assert NEW_COLUMN in names
    assert OLD_COLUMN not in names


@pytest.mark.parametrize(
    "token",
    [
        pytest.param({"key": 7, "values": {}}, id="key-not-a-string"),
        pytest.param({"values": {}}, id="key-missing"),
        pytest.param({"key": "voiceFailure.crashed", "values": []}, id="values-not-an-object"),
        pytest.param({"key": "voiceFailure.crashed"}, id="values-missing"),
    ],
)
def test_the_database_refuses_a_value_that_is_not_a_token(upgraded, token):
    _, engine = upgraded
    with pytest.raises(IntegrityError):
        _insert_lora(engine, "bad", NEW_COLUMN, token)


def test_downgrade_restores_every_sentence_and_keeps_the_voices_without_a_reason(upgraded):
    config, engine = upgraded
    command.downgrade(config, PREVIOUS_REVISION)
    assert NEW_COLUMN not in column_names(engine, "user_loras")
    stored = stored_values(engine, "user_loras", OLD_COLUMN)
    for number, sentence in enumerate(SENTENCES):
        expected = (
            text(SOURCE_LANGUAGE, MIGRATION.STORED_MESSAGE_KEYS[sentence])
            if sentence == HISTORIC_CANCEL_SENTENCE else sentence
        )
        assert stored[f"known-{number}"] == expected
    for number, sentence in enumerate(MODE_TOKENS):
        assert stored[f"mode-{number}"] == sentence
    assert stored["unknown"] == UNKNOWN_SENTENCE
    assert stored["none"] is None


def test_the_migration_upgrades_again_after_a_downgrade(upgraded):
    config, engine = upgraded
    command.downgrade(config, PREVIOUS_REVISION)
    command.upgrade(config, MIGRATION.revision)
    assert stored_values(engine, "user_loras", NEW_COLUMN)["unknown"] == {
        "key": RECORDED_KEY, "values": {"cause": UNKNOWN_SENTENCE},
    }


def test_the_keys_the_migration_stores_are_in_the_committed_set_of_stored_keys():
    committed = {
        line.strip() for line in STORED_KEYS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    stored = {
        *MIGRATION.STORED_MESSAGE_KEYS.values(),
        RECORDED_KEY,
        *(token["key"] for token in MODE_TOKENS.values()),
    }
    assert stored <= committed

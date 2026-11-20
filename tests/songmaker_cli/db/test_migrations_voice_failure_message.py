"""The migration that stores a failed voice's reason as a message token, not an English sentence."""

from __future__ import annotations

import importlib
import json

import pytest
import sqlalchemy as sa
from alembic import command
from support.migration_chain import (
    column_names,
    frozen_table,
    seeded_then_upgraded,
    stored_values,
)
from support.reference_link_migration import seed_users
from support.stored_message_contract import StoredMessageMigrationContract

from songmaker_cli.words import SOURCE_LANGUAGE, text

MIGRATION = importlib.import_module(
    "songmaker_cli.db.migrations.versions.b3a8d5e1f7c2_a_failed_voice_is_stored_as_a_message"
)
PREVIOUS_REVISION = "a9d3f1b7c5e2"
OLD_COLUMN = "error"
NEW_COLUMN = "error_message"
RECORDED_KEY = "voiceFailure.recorded"
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
    _insert_lora(engine, "historic-cancel", OLD_COLUMN, HISTORIC_CANCEL_SENTENCE)
    _insert_lora(engine, "none", OLD_COLUMN, None)


@pytest.fixture
def upgraded(reference_link_database):
    engine = seeded_then_upgraded(
        reference_link_database, PREVIOUS_REVISION, MIGRATION.revision, _seed_voices,
    )
    return reference_link_database[0], engine


def test_the_migration_follows_the_previous_revision():
    assert MIGRATION.down_revision == PREVIOUS_REVISION



def test_the_historic_cancel_sentence_is_kept_as_the_recorded_token(upgraded):
    _, engine = upgraded
    token = stored_values(engine, "user_loras", NEW_COLUMN)["historic-cancel"]
    assert token == {"key": RECORDED_KEY, "values": {"cause": HISTORIC_CANCEL_SENTENCE}}
    assert text(SOURCE_LANGUAGE, token["key"], **token["values"]) == HISTORIC_CANCEL_SENTENCE


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




def test_downgrade_restores_every_sentence_and_keeps_the_voices_without_a_reason(upgraded):
    config, engine = upgraded
    command.downgrade(config, PREVIOUS_REVISION)
    assert NEW_COLUMN not in column_names(engine, "user_loras")
    stored = stored_values(engine, "user_loras", OLD_COLUMN)
    for number, sentence in enumerate(SENTENCES):
        assert stored[f"known-{number}"] == sentence
    assert stored["historic-cancel"] == HISTORIC_CANCEL_SENTENCE
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


class TestVoiceFailureMigration(StoredMessageMigrationContract):
    migration = MIGRATION
    table = "user_loras"
    old_column = OLD_COLUMN
    new_column = NEW_COLUMN
    insert_row = staticmethod(_insert_lora)
    other_stored_keys = frozenset({RECORDED_KEY, *(token["key"] for token in MODE_TOKENS.values())})

"""A failed voice's reason is stored as a message token instead of an English sentence

Revision ID: b3a8d5e1f7c2
Revises: a9d3f1b7c5e2
Create Date: 2026-11-15 09:00:00.000000

user_loras.error (Text) becomes user_loras.error_message (JSON, a catalog key and the values of
its gaps). Each sentence a writer ever stored maps to its key through the frozen table below, the
two mode errors map through their templates with the quoted modes as gap values, and any other
text is kept as `voiceFailure.recorded` with the text as its cause, so nothing is lost. NULL stays
NULL. The downgrade writes each token's sentence back; `recorded` writes its cause.
"""
from __future__ import annotations

import re
from typing import Any, Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3a8d5e1f7c2"
down_revision: str | Sequence[str] | None = "a9d3f1b7c5e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# why: frozen on purpose, so the migration never reads the catalog a later revision changes. The
# first sentence of a key is the one the downgrade writes back.
STORED_MESSAGE_KEYS: dict[str, str] = {
    "Failed to download generated audio": "jobFailure.audioDownloadFailed",
    "ACE-Step server not reachable": "jobFailure.serverUnreachable",
    "Generation timed out": "jobFailure.generationTimedOut",
    "No ACE-Step workers available": "jobFailure.noWorkers",
    "Internal error during processing": "jobFailure.internal",
    "An unexpected error occurred": "jobFailure.unexpected",
    "Generating failed — try again.": "jobFailure.generationFailed",
    "Generating isn't available right now.": "jobFailure.generationUnavailable",
    "Too long for the GPU right now — try a shorter duration.": "jobFailure.gpuOutOfMemory",
    "Worker training failed": "voiceFailure.workerTrainingFailed",
    "Training crashed or was interrupted": "voiceFailure.crashed",
    "Generation queue did not drain before LoRA training could start": (
        "voiceFailure.drainTimeout"
    ),
    "Job cancelled: exceeded LORA_TRAINING_JOB_TIMEOUT or worker shutdown": (
        "voiceFailure.cancelled"
    ),
    "Job cancelled: exceeded ARQ_JOB_TIMEOUT or worker shutdown": "voiceFailure.cancelled",
    "Job queue unavailable": "jobRefusal.queueUnavailable",
}
# why: the two sentences that quote the worker's and the requested mode, with the quotes kept.
MODE_TEMPLATES: dict[str, str] = {
    "voiceFailure.modeUnsupported": (
        "Worker completed LoRA training with unsupported model mode: {workerMode}"
    ),
    "voiceFailure.modeMismatch": (
        "Worker completed LoRA training with model mode {workerMode}, expected {requestedMode}"
    ),
}
RECORDED_KEY = "voiceFailure.recorded"
SHAPE_CONSTRAINT = "ck_user_loras_error_message_shape"
SHAPE_CHECK = (
    "error_message IS NULL OR ("
    "COALESCE(json_typeof(error_message->'key'), '') = 'string' "
    "AND COALESCE(json_typeof(error_message->'values'), '') = 'object')"
)

_SENTENCE_OF_KEY: dict[str, str] = {}
for _sentence, _key in STORED_MESSAGE_KEYS.items():
    _SENTENCE_OF_KEY.setdefault(_key, _sentence)
_MODE_PATTERNS: dict[str, re.Pattern[str]] = {
    key: re.compile(re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>.+)", re.escape(template)), re.DOTALL)
    for key, template in MODE_TEMPLATES.items()
}

user_loras = sa.table(
    "user_loras",
    sa.column("id", sa.String),
    sa.column("error", sa.Text),
    sa.column("error_message", sa.JSON(none_as_null=True)),
)


def _token_of(sentence: str) -> dict[str, object]:
    if sentence in STORED_MESSAGE_KEYS:
        return {"key": STORED_MESSAGE_KEYS[sentence], "values": {}}
    for key, pattern in _MODE_PATTERNS.items():
        matched = pattern.fullmatch(sentence)
        if matched:
            return {"key": key, "values": matched.groupdict()}
    return {"key": RECORDED_KEY, "values": {"cause": sentence}}


def _sentence_of(lora_id: str, token: dict[str, Any]) -> str:
    key, values = token["key"], token["values"]
    if key == RECORDED_KEY:
        return values["cause"]
    if key in MODE_TEMPLATES:
        return MODE_TEMPLATES[key].format(**values)
    if key in _SENTENCE_OF_KEY:
        return _SENTENCE_OF_KEY[key]
    raise ValueError(f"user_loras {lora_id} holds the key {key}, which has no stored sentence")


def upgrade() -> None:
    op.add_column(
        "user_loras", sa.Column("error_message", sa.JSON(none_as_null=True), nullable=True),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(user_loras.c.id, user_loras.c.error).where(user_loras.c.error.is_not(None)),
    ).all()
    for lora_id, sentence in rows:
        connection.execute(
            sa.update(user_loras)
            .where(user_loras.c.id == lora_id)
            .values(error_message=_token_of(sentence)),
        )
    op.create_check_constraint(SHAPE_CONSTRAINT, "user_loras", SHAPE_CHECK)
    op.drop_column("user_loras", "error")


def downgrade() -> None:
    op.add_column("user_loras", sa.Column("error", sa.Text(), nullable=True))
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(user_loras.c.id, user_loras.c.error_message).where(
            user_loras.c.error_message.is_not(None),
        ),
    ).all()
    for lora_id, token in rows:
        connection.execute(
            sa.update(user_loras)
            .where(user_loras.c.id == lora_id)
            .values(error=_sentence_of(lora_id, token)),
        )
    op.drop_constraint(SHAPE_CONSTRAINT, "user_loras", type_="check")
    op.drop_column("user_loras", "error_message")

"""A job's failure is stored as a message token and the takes that completed, not a sentence

Revision ID: c7e1a4d9b2f8
Revises: b3a8d5e1f7c2
Create Date: 2026-11-16 12:00:00.000000

jobs.error (Text) becomes jobs.error_message (JSON, a catalog key and the values of its gaps),
and jobs.completed_takes (nullable integer) holds the takes a partial Generate finished. Each
sentence the current writers store maps to its key through the frozen table below. The other
classes of old row map as follows:

* a partial prefix "c/n completed, f failed: cause" keeps its counts when f = n - c, and its cause
  maps like any other text; any other prefix is kept whole as `jobFailure.recorded`;
* the two LoRA mode errors of a LoRA training job and the chat "<problem>: <detail>" of a chat job
  map through their templates with the quoted values as gaps; the same text on any other job
  type is no such template and falls to the buckets below;
* an admin model job's raw worker text is `jobFailure.workerReported` with the text as its cause;
* the raw worker text of an old Generate row (error type `generation_error`) is dropped for good:
  the row becomes `jobFailure.generationFailed`;
* any other text is kept as `jobFailure.recorded` with the text as its cause.

NULL stays NULL. Each bucket's row count is logged. The downgrade raises: the dropped worker text
and the reworded causes cannot be restored, so a backup is.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Mapping
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7e1a4d9b2f8"
down_revision: str | Sequence[str] | None = "b3a8d5e1f7c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

# why: these two keys held a stored message in the code that wrote them; the keys that replace
# them are `jobFailure.workerReported` and the takes column.
RETIRED_STORED_KEYS = frozenset({"jobFailure.partialTakes", "jobFailure.reported"})

# why: frozen on purpose, so the migration never reads the catalog a later revision changes.
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
    "Song not found": "jobFailure.songNotFound",
    "Version not found": "jobFailure.versionNotFound",
    "Reference audio not found": "jobFailure.referenceAudioNotFound",
    "The reference track was deleted while this take was generating.": (
        "jobFailure.referenceDeletedDuringTake"
    ),
    "Selected voice is unavailable for this generation": "jobFailure.voiceUnavailable",
    "Job cancelled: exceeded ARQ_JOB_TIMEOUT or worker shutdown": (
        "jobFailure.generationCancelled"
    ),
    "Scoring worker not running": "jobFailure.scoringWorkerDown",
    "Failed to enqueue auto-score job": "jobFailure.scoringEnqueueFailed",
    "Audio file not found for scoring": "jobFailure.scoringAudioMissing",
    "Generation not found": "jobFailure.scoringGenerationMissing",
    "Server restarted while job was in progress": "jobFailure.serverRestarted",
    "No worker alive for this job type — please retry.": "jobFailure.noWorkerAlive",
    "Queued longer than a full queue could take — please retry.": (
        "jobFailure.queuedFullQueueBound"
    ),
    "Queued too long — please retry.": "jobFailure.queuedTooLong",
    "Took too long to finish — please retry.": "jobFailure.tookTooLong",
    "Job queue unavailable": "jobRefusal.queueUnavailable",
    "Chat request cancelled": "chatFailure.requestCancelled",
    "Chat setup failed": "chatFailure.setupFailed",
    "Chat request failed": "chatFailure.requestFailed",
    "Chat completion failed": "chatFailure.completionFailed",
    "Turn cancelled by the client.": "chatFailure.clientCancelled",
    "Cover suggestions are busy. Try again when Suggest opens.": "coverProblem.busy",
    "The budget for cover suggestions is used up. Try again later.": "coverProblem.budgetSpent",
    "Cover suggestions are not enabled for your account. Ask an admin to enable them.": (
        "coverProblem.notEnabled"
    ),
    "Cover suggestions are unavailable right now. Try again later.": "coverProblem.unavailable",
    "Log in again to get cover suggestions.": "coverProblem.signInAgain",
    "LoRA not found": "voiceFailure.notFound",
    "LoRA is deleted": "voiceFailure.deleted",
    "Worker training failed": "voiceFailure.workerTrainingFailed",
    "Training crashed or was interrupted": "voiceFailure.crashed",
    "Generation queue did not drain before LoRA training could start": (
        "voiceFailure.drainTimeout"
    ),
    "Job cancelled: exceeded LORA_TRAINING_JOB_TIMEOUT or worker shutdown": (
        "voiceFailure.cancelled"
    ),
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
CHAT_PROBLEM_KEY = "chatFailure.problem"
CHAT_PROBLEMS = ("unavailable", "busy", "budget_spent", "not_enabled", "sign_in_again")
WORKER_REPORTED_KEY = "jobFailure.workerReported"
GENERATION_FAILED_KEY = "jobFailure.generationFailed"
RECORDED_KEY = "jobFailure.recorded"
# why: the error types the admin model load and download jobs store beside a raw worker text.
ADMIN_MODEL_ERROR_TYPES = frozenset(
    {"worker_error", "worker_unreachable", "download_error", "sse_transport"},
)
GENERATE_ERROR_TYPE = "generation_error"
LORA_TRAINING_JOB_TYPE = "lora_training"
CHAT_JOB_TYPE = "chat"
BUCKETS = (
    "exact", "partial", "mode", "chat", "workerReported", "generationFailed", "recorded", "null",
)
SHAPE_CONSTRAINT = "ck_jobs_error_message_shape"
SHAPE_CHECK = (
    "error_message IS NULL OR ("
    "COALESCE(json_typeof(error_message->'key'), '') = 'string' "
    "AND COALESCE(json_typeof(error_message->'values'), '') = 'object')"
)

_MODE_PATTERNS: dict[str, re.Pattern[str]] = {
    key: re.compile(re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>.+)", re.escape(template)), re.DOTALL)
    for key, template in MODE_TEMPLATES.items()
}
_CHAT_PATTERN = re.compile(rf"(?P<problem>{'|'.join(CHAT_PROBLEMS)}): (?P<detail>.*)", re.DOTALL)
_PARTIAL_PATTERN = re.compile(
    r"(?P<completed>\d+)/(?P<count>\d+) completed, (?P<failed>\d+) failed: (?P<cause>.*)",
    re.DOTALL | re.ASCII,
)

jobs = sa.table(
    "jobs",
    sa.column("id", sa.String),
    sa.column("error", sa.Text),
    sa.column("error_type", sa.String),
    sa.column("type", sa.String),
    sa.column("take_count", sa.Integer),
    sa.column("error_message", sa.JSON(none_as_null=True)),
    sa.column("completed_takes", sa.Integer),
)


def _token(key: str, values: Mapping[str, str] | None = None) -> dict[str, object]:
    return {"key": key, "values": dict(values or {})}


def _classified(
    sentence: str, error_type: str | None, job_type: str,
) -> tuple[str, dict[str, object]]:
    """The bucket of a stored sentence and the token it becomes; a partial is no cause."""
    if sentence in STORED_MESSAGE_KEYS:
        return "exact", _token(STORED_MESSAGE_KEYS[sentence])
    if job_type == LORA_TRAINING_JOB_TYPE:
        for key, pattern in _MODE_PATTERNS.items():
            matched = pattern.fullmatch(sentence)
            if matched:
                return "mode", _token(key, matched.groupdict())
    chat = _CHAT_PATTERN.fullmatch(sentence) if job_type == CHAT_JOB_TYPE else None
    if chat:
        return "chat", _token(CHAT_PROBLEM_KEY, chat.groupdict())
    if error_type == GENERATE_ERROR_TYPE:
        return "generationFailed", _token(GENERATION_FAILED_KEY)
    if error_type in ADMIN_MODEL_ERROR_TYPES:
        return "workerReported", _token(WORKER_REPORTED_KEY, {"cause": sentence})
    return "recorded", _token(RECORDED_KEY, {"cause": sentence})


def _migrated(
    sentence: str, error_type: str | None, job_type: str,
) -> tuple[str, dict[str, object], int | None, int | None]:
    """The bucket, the token, the takes that completed and the takes asked for, of one row."""
    partial = _PARTIAL_PATTERN.fullmatch(sentence)
    if partial:
        completed, count, failed = (int(partial[name]) for name in ("completed", "count", "failed"))
        if failed != count - completed:
            return "recorded", _token(RECORDED_KEY, {"cause": sentence}), None, None
        _, token = _classified(partial["cause"], error_type, job_type)
        return "partial", token, completed, count
    bucket, token = _classified(sentence, error_type, job_type)
    return bucket, token, None, None


def upgrade() -> None:
    op.add_column(
        "jobs", sa.Column("error_message", sa.JSON(none_as_null=True), nullable=True),
    )
    op.add_column("jobs", sa.Column("completed_takes", sa.Integer(), nullable=True))
    connection = op.get_bind()
    counts: Counter[str] = Counter()
    rows = connection.execute(
        sa.select(jobs.c.id, jobs.c.error, jobs.c.error_type, jobs.c.type)
        .where(jobs.c.error.is_not(None)),
    ).all()
    for job_id, sentence, error_type, job_type in rows:
        bucket, token, completed, count = _migrated(sentence, error_type, job_type)
        counts[bucket] += 1
        values: dict[str, object] = {"error_message": token}
        if completed is not None:
            values.update(completed_takes=completed, take_count=count)
        connection.execute(sa.update(jobs).where(jobs.c.id == job_id).values(**values))
    counts["null"] = connection.execute(
        sa.select(sa.func.count()).select_from(jobs).where(jobs.c.error.is_(None)),
    ).scalar_one()
    logger.info(
        "Stored job failures as messages: %s",
        ", ".join(f"{bucket}={counts[bucket]}" for bucket in BUCKETS),
    )
    op.create_check_constraint(SHAPE_CONSTRAINT, "jobs", SHAPE_CHECK)
    op.drop_column("jobs", "error")


def downgrade() -> None:
    raise NotImplementedError(
        "irreversible: the raw worker text of old Generate rows is dropped and the stored "
        "causes are reworded; restore a backup instead",
    )

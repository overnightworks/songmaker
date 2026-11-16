from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from songmaker_cli.api_models.jobs import JobResponse
from songmaker_cli.db.models import Job
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.messages import Message, message

NOW = datetime(2030, 1, 1, 0, 10, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("current_epoch", "train_epochs", "elapsed_seconds", "expected"),
    [
        pytest.param(None, None, 60, "calculating", id="before-first-progress-report"),
        pytest.param(2, None, 60, "calculating", id="epoch-count-missing"),
        pytest.param(None, 10, 60, "calculating", id="current-epoch-missing"),
        pytest.param(0, 10, 60, "calculating", id="epoch-zero"),
        pytest.param(11, 10, 60, "calculating", id="worker-overshoots-total"),
        pytest.param(2, 10, None, "calculating", id="start-time-missing"),
        pytest.param(2, 10, -30, "calculating", id="start-time-ahead-of-clock"),
        pytest.param(2, 10, 0, "calculating", id="start-time-equals-clock"),
        pytest.param(2, 10, 60, 240, id="epochs-remaining"),
        pytest.param(10, 10, 60, 0, id="final-epoch"),
    ],
)
def test_running_lora_training_estimate_follows_the_workers_epoch_reports(
    current_epoch: int | None,
    train_epochs: int | None,
    elapsed_seconds: int | None,
    expected: int | str,
) -> None:
    job = Job(
        id="job-1",
        type=JobType.LORA_TRAINING,
        status=JobStatus.RUNNING,
        progress=0.5,
        current_epoch=current_epoch,
        train_epochs=train_epochs,
        training_started_at=(
            NOW - timedelta(seconds=elapsed_seconds) if elapsed_seconds is not None else None
        ),
    )

    assert JobResponse.from_orm(job, now=NOW).remaining_time_estimate == expected


@pytest.mark.parametrize(
    ("wait", "sentence"),
    [
        pytest.param(
            message("jobWait.voiceTraining"), "Waiting for LoRA training on this GPU.",
            id="voice-training",
        ),
        pytest.param(
            message("jobWait.queuedGenerations"), "Waiting for queued generations on this GPU.",
            id="queued-generations",
        ),
        pytest.param(None, None, id="no-wait"),
    ],
)
def test_a_queue_wait_is_answered_as_the_unchanged_agent_sentence_and_its_message(wait, sentence):
    job = Job(
        id="job-1", type=JobType.GENERATE, status=JobStatus.QUEUED, progress=0.0,
        queue_reason_message=wait,
    )

    response = JobResponse.from_orm(job)

    assert response.queue_reason == sentence
    assert response.queue_reason_message == wait


def test_a_queue_wait_whose_key_the_catalog_lacks_fails_that_response_and_logs_job_and_key(
    caplog,
):
    job = Job(
        id="job-1", type=JobType.GENERATE, status=JobStatus.QUEUED, progress=0.0,
        queue_reason_message=Message(key="jobWait.retired", values={}),
    )

    with pytest.raises(KeyError):
        JobResponse.from_orm(job)

    assert "job-1" in caplog.text
    assert "jobWait.retired" in caplog.text


@pytest.mark.parametrize(
    ("completed_takes", "take_count", "cause", "expected"),
    [
        (None, None, "jobFailure.generationTimedOut", "Generation timed out"),
        (1, 2, "jobFailure.generationTimedOut", "1/2 completed, 1 failed: Generation timed out"),
        (
            12, 15, "jobFailure.generationFailed",
            "12/15 completed, 3 failed: Generating failed — try again.",
        ),
    ],
)
def test_response_sentence_of_a_failure_leads_a_partial_with_its_takes(
    completed_takes, take_count, cause, expected,
):
    """L11: An agent reads a partial Generate failure as its takes and then its cause."""
    job = Job(
        id="partial", type="generate", status="partial", progress=0.5,
        error_message=message(cause), completed_takes=completed_takes, take_count=take_count,
        error_type="generation_error",
    )
    response = JobResponse.from_orm(job)
    assert response.error == expected
    assert response.error_message == message(cause)
    assert response.completed_takes == completed_takes


def test_response_of_a_job_without_a_failure_has_no_sentence_and_no_message():
    response = JobResponse.from_orm(Job(id="ok", type="generate", status="running", progress=0.1))
    assert (response.error, response.error_message, response.completed_takes) == (None, None, None)


def test_response_fails_loudly_for_completed_takes_without_a_take_count():
    job = Job(
        id="broken", type="generate", status="partial", progress=0.5,
        error_message=message("jobFailure.generationFailed"), completed_takes=1,
    )
    with pytest.raises(RuntimeError, match="completed takes without a take count"):
        JobResponse.from_orm(job)

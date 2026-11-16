"""Generate failure ownership without worker or database dependencies."""

import pytest
from support.generation_failures import GENERATION_SETUP_REASONS

from songmaker_cli.jobs._runtime import GenerationSetupError
from songmaker_cli.jobs.generation_failure import (
    generation_failure,
    running_failure_pair,
    select_generation_failure,
)
from songmaker_cli.messages import message
from songmaker_cli.scheduler import (
    WorkerGenerationFailed,
    WorkerGenerationUnavailable,
    WorkerGpuOutOfMemory,
    WorkerModeNotLoaded,
    WorkerProtocolError,
    WorkerTaskFailed,
)


@pytest.mark.parametrize(
    "error_class",
    [WorkerTaskFailed, WorkerGenerationFailed, WorkerProtocolError, WorkerModeNotLoaded],
)
@pytest.mark.parametrize("cause", ["18.5 GB required", "Generation timed out", ""])
def test_worker_family_gets_generic_message_and_type(error_class, cause, caplog):
    """defect:#1569: Worker identity, never its wording, decides the message."""
    failure = generation_failure(error_class(cause), "worker-job")
    assert failure.message.sentence() == "Generating failed — try again."
    assert failure.error_type == "generation_error"
    assert "worker-job" in caplog.text
    assert cause in caplog.text


def test_songmaker_message_stays_with_existing_sanitizer(generation_write_failure_case, caplog):
    """S8-A; S5-B/D, L6/L10: Availability changes while other sanitization and logging survive."""
    cause, expected, error_type = generation_write_failure_case
    failure = generation_failure(cause, "own-job")
    assert failure.message.sentence() == expected
    assert failure.error_type == error_type
    assert "own-job" in caplog.text
    assert str(cause) in caplog.text


@pytest.mark.parametrize(
    ("causes", "expected_message", "error_type", "running"),
    [
        (
            (WorkerGpuOutOfMemory,),
            "Too long for the GPU right now — try a shorter duration.",
            "gpu_out_of_memory",
            True,
        ),
        (
            (WorkerGpuOutOfMemory, WorkerGenerationFailed),
            "Too long for the GPU right now — try a shorter duration.",
            "gpu_out_of_memory",
            True,
        ),
        (
            (WorkerGenerationFailed, WorkerGpuOutOfMemory),
            "Too long for the GPU right now — try a shorter duration.",
            "gpu_out_of_memory",
            True,
        ),
        (
            (WorkerGenerationUnavailable, WorkerGenerationFailed),
            "Generating failed — try again.",
            "generation_error",
            False,
        ),
        (
            (WorkerGenerationUnavailable,),
            "Generating isn't available right now.",
            "generation_unavailable",
            False,
        ),
    ],
    ids=["oom", "oom-generic", "generic-oom", "unavailable-generic", "unavailable"],
)
def test_s8_failure_selection(causes, expected_message, error_type, running, caplog):
    """S8-A/D/E: One owner logs every cause and chooses stored and running pairs."""
    selected = None
    assert running_failure_pair(selected) == (None, None)
    for index, cause in enumerate(causes):
        diagnosis = f"private worker cause {index}"
        selected = select_generation_failure(selected, cause(diagnosis), "s8-job")
        assert diagnosis in caplog.text
    assert "s8-job" in caplog.text
    assert (selected.message.sentence(), selected.error_type) == (expected_message, error_type)
    pair = running_failure_pair(selected)
    expected_pair = (expected_message, error_type) if running else (None, None)
    actual_pair = (pair[0] and pair[0].sentence(), pair[1])
    assert actual_pair == expected_pair


@pytest.mark.parametrize("reason", GENERATION_SETUP_REASONS)
def test_setup_message_stays_with_existing_sanitizer(reason):
    """L11: Setup messages retain their existing write classification."""
    failure = generation_failure(GenerationSetupError(reason), "setup-job")
    assert failure.message == reason
    assert failure.error_type == "generation_error"


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
    from songmaker_cli.api_models import JobResponse
    from songmaker_cli.db.models import Job

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
    from songmaker_cli.api_models import JobResponse
    from songmaker_cli.db.models import Job

    response = JobResponse.from_orm(Job(id="ok", type="generate", status="running", progress=0.1))
    assert (response.error, response.error_message, response.completed_takes) == (None, None, None)


def test_response_fails_loudly_for_completed_takes_without_a_take_count():
    from songmaker_cli.api_models import JobResponse
    from songmaker_cli.db.models import Job

    job = Job(
        id="broken", type="generate", status="partial", progress=0.5,
        error_message=message("jobFailure.generationFailed"), completed_takes=1,
    )
    with pytest.raises(RuntimeError, match="completed takes without a take count"):
        JobResponse.from_orm(job)

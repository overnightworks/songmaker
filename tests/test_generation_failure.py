"""Generate failure ownership without worker or database dependencies."""

import pytest
from support.generation_failures import GENERATION_SETUP_MESSAGES, OTHER_GENERATION_ERROR_TYPES

from songmaker_cli.jobs._runtime import GenerationSetupError
from songmaker_cli.jobs.generation_failure import (
    generation_failure,
    musician_error,
    partial_failure_error,
    running_failure_pair,
    select_generation_failure,
)
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
    assert failure.message == "Generating failed — try again."
    assert failure.error_type == "generation_error"
    assert "worker-job" in caplog.text
    assert cause in caplog.text


def test_songmaker_message_stays_with_existing_sanitizer(generation_write_failure_case, caplog):
    """S8-A; S5-B/D, L6/L10: Availability changes while other sanitization and logging survive."""
    cause, expected, error_type = generation_write_failure_case
    failure = generation_failure(cause, "own-job")
    assert failure.message == expected
    assert failure.error_type == error_type
    assert "own-job" in caplog.text
    assert str(cause) in caplog.text


@pytest.mark.parametrize(
    ("causes", "message", "error_type", "running"),
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
def test_s8_failure_selection(causes, message, error_type, running, caplog):
    """S8-A/D/E: One owner logs every cause and chooses stored and running pairs."""
    selected = None
    assert running_failure_pair(selected) == (None, None)
    for index, cause in enumerate(causes):
        diagnosis = f"private worker cause {index}"
        selected = select_generation_failure(selected, cause(diagnosis), "s8-job")
        assert diagnosis in caplog.text
    assert "s8-job" in caplog.text
    assert (selected.message, selected.error_type) == (message, error_type)
    assert running_failure_pair(selected) == ((message, error_type) if running else (None, None))
    assert musician_error(message, error_type) == message


@pytest.mark.parametrize(
    ("completed", "count", "message", "expected"),
    [
        (1, 2, "Generation timed out", "1/2 completed, 1 failed: Generation timed out"),
        (12, 15, "raw worker cause", "12/15 completed, 3 failed: raw worker cause"),
    ],
)
def test_partial_failure_formats_completed_and_failed_counts(completed, count, message, expected):
    """L11: Persisted partial failures retain their counts and selected cause."""
    assert partial_failure_error(completed, count, message) == expected


@pytest.mark.parametrize("prefix", ["", "1/2 completed, 1 failed: "])
def test_read_preserves_songmaker_counterexamples(generation_failure_case, prefix):
    """L11: Own causes survive both complete and partial failure reads."""
    _, expected = generation_failure_case
    assert musician_error(prefix + expected, "generation_error") == prefix + expected


@pytest.mark.parametrize(
    "message",
    GENERATION_SETUP_MESSAGES,
)
def test_setup_message_stays_with_existing_sanitizer(message):
    """L11: Setup messages retain their existing write classification."""
    failure = generation_failure(GenerationSetupError(message), "setup-job")
    assert failure.message == message
    assert failure.error_type == "generation_error"


def test_unknown_setup_message_stays_sanitized():
    """L11: Unknown setup details are still sanitized on write."""
    assert generation_failure(GenerationSetupError("private"), "setup-job").message == (
        "An unexpected error occurred"
    )


@pytest.mark.parametrize("prefix", ["", "1/2 completed, 1 failed: "])
@pytest.mark.parametrize(
    "message",
    [*GENERATION_SETUP_MESSAGES, "Generating failed — try again."],
)
def test_read_preserves_setup_and_generic_lines(message, prefix):
    """L11: The remaining owned lines survive the read projection."""
    assert musician_error(prefix + message, "generation_error") == prefix + message


@pytest.mark.parametrize(
    "error_type",
    OTHER_GENERATION_ERROR_TYPES,
)
def test_read_preserves_other_error_types(error_type):
    """L11: Projection does not reclassify other failures."""
    assert musician_error("raw cause", error_type) == "raw cause"


@pytest.mark.parametrize("error", [None, ""])
def test_read_preserves_missing_error_text(error):
    """L11: Missing text stays missing."""
    assert musician_error(error, "generation_error") == error


@pytest.mark.parametrize("prefix", ["", "1/2 completed, 1 failed: ", "12/15 completed, 3 failed: "])
@pytest.mark.parametrize("cause", ["need 18.5 GB", "generation failed (no detail from ACE-Step)"])
def test_read_replaces_unknown_cause_preserving_partial_prefix(prefix, cause):
    """L6 L11: Historical worker detail disappears, completed counts remain."""
    assert musician_error(prefix + cause, "generation_error") == (
        prefix + "Generating failed — try again."
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("x/2 completed, 1 failed: Generation timed out", "Generating failed — try again."),
        ("1/2 completed, 1 failed:Generation timed out", "Generating failed — try again."),
        ("prefix 1/2 completed, 1 failed: Generation timed out", "Generating failed — try again."),
        ("١/2 completed, 1 failed: Generation timed out", "Generating failed — try again."),
        (
            "1/2 completed, 1 failed: 1/2 completed, 1 failed: Generation timed out",
            "1/2 completed, 1 failed: Generating failed — try again.",
        ),
    ],
)
def test_read_does_not_preserve_malformed_or_nested_prefix(error, expected):
    """L6: Only one correctly formed leading ASCII partial prefix survives."""
    assert musician_error(error, "generation_error") == expected


@pytest.mark.parametrize("job_type", ["generate", "lora_training", "load_model_on_worker", "cover"])
def test_response_preserves_fields_queue_position_and_stored_error(job_type):
    """L5 L11: Only the Generate response error changes; the stored row does not."""
    from songmaker_cli.api_models import JobResponse
    from songmaker_cli.db.models import Job
    from songmaker_cli.jobs.generation_failure import musician_job_response

    job = Job(
        id="legacy",
        type=job_type,
        status="queued",
        progress=0.0,
        error="need 18.5 GB",
        error_type="generation_error",
        queue_reason="queued_full",
        take_index=1,
        take_count=2,
    )
    original = JobResponse.from_orm(job, queue_position=3).model_dump()
    expected = original | {
        "error": "Generating failed — try again." if job_type == "generate" else job.error,
    }
    assert musician_job_response(job, queue_position=3).model_dump() == expected
    assert job.error == "need 18.5 GB"
    assert job.error_type == "generation_error"


@pytest.mark.parametrize("prefix", ["", "1/2 completed, 1 failed: "])
def test_s5_response_preserves_unavailable_and_stored_row(prefix):
    """S5-C, L5/L6/L10: New availability passes reads unchanged, including partials."""
    from songmaker_cli.db.models import Job
    from songmaker_cli.jobs.generation_failure import musician_job_response

    message = prefix + "Generating isn't available right now."
    job = Job(
        id="unavailable",
        type="generate",
        status="failed",
        progress=0.0,
        error=message,
        error_type="generation_unavailable",
    )
    response = musician_job_response(job)
    assert response.error == job.error == message
    assert response.error_type == job.error_type == "generation_unavailable"

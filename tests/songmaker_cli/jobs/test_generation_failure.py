"""Generate failure ownership without worker or database dependencies."""

import pytest
from support.generation_failures import GENERATION_SETUP_REASONS

from songmaker_cli.jobs._runtime import GenerationSetupError
from songmaker_cli.jobs.generation_failure import (
    generation_failure,
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

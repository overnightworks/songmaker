"""Generate failure ownership without worker or database dependencies."""

import pytest

from acestep_engine.errors import AudioDownloadError
from songmaker_cli.jobs._runtime import GenerationSetupError
from songmaker_cli.jobs.generation_failure import generation_failure
from songmaker_cli.scheduler import (
    NoCapacityError,
    WorkerGenerationFailed,
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


@pytest.mark.parametrize(
    "cause,expected",
    [
        (AudioDownloadError("private"), "Failed to download generated audio"),
        (ConnectionError("private"), "ACE-Step server not reachable"),
        (TimeoutError("private"), "Generation timed out"),
        (NoCapacityError("private"), "No ACE-Step workers available"),
        (RuntimeError("private"), "Internal error during processing"),
        (ValueError("private"), "An unexpected error occurred"),
        (GenerationSetupError("Song not found"), "Song not found"),
        (GenerationSetupError("Version not found"), "Version not found"),
        (GenerationSetupError("Reference audio not found"), "Reference audio not found"),
        (GenerationSetupError("Selected voice is unavailable for this generation"),
         "Selected voice is unavailable for this generation"),
        (GenerationSetupError("private"), "An unexpected error occurred"),
    ],
)
def test_songmaker_message_stays_with_existing_sanitizer(cause, expected, caplog):
    """defect:#1569: Songmaker's existing sanitization and raw logging survive."""
    failure = generation_failure(cause, "own-job")
    assert failure.message == expected
    assert failure.error_type == "generation_error"
    assert "own-job" in caplog.text
    assert str(cause) in caplog.text

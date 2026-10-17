"""Own the message and classification persisted for Generate failures."""

from dataclasses import dataclass

from songmaker_cli.constants import JOB_ERROR_GENERATION_FAILED
from songmaker_cli.scheduler import WorkerTaskFailed

from ._runtime import _sanitize_error


@dataclass(frozen=True)
class GenerationFailure:
    message: str
    error_type: str


def generation_failure(exc: Exception, job_id: str) -> GenerationFailure:
    """Log the full cause and select the musician's line and its type together."""
    message = _sanitize_error(exc, job_id)
    if isinstance(exc, WorkerTaskFailed):
        message = JOB_ERROR_GENERATION_FAILED
    return GenerationFailure(message=message, error_type="generation_error")

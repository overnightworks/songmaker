"""Own persisted Generate failures and their musician-facing read projection."""

import re
from dataclasses import dataclass

from songmaker_cli.api_models import JobResponse
from songmaker_cli.constants import JOB_ERROR_GENERATION_FAILED, JobType
from songmaker_cli.db.models import Job
from songmaker_cli.scheduler import WorkerTaskFailed

from ._runtime import _sanitize_error, generation_error_messages

_PARTIAL_FAILURE_PREFIX = re.compile(r"\d+/\d+ completed, \d+ failed: ", re.ASCII)


def partial_failure_error(completed: int, count: int, message: str) -> str:
    """Format the persisted partial failure and its musician-facing cause."""
    return f"{completed}/{count} completed, {count - completed} failed: {message}"


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


def musician_error(error: str | None, error_type: str | None) -> str | None:
    """Project legacy Generate causes without changing their stored diagnosis."""
    if error_type != "generation_error" or not error:
        return error
    partial = _PARTIAL_FAILURE_PREFIX.match(error)
    prefix = partial.group() if partial else ""
    cause = error[len(prefix) :]
    if cause in generation_error_messages() | {JOB_ERROR_GENERATION_FAILED}:
        return error
    return prefix + JOB_ERROR_GENERATION_FAILED


def musician_job_response(job: Job, *, queue_position: int | None = None) -> JobResponse:
    """Serialize once, projecting only Generate errors on musician endpoints."""
    response = JobResponse.from_orm(job, queue_position=queue_position)
    if job.type == JobType.GENERATE:
        response.error = musician_error(response.error, response.error_type)
    return response

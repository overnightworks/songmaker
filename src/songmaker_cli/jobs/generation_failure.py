"""Own persisted Generate failures and their musician-facing read projection."""

import re
from dataclasses import dataclass
from typing import Final

from songmaker_cli.api_models import JobResponse
from songmaker_cli.db.models import Job
from songmaker_cli.job_types import JobType
from songmaker_cli.messages import Message, message
from songmaker_cli.scheduler import (
    NoCapacityError,
    WorkerGenerationUnavailable,
    WorkerGpuOutOfMemory,
    WorkerTaskFailed,
)

from ._runtime import _sanitize_error, generation_error_messages

GPU_OUT_OF_MEMORY: Final = "gpu_out_of_memory"

_GENERATION_FAILED: Final = message("jobFailure.generationFailed")
_GENERATION_UNAVAILABLE: Final = message("jobFailure.generationUnavailable")
_GPU_OUT_OF_MEMORY: Final = message("jobFailure.gpuOutOfMemory")
_PARTIAL_FAILURE_PREFIX = re.compile(r"\d+/\d+ completed, \d+ failed: ", re.ASCII)


def partial_failure_error(completed: int, count: int, cause: Message) -> Message:
    """The persisted partial failure: its counts and the musician-facing cause."""
    return message(
        "jobFailure.partialTakes",
        completed=str(completed),
        count=str(count),
        failed=str(count - completed),
        cause=cause.sentence(),
    )


@dataclass(frozen=True)
class GenerationFailure:
    message: Message
    error_type: str


def generation_failure(exc: Exception, job_id: str) -> GenerationFailure:
    """Log the full cause and select the musician's line and its type together."""
    failure = _sanitize_error(exc, job_id)
    if isinstance(exc, WorkerGpuOutOfMemory):
        return GenerationFailure(_GPU_OUT_OF_MEMORY, GPU_OUT_OF_MEMORY)
    if isinstance(exc, (WorkerGenerationUnavailable, NoCapacityError)):
        return GenerationFailure(_GENERATION_UNAVAILABLE, "generation_unavailable")
    if isinstance(exc, WorkerTaskFailed):
        failure = _GENERATION_FAILED
    return GenerationFailure(message=failure, error_type="generation_error")


def select_generation_failure(
    previous: GenerationFailure | None, exc: Exception, job_id: str,
) -> GenerationFailure:
    """Log each cause; GPU memory takes precedence, otherwise the latest wins."""
    current = generation_failure(exc, job_id)
    if previous is not None and previous.error_type == GPU_OUT_OF_MEMORY:
        return previous
    return current


def is_visible_generation_failure(error_type: str | None) -> bool:
    """Only typed GPU-memory failures are visible outside FAILED."""
    return error_type == GPU_OUT_OF_MEMORY


def running_failure_pair(
    failure: GenerationFailure | None,
) -> tuple[Message | None, str | None]:
    """Only a GPU-memory failure is visible before all takes finish."""
    if failure is not None and is_visible_generation_failure(failure.error_type):
        return failure.message, failure.error_type
    return None, None


def musician_error(error: str | None, error_type: str | None) -> str | None:
    """Project legacy Generate causes without changing their stored diagnosis."""
    if error_type != "generation_error" or not error:
        return error
    partial = _PARTIAL_FAILURE_PREFIX.match(error)
    prefix = partial.group() if partial else ""
    cause = error[len(prefix) :]
    generation_failed = _GENERATION_FAILED.sentence()
    if cause in generation_error_messages() | {generation_failed}:
        return error
    return prefix + generation_failed


def musician_job_response(job: Job, *, queue_position: int | None = None) -> JobResponse:
    """Serialize once, projecting only Generate errors on musician endpoints."""
    response = JobResponse.from_orm(job, queue_position=queue_position)
    if job.type == JobType.GENERATE:
        response.error = musician_error(response.error, response.error_type)
    return response

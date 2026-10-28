from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import TYPE_CHECKING, Final

from acestep_worker.clock import utcnow
from acestep_worker.last_error import LastError
from acestep_worker.model_cache import CapacityError, UnknownModeError
from acestep_worker.subprocess_runner import LmInitFailedError, SubprocessStartError

if TYPE_CHECKING:
    from acestep_worker.wrapper import WorkerDeps

log = logging.getLogger(__name__)

# EX_TEMPFAIL: neither success, a crash, a usage error nor uvicorn's startup failure,
# so a restart loop caused by the LM reads differently from every other exit.
LM_FAILURE_EXIT_CODE: Final = 75
EXIT_DELAY_SECONDS: Final = 0.1
LM_FAILURE_KEY_PREFIX: Final = "songmaker:acestep:lm-failure"


def lm_failure_key(worker_id: str) -> str:
    return f"{LM_FAILURE_KEY_PREFIX}:{worker_id}"


def schedule_sigterm() -> int:
    """Ask this process to shut down once the current response is out; returns its pid."""
    pid = os.getpid()
    asyncio.get_running_loop().call_later(EXIT_DELAY_SECONDS, lambda: os.kill(pid, signal.SIGTERM))
    return pid


async def leave_if_lm_failed(deps: WorkerDeps, mode: str, error: SubprocessStartError) -> None:
    """After an LM failure, remember the mode and end the process so a restart retries it."""
    if not isinstance(error, LmInitFailedError):
        return
    try:
        await deps.redis.set(lm_failure_key(deps.worker_id), mode)
    except Exception:
        log.exception("Could not record the LM failure for %s; leaving anyway", mode)
    log.error("ACE-Step LM did not initialise for %s; ending the worker to retry", mode)
    # Stopping the children ends running takes now instead of when their streams finish.
    await deps.cache.evict_all()
    deps.request_shutdown(LM_FAILURE_EXIT_CODE)


async def retry_failed_load(deps: WorkerDeps) -> None:
    """Load the mode whose LM failed before the last exit, ahead of registration and heartbeat.

    An LM failure again propagates and fails the start with the key kept; any other failure is
    one a restart cannot fix, so the key is cleared and the worker starts empty.
    """
    key = lm_failure_key(deps.worker_id)
    raw_mode = await deps.redis.get(key)
    if raw_mode is None:
        return
    mode = raw_mode.decode()
    try:
        await deps.cache.load(mode)
    except LmInitFailedError:
        log.exception("ACE-Step LM failed again for %s; the start fails", mode)
        raise
    except (SubprocessStartError, CapacityError, UnknownModeError, OSError) as exc:
        deps.last_error = LastError(str(exc), utcnow())
        log.exception("Retry of the failed %s load failed for another reason; starting empty", mode)
    await deps.redis.delete(key)

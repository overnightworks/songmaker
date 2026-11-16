"""Redis read/write helpers for ACE-Step worker ephemeral state.

Workers publish their loaded models, queue depth, and VRAM usage to Redis
with a 15s TTL via ``acestep_worker.heartbeat``. The web container reads
that state through these helpers when assembling the admin Worker Pool view.

The key prefixes here MUST stay in sync with ``acestep_worker.heartbeat`` and
``acestep_worker.lm_failure``;
see ``tests/songmaker_cli/test_acestep_state.py`` for the cross-package assertion.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from arq.connections import ArqRedis
from redis.exceptions import RedisError
from tandem import Liveness, Locks, Script, StoreError

from songmaker_cli.constants import REDIS_KEY_PREFIX

log = logging.getLogger(__name__)

WORKER_KEY_PREFIX = "songmaker:acestep:worker"
QUEUE_KEY_PREFIX = "songmaker:acestep:queue"
DOWNLOAD_KEY_PREFIX = "songmaker:acestep:download"
LM_FAILURE_KEY_PREFIX = "songmaker:acestep:lm-failure"
GPU_HOLD_OLD_KEY_PREFIX = "songmaker:acestep:hold"
GPU_HOLD_FAMILY = "gpu"
GPU_HOLD_LASTS = timedelta(seconds=15)
DOWNLOAD_LOCK_FAMILY = "download"
# The holder extends the lock while it downloads, so a crashed holder frees the mode after one
# span; the same span bounds how long a download waits after a Redis restart.
DOWNLOAD_LOCK_LASTS = timedelta(seconds=15)
DOWNLOAD_LOCK_EXTEND_EVERY = timedelta(seconds=5)
DOWNLOAD_LOCK_POLL_SECONDS = 1.0

# KEYS: the queue depth, then the GPU holds' epoch, expiry and generation keys, then the old hold
# key; ARGV: the lock span in ms and the worker id. A hold, or a restart that may have lost one,
# refuses the admission.
ADMIT_GENERATION_SCRIPT = """
local keys = {epoch = KEYS[2], expiry = KEYS[3], generation = KEYS[4]}
if tandem.lock_state(keys, ARGV[2], ARGV[1]) then return 0 end
if redis.call('EXISTS', KEYS[5]) == 1 then return 0 end
redis.call('INCR', KEYS[1])
return 1
"""


def worker_state_key(worker_id: str) -> str:
    return f"{WORKER_KEY_PREFIX}:{worker_id}"


def queue_depth_key(worker_id: str) -> str:
    return f"{QUEUE_KEY_PREFIX}:{worker_id}"


def gpu_hold_old_key(worker_id: str) -> str:
    """The key the previous release holds for a worker's GPU hold; the worker writes it beside the
    lock for one release, so a reader of either release sees a hold of the other.

    ``acestep_worker.heartbeat`` builds the same key.
    """
    return f"{GPU_HOLD_OLD_KEY_PREFIX}:{worker_id}"


def gpu_hold_locks(pool: ArqRedis) -> Locks:
    """The GPU holds of the workers, one lock per worker id; the worker takes and renews them.

    ``acestep_worker.heartbeat`` builds the same family.
    """
    return Locks(
        pool, key_prefix=REDIS_KEY_PREFIX, family=GPU_HOLD_FAMILY, lasts=GPU_HOLD_LASTS,
    )


async def gpu_hold_is_free(pool: ArqRedis, worker_id: str) -> bool:
    """Whether no hold is live and none can have been lost to a Redis restart."""
    state = await gpu_hold_locks(pool).state(worker_id)
    return state.liveness is Liveness.GONE and not await pool.exists(gpu_hold_old_key(worker_id))


def download_key(mode: str) -> str:
    return f"{DOWNLOAD_KEY_PREFIX}:{mode}"


def lm_failure_key(worker_id: str) -> str:
    return f"{LM_FAILURE_KEY_PREFIX}:{worker_id}"


def decode_redis_text(raw: bytes | str | None) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode()
    return raw


async def read_worker_state(pool: ArqRedis, worker_id: str) -> dict[str, Any] | None:
    raw = await pool.get(worker_state_key(worker_id))
    text = decode_redis_text(raw)
    if text is None:
        return None
    return json.loads(text)


async def worker_lm_failed(pool: ArqRedis, worker_id: str) -> bool:
    """Whether the worker's last start failed on the LM; only the key's existence counts."""
    return bool(await pool.exists(lm_failure_key(worker_id)))


def worker_is_online(state: Mapping[str, Any] | None) -> bool:
    """The one place that answers "does this worker take jobs right now?"

    A worker whose GPU has gone away (NVML present but unreachable — a
    driver/GPU mismatch, a vanished device) keeps heartbeating fine, so
    heartbeat presence alone is not enough (issue #367); it must also report
    ``gpu_healthy: true``. Fail-closed on purpose: a heartbeat missing the
    ``gpu_healthy`` key entirely — an old or broken worker build that never
    learned to publish it — counts as not online, never as a silent "assume
    fine forever". This is a single-host deployment where every container is
    rebuilt in one `docker compose up --build`; the mixed-version window a
    lenient default would have covered is seconds on the first deploy after
    this change, not an ongoing state worth trusting indefinitely.

    Every caller that decides "is this worker available" (``/health``,
    ``/metrics``, the scheduler's own worker picker, the generate/repaint/
    cover preflight, the admin worker pool and model registry) must go
    through this function, not re-read the heartbeat dict itself, so the
    definition of "online" cannot drift between them.
    """
    return state is not None and state.get("gpu_healthy") is True


async def read_queue_depth(pool: ArqRedis, worker_id: str) -> int:
    raw = await pool.get(queue_depth_key(worker_id))
    text = decode_redis_text(raw)
    return int(text) if text is not None else 0


async def decr_queue_depth(pool: ArqRedis, worker_id: str) -> int:
    return await pool.decr(queue_depth_key(worker_id))


async def admit_generation(pool: ArqRedis, worker_id: str) -> bool:
    locks = gpu_hold_locks(pool)
    result = await Script(pool, ADMIT_GENERATION_SCRIPT).run(
        [
            queue_depth_key(worker_id),
            locks.keys.epoch,
            locks.keys.expiry,
            locks.keys.generation,
            gpu_hold_old_key(worker_id),
        ],
        [int(locks.lasts.total_seconds() * 1000), worker_id],
    )
    return bool(result)


def download_locks(pool: ArqRedis) -> Locks:
    """The single-flight locks of the model downloads, one lock per mode."""
    return Locks(
        pool, key_prefix=REDIS_KEY_PREFIX, family=DOWNLOAD_LOCK_FAMILY, lasts=DOWNLOAD_LOCK_LASTS,
    )


class DownloadAlreadyRunning(Exception):
    """Another job holds the download lock of the mode; ``job_id`` is its label, when it has one."""

    def __init__(self, job_id: str | None) -> None:
        super().__init__(job_id)
        self.job_id = job_id


async def read_download_in_progress(pool: ArqRedis, mode: str) -> str | None:
    """The job that downloads ``mode``, from the label its holder keeps beside the lock.

    A lock names no holder, so the holder writes its job id under ``download_key`` for as long as
    it extends the lock. The label also reads as in progress for a holder of the previous release,
    which wrote the same key.
    """
    raw = await pool.get(download_key(mode))
    return decode_redis_text(raw)


async def _acquire_download_lock(pool: ArqRedis, locks: Locks, mode: str) -> str:
    """The generation of the lock; a Redis restart is waited out, a live holder is refused."""
    attempts = int(DOWNLOAD_LOCK_LASTS.total_seconds() / DOWNLOAD_LOCK_POLL_SECONDS) + 2
    for _ in range(attempts):
        generation = await locks.acquire(mode)
        if generation is not None:
            return generation
        if (await locks.state(mode)).liveness is Liveness.ALIVE:
            raise DownloadAlreadyRunning(await read_download_in_progress(pool, mode))
        await asyncio.sleep(DOWNLOAD_LOCK_POLL_SECONDS)
    raise RuntimeError(f"The download lock of {mode} stayed unsettled after a Redis restart")


async def _keep_download_lock(
    pool: ArqRedis, locks: Locks, mode: str, job_id: str, generation: str,
) -> None:
    """Extend the lock and its label until cancelled; stop when the lock is lost."""
    label_seconds = int(DOWNLOAD_LOCK_LASTS.total_seconds())
    while True:
        await asyncio.sleep(DOWNLOAD_LOCK_EXTEND_EVERY.total_seconds())
        try:
            if not await locks.extend(mode, generation):
                log.warning("The download lock of %s was lost during its download", mode)
                return
            await pool.set(download_key(mode), job_id, ex=label_seconds)
        except (StoreError, RedisError):
            log.warning("Could not extend the download lock of %s", mode, exc_info=True)


@asynccontextmanager
async def single_flight_download(pool: ArqRedis, mode: str, job_id: str) -> AsyncIterator[None]:
    """Hold the download lock of ``mode`` for the block, or raise ``DownloadAlreadyRunning``."""
    locks = download_locks(pool)
    generation = await _acquire_download_lock(pool, locks, mode)
    keeper = asyncio.create_task(_keep_download_lock(pool, locks, mode, job_id, generation))
    try:
        await pool.set(
            download_key(mode), job_id, ex=int(DOWNLOAD_LOCK_LASTS.total_seconds()),
        )
        yield
    finally:
        keeper.cancel()
        await asyncio.gather(keeper, return_exceptions=True)
        await pool.delete(download_key(mode))
        await locks.release(mode, generation)

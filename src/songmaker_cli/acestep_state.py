"""Redis read/write helpers for ACE-Step worker ephemeral state.

Workers publish their loaded models, queue depth, and VRAM usage to Redis
with a 15s TTL via ``songmaker_acestep_worker.heartbeat``. The web container reads
that state through these helpers when assembling the admin Worker Pool view.

The key prefixes here MUST stay in sync with ``songmaker_acestep_worker.heartbeat`` and
``songmaker_acestep_worker.lm_failure``;
see ``tests/songmaker_cli/test_acestep_state.py`` for the cross-package assertion.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Collection, Mapping
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, cast

from redis import Redis as SyncRedis
from redis.asyncio import Redis
from tandem import Liveness, LockLost, Locks, Script

from songmaker_cli.constants import REDIS_KEY_PREFIX

WORKER_KEY_PREFIX = "songmaker:acestep:worker"
ADMITTED_KEY_PREFIX = "songmaker:acestep:admitted"
DOWNLOAD_KEY_PREFIX = "songmaker:acestep:download"
LM_FAILURE_KEY_PREFIX = "songmaker:acestep:lm-failure"
GPU_HOLD_FAMILY = "gpu"
GPU_HOLD_LASTS = timedelta(seconds=15)
DOWNLOAD_LOCK_FAMILY = "download"
# The holder extends the lock while it downloads, so a crashed holder frees the mode after one
# span; the same span bounds how long a download waits after a Redis restart.
DOWNLOAD_LOCK_LASTS = timedelta(seconds=15)
DOWNLOAD_LOCK_EXTEND_EVERY = timedelta(seconds=5)
DOWNLOAD_LOCK_POLL_SECONDS = 1.0

# KEYS: the admitted job ids, then the GPU holds' epoch, expiry and generation keys; ARGV: the lock
# span in ms, the worker id and the job id. A hold, or a restart that may have lost one, refuses
# the admission.
ADMIT_GENERATION_SCRIPT = """
local keys = {epoch = KEYS[2], expiry = KEYS[3], generation = KEYS[4]}
if tandem.lock_state(keys, ARGV[2], ARGV[1]) then return 0 end
redis.call('SADD', KEYS[1], ARGV[3])
return 1
"""


def worker_state_key(worker_id: str) -> str:
    return f"{WORKER_KEY_PREFIX}:{worker_id}"


def admitted_key(worker_id: str) -> str:
    """The set of job ids admitted on the worker; its size is the worker's queue depth."""
    return f"{ADMITTED_KEY_PREFIX}:{worker_id}"


def gpu_hold_locks(pool: Redis) -> Locks:
    """The GPU holds of the workers, one lock per worker id; the worker takes and renews them.

    ``songmaker_acestep_worker.heartbeat`` builds the same family.
    """
    return Locks(
        pool, key_prefix=REDIS_KEY_PREFIX, family=GPU_HOLD_FAMILY, lasts=GPU_HOLD_LASTS,
    )


async def gpu_hold_is_free(pool: Redis, worker_id: str) -> bool:
    """Whether no hold is live and none can have been lost to a Redis restart."""
    state = await gpu_hold_locks(pool).state(worker_id)
    return state.liveness is Liveness.GONE


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


async def read_worker_state(pool: Redis, worker_id: str) -> dict[str, Any] | None:
    raw = await pool.get(worker_state_key(worker_id))
    text = decode_redis_text(raw)
    if text is None:
        return None
    return json.loads(text)


async def worker_lm_failed(pool: Redis, worker_id: str) -> bool:
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


async def read_queue_depth(pool: Redis, worker_id: str) -> int:
    return await pool.scard(admitted_key(worker_id))


async def release_admission(pool: Redis, worker_id: str, job_id: str) -> None:
    await pool.srem(admitted_key(worker_id), job_id)


def remove_admissions_of_ended_jobs(
    redis: SyncRedis,
    worker_id: str,
    ended_among: Callable[[Collection[str]], Collection[str]],
) -> int:
    """Remove the worker's admitted job ids that ``ended_among`` names; returns how many.

    Only those ids are removed, never the set rewritten, so an admission made after the read stays.
    The removal is idempotent: the job's own release may remove the same id.
    """
    key = admitted_key(worker_id)
    raw_ids = cast("set[bytes | str]", redis.smembers(key))
    admitted = {cast("str", decode_redis_text(raw)) for raw in raw_ids}
    ended = list(ended_among(admitted)) if admitted else []
    if ended:
        redis.srem(key, *ended)
    return len(ended)


async def admit_generation(pool: Redis, worker_id: str, job_id: str) -> bool:
    locks = gpu_hold_locks(pool)
    result = await Script(pool, ADMIT_GENERATION_SCRIPT).run(
        [
            admitted_key(worker_id),
            locks.keys.epoch,
            locks.keys.expiry,
            locks.keys.generation,
        ],
        [int(locks.lasts.total_seconds() * 1000), worker_id, job_id],
    )
    return bool(result)


def download_locks(pool: Redis) -> Locks:
    """The single-flight locks of the model downloads, one lock per mode."""
    return Locks(
        pool, key_prefix=REDIS_KEY_PREFIX, family=DOWNLOAD_LOCK_FAMILY, lasts=DOWNLOAD_LOCK_LASTS,
    )


class DownloadAlreadyRunning(Exception):
    """Another job holds the download lock of the mode; ``job_id`` is its label, when it has one."""

    def __init__(self, job_id: str | None) -> None:
        super().__init__(job_id)
        self.job_id = job_id


# KEYS: the label, then the download locks' epoch, expiry and generation keys; ARGV: the lock span
# in ms and the mode. Replies {'held', label or nil} while the lock is held, {'unknown'} while a
# Redis restart may have lost it, else {'free'}.
READ_DOWNLOAD_STATE_SCRIPT = """
local keys = {epoch = KEYS[2], expiry = KEYS[3], generation = KEYS[4]}
local state = tandem.lock_state(keys, ARGV[2], ARGV[1])
if not state then return {'free'} end
if state[1] == 'held' then return {'held', redis.call('GET', KEYS[1])} end
return {'unknown'}
"""
_LIVENESS_OF_REPLY = {
    "held": Liveness.ALIVE, "unknown": Liveness.UNKNOWN, "free": Liveness.GONE,
}


async def _read_download_state(pool: Redis, mode: str) -> tuple[Liveness, str | None]:
    """The liveness of the mode's lock and, while it is held, the label beside it, in one read."""
    locks = download_locks(pool)
    reply = cast(
        "list[bytes | str | None]",
        await Script(pool, READ_DOWNLOAD_STATE_SCRIPT).run(
            [download_key(mode), locks.keys.epoch, locks.keys.expiry, locks.keys.generation],
            [int(locks.lasts.total_seconds() * 1000), mode],
        ),
    )
    liveness = _LIVENESS_OF_REPLY[cast("str", decode_redis_text(reply[0]))]
    label = decode_redis_text(reply[1]) if liveness is Liveness.ALIVE else None
    return liveness, label


async def read_download_in_progress(pool: Redis, mode: str) -> str | None:
    """The job that downloads ``mode``: its holder's label, read only while the lock is held.

    A lock names no holder, so the holder writes its job id under ``download_key`` as the first
    statement of its hold and deletes it after the hold ends. A label whose lock is free or unknown
    is a crashed holder's and means nothing; the next holder overwrites it.
    """
    return (await _read_download_state(pool, mode))[1]


async def _acquire_download_lock(pool: Redis, locks: Locks, mode: str) -> str:
    """The generation of the lock; a Redis restart is waited out, a live holder is refused."""
    attempts = int(DOWNLOAD_LOCK_LASTS.total_seconds() / DOWNLOAD_LOCK_POLL_SECONDS) + 2
    for _ in range(attempts):
        generation = await locks.acquire(mode)
        if generation is not None:
            return generation
        liveness, label = await _read_download_state(pool, mode)
        if liveness is Liveness.ALIVE:
            raise DownloadAlreadyRunning(label)
        await asyncio.sleep(DOWNLOAD_LOCK_POLL_SECONDS)
    raise RuntimeError(f"The download lock of {mode} stayed unsettled after a Redis restart")


class DownloadLockLost(Exception):
    """The download lock of ``mode`` ended under its holder, so another job may download it now."""

    def __init__(self, mode: str) -> None:
        super().__init__(mode)
        self.mode = mode


# Deletes the label only while it still names the job that wrote it.
DELETE_DOWNLOAD_LABEL_SCRIPT = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
return redis.call('DEL', KEYS[1])
"""


@asynccontextmanager
async def single_flight_download(pool: Redis, mode: str, job_id: str) -> AsyncIterator[None]:
    """Hold the download lock of ``mode`` for the block, or raise ``DownloadAlreadyRunning``.

    tandem keeps the lock while the block runs. A block whose lock is lost is cancelled and raises
    ``DownloadLockLost``, leaving the lock and the label to the job that holds them now. The
    transfer already running on the ACE-Step worker is not cancelled; the worker joins the next
    download of the mode to it.

    The label is written without expiry as the first statement of the hold, so a lock that was
    lost at the entry leaves none, and deleted after the hold has ended, never inside it: after a
    loss tandem cancels the block repeatedly until it ends, which could cut a delete inside.
    """
    locks = download_locks(pool)
    generation = await _acquire_download_lock(pool, locks, mode)
    try:
        async with locks.held(mode, generation, every=DOWNLOAD_LOCK_EXTEND_EVERY):
            await pool.set(download_key(mode), job_id)
            yield
    except LockLost:
        raise DownloadLockLost(mode) from None
    finally:
        await pool.eval(DELETE_DOWNLOAD_LABEL_SCRIPT, 1, download_key(mode), job_id)

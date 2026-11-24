"""Worker-liveness readers and job-type policy shared by reapers."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Collection, Iterable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, NamedTuple

from redis import Redis
from redis.exceptions import RedisError
from tandem import Client, Hold, Leases, LeaseState, Liveness, Roster, StoreError

from songmaker_cli.acestep_state import decode_redis_text, worker_is_online, worker_state_key
from songmaker_cli.constants import REDIS_KEY_PREFIX, WORKER_LAST_ALIVE_TTL_SECONDS
from songmaker_cli.job_timing import (
    OWNER_LAPSE_CLAIM_SECONDS,
    OWNER_LEASE_REFRESH_SECONDS,
    OWNER_LEASE_TTL_SECONDS,
    worker_restart_grace_seconds,
)
from songmaker_cli.job_types import JobType, WorkerLivenessSignal
from songmaker_cli.timestamps import aware_timestamp, utcnow

log = logging.getLogger(__name__)

_PROCESS_STARTED_AT = utcnow()
OWNER_LEASE_FAMILY = "owner"
PID_ONE_STAT_FILE = Path("/proc/1/stat")
_START_TICKS_FIELD = 22
_FIELDS_BEFORE_COMMAND_END = 2


class WorkerLiveness(StrEnum):
    ALIVE = "alive"
    DEAD = "dead"
    UNKNOWN = "unknown"


def _last_alive_key(signal: str) -> str:
    return f"{REDIS_KEY_PREFIX}:worker_liveness:last_alive:{signal}"


ACESTEP_LAST_ALIVE_KEY = _last_alive_key("acestep")


class WorkerKind(NamedTuple):
    """What a kind of worker that holds a lease in its own family persists in Redis."""

    lease_family: str
    last_alive_key: str


WORKER_KINDS: Final[Mapping[WorkerLivenessSignal, WorkerKind]] = {
    WorkerLivenessSignal.MUSIC: WorkerKind("music-worker", _last_alive_key("music")),
    WorkerLivenessSignal.SCORING: WorkerKind("scoring-worker", _last_alive_key("scoring")),
}
"""The one table of worker kinds. A signal without a row has no worker of its own."""


def _leases(redis: Client, family: str) -> Leases:
    return Leases(
        redis,
        key_prefix=REDIS_KEY_PREFIX,
        family=family,
        lasts=timedelta(seconds=OWNER_LEASE_TTL_SECONDS),
        claim_for=timedelta(seconds=OWNER_LAPSE_CLAIM_SECONDS),
    )


def owner_leases(redis: Client) -> Leases:
    """The leases of the processes that run jobs, one family shared by web and worker.

    Every process builds them from the same spans: a lease and a claim are measured by the
    process that reads them.
    """
    return _leases(redis, OWNER_LEASE_FAMILY)


def worker_kind_leases(redis: Client, kind: WorkerLivenessSignal) -> Leases:
    """The leases of the workers of one kind, held by no web process.

    The owner family holds the ids of web processes too, so its roster cannot say that a worker
    of this kind lives; this family's roster can. A signal without a row in ``WORKER_KINDS``
    raises ``KeyError``.
    """
    return _leases(redis, WORKER_KINDS[kind].lease_family)


def every_worker_kind_leases(redis: Client) -> dict[WorkerLivenessSignal, Leases]:
    """The leases of every worker kind, by kind."""
    return {kind: worker_kind_leases(redis, kind) for kind in WORKER_KINDS}


async def read_kind_roster(kind: WorkerLivenessSignal, leases: Leases) -> Roster | None:
    """The live workers of one kind, or none when Redis cannot be read."""
    try:
        return await leases.live()
    except StoreError:
        log.warning("Could not read the %s worker roster", kind, exc_info=True)
        return None


async def read_kind_rosters(
    kind_leases: Mapping[WorkerLivenessSignal, Leases],
) -> dict[WorkerLivenessSignal, Roster | None]:
    """The roster of every kind in ``kind_leases``; none for a kind whose read failed."""
    return {kind: await read_kind_roster(kind, leases) for kind, leases in kind_leases.items()}


class JobOwnerStamp(NamedTuple):
    """What a job row stores of its owner: the process and the lease generation it held."""

    owner_id: str
    generation: str | None
    """``None`` on a row written before generations were stored."""


@dataclass(frozen=True)
class JobOwner:
    """A process that runs jobs: its id and the lease it holds, whose generation may change."""

    owner_id: str
    hold: Hold

    @property
    def generation(self) -> str:
        return self.hold.generation


async def owner_lease_liveness(
    leases: Leases, stamps: Collection[JobOwnerStamp],
) -> dict[JobOwnerStamp, Liveness]:
    """Whether the lease each stamp names is live, gone or possibly lost with a Redis restart.

    A lease that lapsed and started anew is a different generation: a stamp of the lapsed one
    reads GONE although its owner lives. A stamp without a generation, or an owner whose lease
    state names none, reads as its owner does.
    """
    states = await leases.state({stamp.owner_id for stamp in stamps})
    return {stamp: _liveness_of_stamp(stamp, states[stamp.owner_id]) for stamp in stamps}


def _liveness_of_stamp(stamp: JobOwnerStamp, state: LeaseState) -> Liveness:
    if state.liveness is not Liveness.ALIVE:
        return state.liveness
    if stamp.generation is None or state.generation is None:
        return Liveness.ALIVE
    return Liveness.ALIVE if stamp.generation == state.generation else Liveness.GONE


@asynccontextmanager
async def keep_owner_lease(
    leases: Leases,
    owner_id: str,
    *,
    on_new_start: Callable[[], Awaitable[None]] | None = None,
    every: timedelta = timedelta(seconds=OWNER_LEASE_REFRESH_SECONDS),
) -> AsyncIterator[JobOwner]:
    """Hold the lease of ``owner_id`` for the block, renewed every ``every``, and yield the owner.

    A lease that cannot be started fails the entry. One that cannot be ended because Redis
    is unreachable is left to lapse by itself, so a process always shuts down. When the lease
    lapsed and started again, its generation changes: that counts as a start, because another
    process may have failed the jobs this one still runs. It is logged and ``on_new_start``
    runs.
    """
    ending = AsyncExitStack()
    hold = await ending.enter_async_context(leases.kept(owner_id, every=every))
    watching = asyncio.create_task(
        _treat_a_new_generation_as_a_start(hold, owner_id, on_new_start, every),
    )
    try:
        yield JobOwner(owner_id, hold)
    finally:
        watching.cancel()
        try:
            await ending.aclose()
        except StoreError:
            log.warning("Could not end the owner lease; it lapses by itself", exc_info=True)
        finally:
            await asyncio.gather(watching, return_exceptions=True)


@asynccontextmanager
async def keep_kind_lease(
    leases: Leases,
    holder: str,
    *,
    every: timedelta = timedelta(seconds=OWNER_LEASE_REFRESH_SECONDS),
) -> AsyncIterator[None]:
    """Hold the lease of ``holder`` in a worker-kind family for the block, renewed every ``every``.

    A lease that cannot be started fails the entry; one that cannot be ended because Redis is
    unreachable lapses by itself, so a process always shuts down.
    """
    ending = AsyncExitStack()
    await ending.enter_async_context(leases.kept(holder, every=every))
    try:
        yield
    finally:
        try:
            await ending.aclose()
        except StoreError:
            log.warning("Could not end the lease of %s; it lapses by itself", holder, exc_info=True)


async def _treat_a_new_generation_as_a_start(
    hold: Hold,
    owner_id: str,
    on_new_start: Callable[[], Awaitable[None]] | None,
    every: timedelta,
) -> None:
    known = hold.generation
    while True:
        await asyncio.sleep(every.total_seconds())
        if hold.generation == known:
            continue
        known = hold.generation
        log.warning("The owner lease of %s started anew; its jobs may have been failed", owner_id)
        if on_new_start is None:
            continue
        try:
            await on_new_start()
        except Exception:
            log.exception("Could not reconcile the jobs of %s after a new start", owner_id)


def pid_one_start_ticks(stat_file: Path = PID_ONE_STAT_FILE) -> str:
    """When PID 1 started, in clock ticks after the machine booted: field 22 of its stat file.

    A container that restarts gets a new PID 1, so the value names one start of the container.
    The command name (field 2) may hold spaces and parentheses; the fields after it follow its
    last closing parenthesis.
    """
    after_command = stat_file.read_text().rpartition(")")[2].split()
    return after_command[_START_TICKS_FIELD - _FIELDS_BEFORE_COMMAND_END - 1]


def write_readiness_file(readiness_file: Path, owner_id: str, start_ticks: str) -> None:
    """Record this start's owner id and PID 1's start ticks in one atomic write."""
    pending = readiness_file.with_name(f"{readiness_file.name}.{os.getpid()}.pending")
    pending.write_text(f"{owner_id} {start_ticks}")
    os.replace(pending, readiness_file)


async def worker_is_ready(
    leases: Leases, readiness_file: Path, start_ticks: str,
) -> bool:
    """Whether this container start's worker holds a live owner lease.

    The file names the owner id and the PID 1 start ticks of the start that wrote it. After a
    container restart, its lease may still live for its lifetime, so a file written by an
    earlier start, which carries other ticks, is not ready.
    """
    try:
        owner_id, written_ticks = readiness_file.read_text().split()
    except (OSError, ValueError):
        return False
    if written_ticks != start_ticks:
        return False
    return (await leases.state({owner_id}))[owner_id].liveness is Liveness.ALIVE


def _record_alive(redis: Any, key: str, now: datetime) -> None:
    try:
        redis.set(key, now.isoformat(), ex=WORKER_LAST_ALIVE_TTL_SECONDS)
    except RedisError:
        log.warning("Could not persist worker liveness", exc_info=True)


def _missing_signal_liveness(
    redis: Any,
    last_alive_key: str,
    signal: WorkerLivenessSignal,
    now: datetime,
) -> WorkerLiveness:
    """Classify a missing signal from its durable observation and observer age."""
    try:
        raw_seen_at = redis.get(last_alive_key)
        seen_at = decode_redis_text(raw_seen_at)
        if seen_at is None:
            return WorkerLiveness.UNKNOWN
        last_alive_at = datetime.fromisoformat(seen_at)
    except (RedisError, TypeError, ValueError):
        log.warning("Could not read worker liveness", exc_info=True)
        return WorkerLiveness.UNKNOWN
    grace = timedelta(seconds=worker_restart_grace_seconds(signal))
    now = aware_timestamp(now)
    if now - aware_timestamp(last_alive_at) <= grace:
        return WorkerLiveness.ALIVE
    if now - _PROCESS_STARTED_AT > grace:
        return WorkerLiveness.DEAD
    return WorkerLiveness.ALIVE


def acestep_worker_liveness(
    redis: Any,
    worker_ids: Iterable[str],
    *,
    now: datetime,
) -> WorkerLiveness:
    """Read ACE-Step workers and fall back to their durable observation."""
    worker_ids = tuple(worker_ids)
    malformed_state = False
    for worker_id in worker_ids:
        try:
            raw_state = redis.get(worker_state_key(worker_id))
        except RedisError:
            log.warning("Could not read ACE-Step worker liveness", exc_info=True)
            return WorkerLiveness.UNKNOWN
        try:
            state = decode_redis_text(raw_state)
            if state is None:
                continue
            parsed_state = json.loads(state)
        except (TypeError, ValueError):
            log.warning("Could not decode ACE-Step worker liveness", exc_info=True)
            malformed_state = True
            continue
        if not isinstance(parsed_state, Mapping):
            log.warning("Could not decode ACE-Step worker liveness: expected an object")
            malformed_state = True
            continue
        if worker_is_online(parsed_state):
            _record_alive(redis, ACESTEP_LAST_ALIVE_KEY, aware_timestamp(now))
            return WorkerLiveness.ALIVE
    if malformed_state:
        return WorkerLiveness.UNKNOWN
    return _missing_signal_liveness(
        redis, ACESTEP_LAST_ALIVE_KEY, WorkerLivenessSignal.MODEL_EXECUTION, aware_timestamp(now),
    )


def worker_kind_liveness(
    redis: Redis, kind: WorkerLivenessSignal, roster: Roster | None, *, now: datetime,
) -> WorkerLiveness:
    """Read the roster of one worker kind and fall back to its durable observation.

    A roster that cannot be read, and an empty one Redis may have lost with a restart, are
    UNKNOWN; an empty roster that is complete follows the restart grace.
    """
    if roster is None:
        return WorkerLiveness.UNKNOWN
    last_alive_key = WORKER_KINDS[kind].last_alive_key
    if roster.holders:
        _record_alive(redis, last_alive_key, aware_timestamp(now))
        return WorkerLiveness.ALIVE
    if not roster.settled:
        return WorkerLiveness.UNKNOWN
    return _missing_signal_liveness(redis, last_alive_key, kind, aware_timestamp(now))


def read_worker_liveness(
    redis: Any,
    acestep_worker_ids: Iterable[str],
    *,
    rosters: Mapping[WorkerLivenessSignal, Roster | None],
    now: datetime | None = None,
) -> dict[JobType, WorkerLiveness]:
    """Read each execution signal without taking ownership of database access.

    The async callers read the rosters first (``read_kind_rosters``) and pass them in; a kind
    without a roster reads like one that could not be read.
    """
    observed_at = aware_timestamp(now or utcnow())
    return worker_liveness_by_job_type(
        acestep=acestep_worker_liveness(redis, acestep_worker_ids, now=observed_at),
        music=worker_kind_liveness(
            redis, WorkerLivenessSignal.MUSIC, rosters.get(WorkerLivenessSignal.MUSIC),
            now=observed_at,
        ),
        scoring=worker_kind_liveness(
            redis, WorkerLivenessSignal.SCORING, rosters.get(WorkerLivenessSignal.SCORING),
            now=observed_at,
        ),
    )


def worker_liveness_by_job_type(
    *,
    acestep: WorkerLiveness,
    music: WorkerLiveness,
    scoring: WorkerLiveness,
) -> dict[JobType, WorkerLiveness]:
    """Return each job's execution signal for its configured execution owner."""
    model_execution = _model_execution_liveness(acestep, music)
    return {
        JobType.COVER: WorkerLiveness.UNKNOWN,
        JobType.GENERATE: model_execution,
        JobType.LOAD_MODEL_ON_WORKER: model_execution,
        JobType.DOWNLOAD_MODEL_ON_WORKER: model_execution,
        JobType.LORA_TRAINING: music,
        JobType.SCORE: scoring,
        JobType.CHAT: WorkerLiveness.UNKNOWN,
    }


def _model_execution_liveness(
    acestep: WorkerLiveness,
    music: WorkerLiveness,
) -> WorkerLiveness:
    if acestep is WorkerLiveness.DEAD or music is WorkerLiveness.DEAD:
        return WorkerLiveness.DEAD
    if acestep is WorkerLiveness.ALIVE and music is WorkerLiveness.ALIVE:
        return WorkerLiveness.ALIVE
    return WorkerLiveness.UNKNOWN


def liveness_for_job_type(
    job_type: JobType,
    liveness_by_type: Mapping[JobType, WorkerLiveness] | None,
) -> WorkerLiveness:
    if liveness_by_type is None:
        return WorkerLiveness.UNKNOWN
    return liveness_by_type.get(job_type, WorkerLiveness.UNKNOWN)

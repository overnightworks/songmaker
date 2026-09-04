"""Worker-liveness readers and job-type policy shared by reapers."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

from redis.exceptions import RedisError

from songmaker_cli.acestep_state import decode_redis_text, worker_is_online, worker_state_key
from songmaker_cli.constants import (
    ARQ_MUSIC_HEALTH_KEY,
    ARQ_SCORING_HEALTH_KEY,
    REDIS_KEY_PREFIX,
    WORKER_LAST_ALIVE_TTL_SECONDS,
    JobType,
    WorkerLivenessSignal,
    worker_restart_grace_seconds,
)

log = logging.getLogger(__name__)

_PROCESS_STARTED_AT = datetime.now(timezone.utc)


class WorkerLiveness(StrEnum):
    ALIVE = "alive"
    DEAD = "dead"
    UNKNOWN = "unknown"


def _last_alive_key(signal: str) -> str:
    return f"{REDIS_KEY_PREFIX}:worker_liveness:last_alive:{signal}"


ACESTEP_LAST_ALIVE_KEY = _last_alive_key("acestep")
MUSIC_LAST_ALIVE_KEY = _last_alive_key("music")
SCORING_LAST_ALIVE_KEY = _last_alive_key("scoring")


def _as_utc(now: datetime) -> datetime:
    return now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)


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
    except (RedisError, UnicodeDecodeError, TypeError, ValueError):
        log.warning("Could not read worker liveness", exc_info=True)
        return WorkerLiveness.UNKNOWN
    grace = timedelta(seconds=worker_restart_grace_seconds(signal))
    now = _as_utc(now)
    if now - _as_utc(last_alive_at) <= grace:
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
        except (UnicodeDecodeError, TypeError, ValueError):
            log.warning("Could not decode ACE-Step worker liveness", exc_info=True)
            malformed_state = True
            continue
        if not isinstance(parsed_state, Mapping):
            log.warning("Could not decode ACE-Step worker liveness: expected an object")
            malformed_state = True
            continue
        if worker_is_online(parsed_state):
            _record_alive(redis, ACESTEP_LAST_ALIVE_KEY, _as_utc(now))
            return WorkerLiveness.ALIVE
    if malformed_state:
        return WorkerLiveness.UNKNOWN
    return _missing_signal_liveness(
        redis, ACESTEP_LAST_ALIVE_KEY, WorkerLivenessSignal.MODEL_EXECUTION, _as_utc(now),
    )


def arq_worker_liveness(
    redis: Any,
    *,
    health_key: str,
    last_alive_key: str,
    signal: WorkerLivenessSignal,
    now: datetime,
) -> WorkerLiveness:
    """Read an ARQ health signal and its durable last-alive observation."""
    try:
        signal_is_alive = bool(redis.exists(health_key))
    except RedisError:
        log.warning("Could not read arq worker liveness", exc_info=True)
        return WorkerLiveness.UNKNOWN
    if signal_is_alive:
        _record_alive(redis, last_alive_key, _as_utc(now))
        return WorkerLiveness.ALIVE
    return _missing_signal_liveness(redis, last_alive_key, signal, _as_utc(now))


def read_worker_liveness(
    redis: Any,
    acestep_worker_ids: Iterable[str],
    *,
    now: datetime | None = None,
) -> dict[JobType, WorkerLiveness]:
    """Read each execution signal without taking ownership of database access."""
    observed_at = _as_utc(now or datetime.now(timezone.utc))
    return worker_liveness_by_job_type(
        acestep=acestep_worker_liveness(redis, acestep_worker_ids, now=observed_at),
        music=arq_worker_liveness(
            redis, health_key=ARQ_MUSIC_HEALTH_KEY, last_alive_key=MUSIC_LAST_ALIVE_KEY,
            signal=WorkerLivenessSignal.MUSIC,
            now=observed_at,
        ),
        scoring=arq_worker_liveness(
            redis, health_key=ARQ_SCORING_HEALTH_KEY, last_alive_key=SCORING_LAST_ALIVE_KEY,
            signal=WorkerLivenessSignal.SCORING,
            now=observed_at,
        ),
    )


def worker_liveness_by_job_type(
    *,
    acestep: WorkerLiveness,
    music: WorkerLiveness,
    scoring: WorkerLiveness,
) -> dict[JobType, WorkerLiveness]:
    """Return each job's execution signal; either dead model worker is decisive."""
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

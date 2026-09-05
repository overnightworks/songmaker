"""Tests for worker signals, durable observations, and job-type ownership."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from redis.exceptions import RedisError

from songmaker_cli.acestep_state import worker_state_key
from songmaker_cli.constants import (
    ARQ_MUSIC_HEALTH_KEY,
    WORKER_RESTART_GRACE_SECONDS,
    CoverExecutor,
    JobType,
    WorkerLivenessSignal,
)
from songmaker_cli.settings import get_settings
from songmaker_cli.worker_liveness import (
    ACESTEP_LAST_ALIVE_KEY,
    MUSIC_LAST_ALIVE_KEY,
    WorkerLiveness,
    acestep_worker_liveness,
    arq_worker_liveness,
    read_worker_liveness,
    worker_liveness_by_job_type,
)


def test_worker_liveness_maps_each_job_type_to_its_real_execution_signal() -> None:
    liveness = worker_liveness_by_job_type(
        acestep=WorkerLiveness.ALIVE,
        music=WorkerLiveness.DEAD,
        scoring=WorkerLiveness.UNKNOWN,
    )

    assert liveness == {
        JobType.COVER: WorkerLiveness.DEAD,
        JobType.GENERATE: WorkerLiveness.DEAD,
        JobType.LOAD_MODEL_ON_WORKER: WorkerLiveness.DEAD,
        JobType.DOWNLOAD_MODEL_ON_WORKER: WorkerLiveness.DEAD,
        JobType.LORA_TRAINING: WorkerLiveness.DEAD,
        JobType.SCORE: WorkerLiveness.UNKNOWN,
        JobType.CHAT: WorkerLiveness.UNKNOWN,
    }


def test_web_cover_executor_does_not_depend_on_the_music_worker() -> None:
    liveness = worker_liveness_by_job_type(
        acestep=WorkerLiveness.ALIVE,
        music=WorkerLiveness.DEAD,
        scoring=WorkerLiveness.UNKNOWN,
        cover_executor=CoverExecutor.WEB,
    )

    assert liveness[JobType.COVER] is WorkerLiveness.UNKNOWN
    assert liveness[JobType.GENERATE] is WorkerLiveness.DEAD


def test_read_liveness_ignores_a_live_music_worker_for_web_covers(
    fake_redis, monkeypatch,
) -> None:
    monkeypatch.setenv("COVER_EXECUTOR", CoverExecutor.WEB)
    get_settings.cache_clear()
    fake_redis.set(ARQ_MUSIC_HEALTH_KEY, "alive")

    liveness = read_worker_liveness(fake_redis, [])

    assert liveness[JobType.COVER] is WorkerLiveness.UNKNOWN


def test_model_jobs_require_live_acestep_and_music_workers() -> None:
    alive = worker_liveness_by_job_type(
        acestep=WorkerLiveness.ALIVE,
        music=WorkerLiveness.ALIVE,
        scoring=WorkerLiveness.UNKNOWN,
    )
    assert all(
        alive[job_type] is WorkerLiveness.ALIVE
        for job_type in (
            JobType.GENERATE,
            JobType.LOAD_MODEL_ON_WORKER,
            JobType.DOWNLOAD_MODEL_ON_WORKER,
        )
    )

    acestep_dead = worker_liveness_by_job_type(
        acestep=WorkerLiveness.DEAD,
        music=WorkerLiveness.ALIVE,
        scoring=WorkerLiveness.UNKNOWN,
    )
    assert all(
        acestep_dead[job_type] is WorkerLiveness.DEAD
        for job_type in (
            JobType.GENERATE,
            JobType.LOAD_MODEL_ON_WORKER,
            JobType.DOWNLOAD_MODEL_ON_WORKER,
        )
    )

    music_dead = worker_liveness_by_job_type(
        acestep=WorkerLiveness.ALIVE,
        music=WorkerLiveness.DEAD,
        scoring=WorkerLiveness.UNKNOWN,
    )
    assert all(
        music_dead[job_type] is WorkerLiveness.DEAD
        for job_type in (
            JobType.GENERATE,
            JobType.LOAD_MODEL_ON_WORKER,
            JobType.DOWNLOAD_MODEL_ON_WORKER,
        )
    )

    music_unknown = worker_liveness_by_job_type(
        acestep=WorkerLiveness.ALIVE,
        music=WorkerLiveness.UNKNOWN,
        scoring=WorkerLiveness.UNKNOWN,
    )
    assert all(
        music_unknown[job_type] is WorkerLiveness.UNKNOWN
        for job_type in (
            JobType.GENERATE,
            JobType.LOAD_MODEL_ON_WORKER,
            JobType.DOWNLOAD_MODEL_ON_WORKER,
        )
    )


def test_empty_acestep_registry_is_unknown_when_never_observed(fake_redis) -> None:
    assert (
        acestep_worker_liveness(fake_redis, [], now=datetime.now(timezone.utc))
        is WorkerLiveness.UNKNOWN
    )


def test_empty_acestep_registry_is_alive_when_recently_observed(fake_redis) -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    fake_redis.set(ACESTEP_LAST_ALIVE_KEY, now.isoformat())

    assert acestep_worker_liveness(fake_redis, [], now=now) is WorkerLiveness.ALIVE


def test_missing_signal_becomes_dead_after_restart_grace(fake_redis) -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)

    assert arq_worker_liveness(
        fake_redis, health_key=ARQ_MUSIC_HEALTH_KEY, last_alive_key=MUSIC_LAST_ALIVE_KEY,
        signal=WorkerLivenessSignal.MUSIC, now=now,
    ) is WorkerLiveness.UNKNOWN

    fake_redis.set(
        MUSIC_LAST_ALIVE_KEY,
        (now - timedelta(seconds=WORKER_RESTART_GRACE_SECONDS + 1)).isoformat(),
    )

    assert arq_worker_liveness(
        fake_redis, health_key=ARQ_MUSIC_HEALTH_KEY, last_alive_key=MUSIC_LAST_ALIVE_KEY,
        signal=WorkerLivenessSignal.MUSIC, now=now,
    ) is WorkerLiveness.DEAD


def test_missing_signal_is_alive_during_restart_grace(fake_redis) -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    fake_redis.set(MUSIC_LAST_ALIVE_KEY, now.isoformat())

    assert arq_worker_liveness(
        fake_redis, health_key=ARQ_MUSIC_HEALTH_KEY, last_alive_key=MUSIC_LAST_ALIVE_KEY,
        signal=WorkerLivenessSignal.MUSIC, now=now,
    ) is WorkerLiveness.ALIVE


def test_fresh_observer_does_not_declare_an_old_signal_dead(fake_redis, monkeypatch) -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    fake_redis.set(
        MUSIC_LAST_ALIVE_KEY,
        (now - timedelta(seconds=WORKER_RESTART_GRACE_SECONDS + 1)).isoformat(),
    )
    monkeypatch.setattr("songmaker_cli.worker_liveness._PROCESS_STARTED_AT", now)

    assert arq_worker_liveness(
        fake_redis, health_key=ARQ_MUSIC_HEALTH_KEY, last_alive_key=MUSIC_LAST_ALIVE_KEY,
        signal=WorkerLivenessSignal.MUSIC, now=now,
    ) is WorkerLiveness.ALIVE


def test_live_arq_signal_persists_its_last_alive_observation(fake_redis) -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    fake_redis.set(ARQ_MUSIC_HEALTH_KEY, "alive")

    assert arq_worker_liveness(
        fake_redis, health_key=ARQ_MUSIC_HEALTH_KEY, last_alive_key=MUSIC_LAST_ALIVE_KEY,
        signal=WorkerLivenessSignal.MUSIC, now=now,
    ) is WorkerLiveness.ALIVE
    assert fake_redis.get(MUSIC_LAST_ALIVE_KEY) == now.isoformat()


def test_acestep_signal_requires_an_online_worker_and_persists_observation(fake_redis) -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    fake_redis.set(worker_state_key("ace-1"), '{"gpu_healthy": true}')

    assert acestep_worker_liveness(fake_redis, ["ace-1"], now=now) is WorkerLiveness.ALIVE
    assert fake_redis.get(ACESTEP_LAST_ALIVE_KEY) == now.isoformat()

    fake_redis.set(worker_state_key("ace-1"), '{"gpu_healthy": false}')
    assert acestep_worker_liveness(fake_redis, ["ace-1"], now=now) is WorkerLiveness.ALIVE


def test_live_arq_signal_stays_alive_when_persisting_the_observation_fails(caplog) -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    redis = MagicMock()
    redis.exists.return_value = True
    redis.set.side_effect = RedisError("write failed")

    assert arq_worker_liveness(
        redis, health_key=ARQ_MUSIC_HEALTH_KEY, last_alive_key=MUSIC_LAST_ALIVE_KEY,
        signal=WorkerLivenessSignal.MUSIC, now=now,
    ) is WorkerLiveness.ALIVE
    assert "Could not persist worker liveness" in caplog.text


def test_live_acestep_signal_stays_alive_when_persisting_the_observation_fails(caplog) -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    redis = MagicMock()
    redis.get.return_value = '{"gpu_healthy": true}'
    redis.set.side_effect = RedisError("write failed")

    assert acestep_worker_liveness(redis, ["ace-1"], now=now) is WorkerLiveness.ALIVE
    assert "Could not persist worker liveness" in caplog.text


def test_decode_error_returns_unknown_and_logs(caplog) -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    redis = MagicMock()
    redis.get.side_effect = lambda key: b"\xff" if key == worker_state_key("ace-1") else None

    assert acestep_worker_liveness(redis, ["ace-1"], now=now) is WorkerLiveness.UNKNOWN
    assert "Could not decode ACE-Step worker liveness" in caplog.text


def test_non_object_acestep_state_returns_unknown_and_logs(fake_redis, caplog) -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    fake_redis.set(worker_state_key("ace-1"), "[]")

    assert acestep_worker_liveness(fake_redis, ["ace-1"], now=now) is WorkerLiveness.UNKNOWN
    assert "expected an object" in caplog.text


def test_malformed_acestep_state_does_not_hide_a_later_healthy_worker(fake_redis) -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    fake_redis.set(worker_state_key("ace-1"), '"alive"')
    fake_redis.set(worker_state_key("ace-2"), '{"gpu_healthy": true}')

    assert (
        acestep_worker_liveness(fake_redis, ["ace-1", "ace-2"], now=now)
        is WorkerLiveness.ALIVE
    )


def test_invalid_utf8_acestep_state_does_not_hide_a_later_healthy_worker() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    states = {
        worker_state_key("ace-1"): b"\xff",
        worker_state_key("ace-2"): '{"gpu_healthy": true}',
    }
    redis = MagicMock()
    redis.get.side_effect = states.get

    assert (
        acestep_worker_liveness(redis, ["ace-1", "ace-2"], now=now)
        is WorkerLiveness.ALIVE
    )


def test_null_acestep_state_returns_unknown_and_logs(fake_redis, caplog) -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    fake_redis.set(worker_state_key("ace-1"), "null")

    assert acestep_worker_liveness(fake_redis, ["ace-1"], now=now) is WorkerLiveness.UNKNOWN
    assert "expected an object" in caplog.text

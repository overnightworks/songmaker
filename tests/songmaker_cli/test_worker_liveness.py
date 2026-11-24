"""Tests for worker signals, durable observations, and job-type ownership."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from redis.exceptions import RedisError
from tandem import Roster

from songmaker_cli.acestep_state import worker_state_key
from songmaker_cli.constants import ARQ_SCORING_HEALTH_KEY, REDIS_KEY_PREFIX
from songmaker_cli.job_timing import worker_restart_grace_seconds
from songmaker_cli.job_types import JobType, WorkerLivenessSignal
from songmaker_cli.worker_liveness import (
    ACESTEP_LAST_ALIVE_KEY,
    WORKER_KINDS,
    WorkerLiveness,
    acestep_worker_liveness,
    read_worker_liveness,
    worker_kind_liveness,
    worker_liveness_by_job_type,
)


def test_worker_liveness_maps_each_job_type_to_its_real_execution_signal() -> None:
    liveness = worker_liveness_by_job_type(
        acestep=WorkerLiveness.ALIVE,
        music=WorkerLiveness.DEAD,
        scoring=WorkerLiveness.UNKNOWN,
    )

    assert liveness == {
        JobType.COVER: WorkerLiveness.UNKNOWN,
        JobType.GENERATE: WorkerLiveness.DEAD,
        JobType.LOAD_MODEL_ON_WORKER: WorkerLiveness.DEAD,
        JobType.DOWNLOAD_MODEL_ON_WORKER: WorkerLiveness.DEAD,
        JobType.LORA_TRAINING: WorkerLiveness.DEAD,
        JobType.SCORE: WorkerLiveness.UNKNOWN,
        JobType.CHAT: WorkerLiveness.UNKNOWN,
    }


LIVE_ROSTER = Roster(holders=frozenset({"worker-1"}), settled=True)
EMPTY_SETTLED_ROSTER = Roster(holders=frozenset(), settled=True)
EMPTY_UNSETTLED_ROSTER = Roster(holders=frozenset(), settled=False)


def test_read_liveness_ignores_a_live_music_worker_for_web_covers(fake_redis) -> None:
    liveness = read_worker_liveness(
        fake_redis, [], rosters={WorkerLivenessSignal.MUSIC: LIVE_ROSTER},
    )

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


@pytest.mark.parametrize("kind", WORKER_KINDS, ids=lambda kind: kind.value)
class TestAWorkerKindFollowsItsRoster:
    def test_a_live_roster_is_alive_and_persists_its_last_alive_observation(
        self, fake_redis, kind,
    ) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)

        assert worker_kind_liveness(fake_redis, kind, LIVE_ROSTER, now=now) is WorkerLiveness.ALIVE
        assert fake_redis.get(WORKER_KINDS[kind].last_alive_key) == now.isoformat()

    def test_a_live_roster_stays_alive_when_persisting_the_observation_fails(
        self, kind, caplog,
    ) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        redis = MagicMock()
        redis.set.side_effect = RedisError("write failed")

        assert worker_kind_liveness(redis, kind, LIVE_ROSTER, now=now) is WorkerLiveness.ALIVE
        assert "Could not persist worker liveness" in caplog.text

    def test_a_roster_that_cannot_be_read_is_unknown(self, fake_redis, kind) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        fake_redis.set(WORKER_KINDS[kind].last_alive_key, (now - timedelta(days=1)).isoformat())

        assert worker_kind_liveness(fake_redis, kind, None, now=now) is WorkerLiveness.UNKNOWN

    def test_an_empty_unsettled_roster_is_unknown_even_after_a_recent_observation(
        self, fake_redis, kind,
    ) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        fake_redis.set(WORKER_KINDS[kind].last_alive_key, now.isoformat())

        assert (
            worker_kind_liveness(fake_redis, kind, EMPTY_UNSETTLED_ROSTER, now=now)
            is WorkerLiveness.UNKNOWN
        )

    def test_an_empty_settled_roster_is_unknown_when_never_observed(
        self, fake_redis, kind,
    ) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)

        assert (
            worker_kind_liveness(fake_redis, kind, EMPTY_SETTLED_ROSTER, now=now)
            is WorkerLiveness.UNKNOWN
        )

    def test_an_empty_settled_roster_is_alive_inside_the_restart_grace(
        self, fake_redis, kind,
    ) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        fake_redis.set(
            WORKER_KINDS[kind].last_alive_key,
            (now - timedelta(seconds=worker_restart_grace_seconds(kind))).isoformat(),
        )

        assert (
            worker_kind_liveness(fake_redis, kind, EMPTY_SETTLED_ROSTER, now=now)
            is WorkerLiveness.ALIVE
        )

    def test_an_empty_settled_roster_is_dead_past_the_restart_grace(
        self, fake_redis, kind,
    ) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        fake_redis.set(
            WORKER_KINDS[kind].last_alive_key,
            (now - timedelta(seconds=worker_restart_grace_seconds(kind) + 1)).isoformat(),
        )

        assert (
            worker_kind_liveness(fake_redis, kind, EMPTY_SETTLED_ROSTER, now=now)
            is WorkerLiveness.DEAD
        )

    def test_a_fresh_observer_does_not_declare_an_old_observation_dead(
        self, fake_redis, kind, monkeypatch,
    ) -> None:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        fake_redis.set(
            WORKER_KINDS[kind].last_alive_key,
            (now - timedelta(seconds=worker_restart_grace_seconds(kind) + 1)).isoformat(),
        )
        monkeypatch.setattr("songmaker_cli.worker_liveness._PROCESS_STARTED_AT", now)

        assert (
            worker_kind_liveness(fake_redis, kind, EMPTY_SETTLED_ROSTER, now=now)
            is WorkerLiveness.ALIVE
        )


def test_arqs_health_key_does_not_make_the_scoring_signal_alive(fake_redis) -> None:
    fake_redis.set(ARQ_SCORING_HEALTH_KEY, "alive")

    liveness = read_worker_liveness(
        fake_redis, [], rosters={WorkerLivenessSignal.SCORING: EMPTY_SETTLED_ROSTER},
    )

    assert liveness[JobType.SCORE] is not WorkerLiveness.ALIVE


def test_the_persisted_keys_of_the_worker_kinds_match_those_of_the_release_before() -> None:
    """A rolling deploy in either direction reads the observation the other release wrote."""
    assert {
        kind: (row.lease_family, row.last_alive_key) for kind, row in WORKER_KINDS.items()
    } == {
        WorkerLivenessSignal.MUSIC: (
            "music-worker", f"{REDIS_KEY_PREFIX}:worker_liveness:last_alive:music",
        ),
        WorkerLivenessSignal.SCORING: (
            "scoring-worker", f"{REDIS_KEY_PREFIX}:worker_liveness:last_alive:scoring",
        ),
    }


def test_acestep_signal_requires_an_online_worker_and_persists_observation(fake_redis) -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    fake_redis.set(worker_state_key("ace-1"), '{"gpu_healthy": true}')

    assert acestep_worker_liveness(fake_redis, ["ace-1"], now=now) is WorkerLiveness.ALIVE
    assert fake_redis.get(ACESTEP_LAST_ALIVE_KEY) == now.isoformat()

    fake_redis.set(worker_state_key("ace-1"), '{"gpu_healthy": false}')
    assert acestep_worker_liveness(fake_redis, ["ace-1"], now=now) is WorkerLiveness.ALIVE


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

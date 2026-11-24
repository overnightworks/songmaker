"""A worker process that has not started yet ends on a stop signal, as the platform sends it."""

from __future__ import annotations

from pathlib import Path

import pytest
from redis import Redis
from support.app_processes import (
    LOOPBACK,
    MUSIC_WORKER_COMMAND,
    SCORING_WORKER_COMMAND,
    free_port,
    leased_owner_ids,
    poll_until,
    web_processes,
)

WAITING_FOR_THE_DATABASE = "Waiting up to"
WAIT_BEGINS_WITHIN_SECONDS = 30.0
STOPS_WITHIN_SECONDS = 8.0


@pytest.mark.parametrize(
    "command", [MUSIC_WORKER_COMMAND, SCORING_WORKER_COMMAND], ids=["music", "scoring"],
)
def test_a_worker_waiting_for_its_database_ends_on_a_stop_signal_without_a_lease_or_a_trace(
    command: list[str], tmp_path: Path, redis_url: str,
) -> None:
    database_nobody_answers_at = f"postgresql://songmaker@{LOOPBACK}:{free_port()}/songmaker"
    with web_processes(
        tmp_path, database_url=database_nobody_answers_at, redis_url=redis_url,
    ) as cluster, Redis.from_url(redis_url, decode_responses=True) as redis:
        worker = cluster.launch_worker("waiting", command)
        assert poll_until(
            lambda: WAITING_FOR_THE_DATABASE in worker.log_text(),
            deadline_seconds=WAIT_BEGINS_WITHIN_SECONDS,
        ), worker.log_tail()

        worker.process.terminate()
        exit_code = worker.process.wait(timeout=STOPS_WITHIN_SECONDS)

        assert exit_code == 0, worker.log_tail()
        assert "Traceback" not in worker.log_text()
        assert leased_owner_ids(redis) == set()

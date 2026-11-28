"""A web process that gets SIGTERM ends its streams and bounds its co-writer turns."""

from __future__ import annotations

import json
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx
import pytest
from support.app_processes import WebProcess, environment_name
from support.web_cluster_world import StandInCluster

from songmaker_cli.constants import RESOURCE_EVENT_STREAM_PATH
from songmaker_cli.db.models import Job
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.jobs_api import SSE_POLL_INTERVAL_SECONDS
from songmaker_cli.messages import message
from songmaker_cli.settings import Settings

PERSON_NAME = "pat"
REFRESH_TOKEN = "refresh-token-of-pat"  # noqa: S105
DRAIN_SECONDS = 6
TEARDOWN_SECONDS = 5.0
STREAM_CLOSE_SECONDS = SSE_POLL_INTERVAL_SECONDS + 1.5
DEADLINE_SECONDS = 30.0


@dataclass
class _OpenStream:
    """A stream held open by a thread of the test, and when the server ended it."""

    opened: threading.Event
    closed_at: float | None = None


def _hold_stream(web_process: WebProcess, path: str, cookies: dict[str, str], held: _OpenStream):
    try:
        with httpx.stream(
            "GET", f"{web_process.url}{path}", cookies=cookies, timeout=DEADLINE_SECONDS,
        ) as response:
            for line in response.iter_lines():
                if line.startswith("data: "):
                    held.opened.set()
    finally:
        held.closed_at = time.monotonic()


def _turn_frames(web_process: WebProcess, cookies: dict[str, str]) -> list[dict]:
    """The frames of one turn, up to its end or to the connection the server cut."""
    frames: list[dict] = []
    try:
        with httpx.stream(
            "POST",
            f"{web_process.url}/api/chat/turn",
            json={"message": "Which key suits a lullaby?"},
            cookies=cookies,
            headers={"Origin": web_process.url},
            timeout=DEADLINE_SECONDS,
        ) as response:
            frames.extend(
                json.loads(line.removeprefix("data: "))
                for line in response.iter_lines()
                if line.startswith("data: ")
            )
    except httpx.TransportError:
        pass
    return frames


@pytest.mark.parametrize(
    ("released_before_the_bound", "final_status", "failure"),
    [
        pytest.param(True, JobStatus.COMPLETED, None, id="a-turn-released-in-time-completes"),
        pytest.param(
            False, JobStatus.FAILED, message("chatFailure.serverRestarted"),
            id="a-turn-held-at-the-bound-fails-as-a-restart",
        ),
    ],
)
def test_sigterm_ends_the_streams_and_bounds_the_turn(
    stand_in_cluster: StandInCluster, redis_url: str,
    released_before_the_bound: bool, final_status: JobStatus, failure,
) -> None:
    web_process = stand_in_cluster.cluster.start(
        "web",
        environment={environment_name(Settings, "web_drain_seconds"): str(DRAIN_SECONDS)},
    )
    cookies = stand_in_cluster.sign_in(
        redis_url, PERSON_NAME, refresh_token=REFRESH_TOKEN,
    ).cookies
    gateway, factory = stand_in_cluster.gateway, stand_in_cluster.factory

    with ThreadPoolExecutor(max_workers=4) as executor:
        turn = executor.submit(_turn_frames, web_process, cookies)
        assert gateway.received.wait(DEADLINE_SECONDS)
        with factory() as session:
            job_id = session.query(Job).filter_by(type=JobType.CHAT).one().id
        streams = {
            path: _OpenStream(threading.Event())
            for path in (f"/api/jobs/{job_id}/stream", RESOURCE_EVENT_STREAM_PATH)
        }
        for path, held in streams.items():
            executor.submit(_hold_stream, web_process, path, cookies, held)
        assert all(held.opened.wait(DEADLINE_SECONDS) for held in streams.values())

        terminated_at = time.monotonic()
        stopping = executor.submit(web_process.stop)
        while any(held.closed_at is None for held in streams.values()):
            assert time.monotonic() - terminated_at < DEADLINE_SECONDS
            time.sleep(0.05)
        closed_after = max(held.closed_at for held in streams.values()) - terminated_at
        if released_before_the_bound:
            gateway.released.set()
        frames = turn.result(timeout=DEADLINE_SECONDS)
        stopping.result(timeout=DEADLINE_SECONDS)
        exited_after = time.monotonic() - terminated_at

    with factory() as session:
        job = session.get(Job, job_id)
        stored = (job.status, job.error_message)

    assert closed_after < STREAM_CLOSE_SECONDS
    assert exited_after < DRAIN_SECONDS + TEARDOWN_SECONDS
    # uvicorn ends by the signal it was sent once it has shut down; a kill would read -9.
    assert web_process.process.returncode == -signal.SIGTERM
    assert stored == (final_status, failure)
    assert bool(frames and frames[-1]["type"] == "final") is released_before_the_bound

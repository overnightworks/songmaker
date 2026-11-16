"""Two web processes: a cancel sent to one stops the co-writer turn the other runs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import httpx
from support.app_processes import WebProcess
from support.web_cluster_world import StandInCluster

from songmaker_cli.db.models import Job
from songmaker_cli.job_types import JobStatus, JobType

PERSON_NAME = "pat"
REFRESH_TOKEN = "refresh-token-of-pat"  # noqa: S105
REQUEST_TIMEOUT_SECONDS = 10.0
DEADLINE_SECONDS = 20.0


def _send_turn(web_process: WebProcess, cookies: dict[str, str]) -> list[str]:
    """Send a turn from the process's own page and read its stream until it ends."""
    with httpx.stream(
        "POST",
        f"{web_process.url}/api/chat/turn",
        json={"message": "Which key suits a lullaby?"},
        cookies=cookies,
        headers={"Origin": web_process.url},
        timeout=DEADLINE_SECONDS,
    ) as response:
        return [line for line in response.iter_lines() if line.startswith("data: ")]


def test_a_cancel_sent_to_one_process_stops_the_turn_the_other_runs(
    stand_in_cluster: StandInCluster, redis_url: str,
) -> None:
    process_a = stand_in_cluster.cluster.start("a")
    process_b = stand_in_cluster.cluster.start("b")
    person = stand_in_cluster.sign_in(redis_url, PERSON_NAME, refresh_token=REFRESH_TOKEN)
    gateway, factory = stand_in_cluster.gateway, stand_in_cluster.factory

    with ThreadPoolExecutor(max_workers=1) as executor:
        turn = executor.submit(_send_turn, process_a, person.cookies)
        reached_gateway = gateway.received.wait(DEADLINE_SECONDS)
        with factory() as session:
            job_id = session.query(Job).filter_by(type=JobType.CHAT).one().id
        cancelled = httpx.post(
            f"{process_b.url}/api/jobs/{job_id}/cancel",
            cookies=person.cookies,
            headers={"Origin": process_b.url},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        # The gateway is still held: only a stopped turn can have ended its stream.
        try:
            frames = turn.result(timeout=DEADLINE_SECONDS)
        except TimeoutError:
            frames = None
        gateway.released.set()
        if frames is None:
            frames = turn.result(timeout=DEADLINE_SECONDS)
            stream_ended_while_held = False
        else:
            stream_ended_while_held = True
    with factory() as session:
        final_status = session.get(Job, job_id).status

    assert (
        reached_gateway,
        cancelled.status_code,
        stream_ended_while_held,
        any('"type": "final"' in frame for frame in frames),
        final_status,
    ) == (True, 200, True, False, JobStatus.CANCELLED)

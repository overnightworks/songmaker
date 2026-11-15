"""Two web processes: a cancel sent to one stops the cover picture the other draws."""

from __future__ import annotations

import httpx
from redis import Redis
from support.app_processes import poll_until
from support.web_cluster_world import StandInCluster, start_owner

from songmaker_cli.cover_runner import COVER_PICTURE_CANCELLED_LOG
from songmaker_cli.db.models import Album, Job
from songmaker_cli.job_types import JobStatus

PERSON_NAME = "pat"
REFRESH_TOKEN = "refresh-token-of-pat"  # noqa: S105
ALBUM_ID = "album-of-pat"
REQUEST_TIMEOUT_SECONDS = 10.0
DEADLINE_SECONDS = 20.0


def test_a_cancel_sent_to_one_process_stops_the_picture_the_other_draws(
    stand_in_cluster: StandInCluster, redis_url: str,
) -> None:
    cluster, factory, gateway = (
        stand_in_cluster.cluster, stand_in_cluster.factory, stand_in_cluster.gateway,
    )
    with Redis.from_url(redis_url, decode_responses=True) as redis_client:
        process_a, owner_a = start_owner(cluster, redis_client, "a")
        process_b, owner_b = start_owner(cluster, redis_client, "b")
    person = stand_in_cluster.sign_in(redis_url, PERSON_NAME, refresh_token=REFRESH_TOKEN)
    with factory() as session:
        session.add(
            Album(id=ALBUM_ID, title="Open Windows", artist="Pat", created_by=person.user_id),
        )
        session.commit()

    def post(process, path: str) -> httpx.Response:
        return httpx.post(
            f"{process.url}{path}",
            cookies=person.cookies,
            headers={"Origin": process.url},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    job_id = post(process_a, f"/api/albums/{ALBUM_ID}/cover-suggestions").json()["id"]
    reached_gateway = gateway.received.wait(DEADLINE_SECONDS)
    with factory() as session:
        drawing_owner = session.get(Job, job_id).owner_id
    drawing, other = (
        (process_a, process_b) if drawing_owner == owner_a else (process_b, process_a)
    )

    cancelled = post(other, f"/api/jobs/{job_id}/cancel")
    stopped = poll_until(
        lambda: COVER_PICTURE_CANCELLED_LOG % job_id in drawing.log_text(),
        deadline_seconds=DEADLINE_SECONDS,
    )
    gateway.released.set()
    with factory() as session:
        final_status = session.get(Job, job_id).status

    assert (
        reached_gateway, cancelled.status_code, stopped, final_status,
    ) == (True, 200, True, JobStatus.CANCELLED)

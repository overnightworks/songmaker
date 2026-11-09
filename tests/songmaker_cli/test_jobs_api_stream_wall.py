"""A job stream ends at its wall, and a cancel that loses a race to a worker is refused."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.web_app import (
    make_authenticated_user,
    make_router_app,
    make_router_ctx,
    make_test_app,
    seed_session,
    seed_user,
    web_client,
)

import songmaker_cli.jobs_api as jobs_api
from songmaker_cli.db.models import Job
from songmaker_cli.db.queries.jobs import JobStatusUpdate, create_job, update_job_status
from songmaker_cli.job_types import JobStatus, JobType

OWNER_ID = "owner"


class _TickingClock:
    """A clock that moves one step on every read, so the wall arrives without waiting."""

    def __init__(self, step: float) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        reading = self.now
        self.now += self.step
        return reading


def _queued_job_id(client: TestClient) -> str:
    with client.app.state.ctx.db() as session:
        seed_user(session, "owner", user_id=OWNER_ID)
        job = create_job(session, JobType.GENERATE, user_id=OWNER_ID)
        session.commit()
        return job.id


def _streamed_statuses(client: TestClient, job_id: str) -> list[str]:
    with client.stream("GET", f"/api/jobs/{job_id}/stream") as response:
        assert response.status_code == 200
        return [
            json.loads(line.removeprefix("data: "))["status"]
            for line in response.iter_lines()
            if line.startswith("data: ")
        ]


@pytest.mark.parametrize(
    ("wall_fraction_per_read", "statuses"),
    [(0.4, []), (0.25, ["queued"])],
    ids=["wall-before-the-first-poll", "wall-right-after-a-frame"],
)
def test_a_stream_of_a_waiting_job_ends_at_its_wall(
    tmp_path: Path,
    pg_factory,
    monkeypatch: pytest.MonkeyPatch,
    wall_fraction_per_read: float,
    statuses: list[str],
) -> None:
    client, _ = make_test_app(tmp_path, factory=pg_factory)
    job_id = _queued_job_id(client)
    seed_session(client, "owner")
    clock = _TickingClock(jobs_api.JOB_STREAM_CONNECTION_SECONDS * wall_fraction_per_read)
    monkeypatch.setattr(jobs_api, "monotonic", clock)

    assert _streamed_statuses(client, job_id) == statuses


def test_a_cancel_that_loses_the_race_to_a_finishing_worker_is_refused(
    tmp_path: Path, pg_factory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = make_router_ctx(tmp_path, db=pg_factory)
    client = web_client(make_router_app(ctx, user=make_authenticated_user(OWNER_ID)))
    job_id = _queued_job_id(client)
    cancel_status_update = jobs_api.update_job_status

    def worker_finishes_first(session, finishing_job_id, update):
        with ctx.db() as worker_session:
            update_job_status(
                worker_session, finishing_job_id, JobStatusUpdate(JobStatus.COMPLETED),
            )
            worker_session.commit()
        return cancel_status_update(session, finishing_job_id, update)

    monkeypatch.setattr(jobs_api, "update_job_status", worker_finishes_first)

    response = client.post(f"/api/jobs/{job_id}/cancel")

    assert response.status_code == 409
    with ctx.db() as session:
        assert session.get(Job, job_id).status == JobStatus.COMPLETED

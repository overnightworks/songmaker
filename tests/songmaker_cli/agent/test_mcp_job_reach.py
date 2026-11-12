"""Which jobs a person's agent reaches: only those the person may open as a member."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from support.cowriter_gateway import attach_cowriter_gateway
from support.mcp_tool_table import ALICE, BOB
from support.mcp_world import ADMIN_GROUPS, SAME_ORIGIN, McpWorld, worker_ready
from support.token_world import TokenWorld

from songmaker_cli.db.models import Job
from songmaker_cli.job_types import JobStatus


def _started_in_the_browser(
    path: str, body: dict | None = None,
) -> Callable[[McpWorld, Path], str]:
    def start(world: McpWorld, directory: Path) -> str:
        attach_cowriter_gateway(
            world.world.client, world.world.factory, directory, TokenWorld.ALICE,
        )
        with worker_ready():
            reply = world.world.client.post(path, json=body or {}, headers=SAME_ORIGIN)
        assert reply.status_code == 200
        return reply.json()["id"]
    return start


@pytest.mark.parametrize("start", [
    _started_in_the_browser(f"/api/songs/song-{BOB}/generate", {"model": "sft"}),
    _started_in_the_browser(f"/api/generations/take-{BOB}/score"),
    _started_in_the_browser(f"/api/albums/album-{BOB}/cover-suggestions"),
], ids=["generate", "score", "cover"])
def test_an_admins_agent_is_refused_the_job_the_admin_started_on_another_persons_content(
    admins_household: McpWorld, tmp_path: Path, start: Callable[[McpWorld, Path], str],
) -> None:
    job_id = start(admins_household, tmp_path)

    job = admins_household.call("get_job", {"job_id": job_id}, groups=ADMIN_GROUPS)
    cancel = admins_household.call("cancel_job", {"job_id": job_id}, groups=ADMIN_GROUPS)
    browser = admins_household.world.client.get(f"/api/jobs/{job_id}")

    assert (job.is_error, cancel.is_error) == (True, True)
    statuses = dict(admins_household.rows_of(Job, "id", "status"))
    assert statuses[job_id] != JobStatus.CANCELLED
    assert browser.status_code == 200


def test_a_members_agent_reaches_the_score_job_the_member_started(household: McpWorld) -> None:
    with worker_ready():
        job_id = household.call("score_take", {"gen_id": f"take-{ALICE}"}).json()["id"]

    read = household.call("get_job", {"job_id": job_id})
    cancel = household.call("cancel_job", {"job_id": job_id})

    assert (read.is_error, cancel.is_error) == (False, False)
    assert (job_id, "cancelled") in household.rows_of(Job, "id", "status")



"""Which jobs a person's agent reaches: only those the person may open as a member."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker
from support.cowriter_gateway import attach_cowriter_gateway
from support.mcp_world import McpWorld, build_mcp_world, worker_ready
from support.token_world import TokenWorld
from support.web_app import TEST_ORIGIN, seed_session

from songmaker_cli.constants import OIDC_ADMIN_GROUP, OIDC_LOGIN_GROUP, OIDC_MCP_GROUP
from songmaker_cli.db.models import Job
from songmaker_cli.job_types import JobType

ALICE = "alices"
BOB = "bobs"
_SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin", "Origin": TEST_ORIGIN}
_ADMIN_GROUPS = (OIDC_LOGIN_GROUP, OIDC_ADMIN_GROUP, OIDC_MCP_GROUP)


def _household_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory: sessionmaker,
    lifespans: ExitStack, *, alice_role: str,
) -> McpWorld:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    world = build_mcp_world(tmp_path, monkeypatch, pg_factory, lifespans, alice_role=alice_role)
    world.seed_household(TokenWorld.ALICE, ALICE)
    world.seed_household(TokenWorld.BOB, BOB)
    return world


@pytest.fixture
def admins_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory: sessionmaker,
    lifespans: ExitStack,
) -> McpWorld:
    return _household_world(tmp_path, monkeypatch, pg_factory, lifespans, alice_role="admin")


def _started_in_the_browser(path: str) -> Callable[[McpWorld, Path], str]:
    def start(world: McpWorld, directory: Path) -> str:
        attach_cowriter_gateway(
            world.world.client, world.world.factory, directory, TokenWorld.ALICE,
        )
        with worker_ready():
            reply = world.world.client.post(path, json={}, headers=_SAME_ORIGIN)
        assert reply.status_code == 200
        return reply.json()["id"]
    return start


def _seeded_by_the_admin(world: McpWorld, directory: Path) -> str:
    seed_session(world.world.client, "alice")
    with world.world.factory() as session:
        session.add(Job(id="admin-job", type=JobType.GENERATE, status="queued",
                        user_id=TokenWorld.ALICE, song_id=f"song-{BOB}"))
        session.commit()
    return "admin-job"


@pytest.mark.parametrize("start", [
    _seeded_by_the_admin,
    _started_in_the_browser(f"/api/generations/take-{BOB}/score"),
    _started_in_the_browser(f"/api/albums/album-{BOB}/cover-suggestions"),
], ids=["generate", "score", "cover"])
def test_an_admins_agent_is_refused_the_job_the_admin_started_on_another_persons_content(
    admins_world: McpWorld, tmp_path: Path, start: Callable[[McpWorld, Path], str],
) -> None:
    job_id = start(admins_world, tmp_path)

    job = admins_world.call("get_job", {"job_id": job_id}, groups=_ADMIN_GROUPS)
    cancel = admins_world.call("cancel_job", {"job_id": job_id}, groups=_ADMIN_GROUPS)
    browser = admins_world.world.client.get(f"/api/jobs/{job_id}")

    assert (job.is_error, cancel.is_error) == (True, True)
    assert (job_id, "queued") in admins_world.rows_of(Job, "id", "status")
    assert browser.status_code == 200


def test_a_members_agent_reaches_the_score_job_the_member_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory: sessionmaker,
    lifespans: ExitStack,
) -> None:
    world = _household_world(tmp_path, monkeypatch, pg_factory, lifespans, alice_role="user")
    with worker_ready():
        job_id = world.call("score_take", {"gen_id": f"take-{ALICE}"}).json()["id"]

    read = world.call("get_job", {"job_id": job_id})
    cancel = world.call("cancel_job", {"job_id": job_id})

    assert (read.is_error, cancel.is_error) == (False, False)
    assert (job_id, "cancelled") in world.rows_of(Job, "id", "status")



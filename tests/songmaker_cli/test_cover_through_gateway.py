"""The album cover through the gateway, driven at Suggest and the web runner.

Suggest is ``POST /api/albums/{id}/cover-suggestions``; the run is ``run_next_cover_job`` on the
app; the gateway is ``FakeGateway`` and the realm the fake issuer, so the picture agent, the
classifier, the session the job references and the publication are all real.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from io import BytesIO
from pathlib import Path

import pytest
from agent_runtime_client.agents import load_agent
from agent_runtime_client.backend import TurnStopKind, TurnStopped
from agent_runtime_client.backend.fake_gateway import (
    Reply,
    completion,
    picture,
    tool_call,
    tool_round,
)
from agent_runtime_client.backend.gateway import GatewayBackend
from agent_runtime_client.turn import FailureCode, Principal, RejectionCode, person_fingerprint
from fastapi.testclient import TestClient
from PIL import Image
from support.cover_album_world import declared_suggest_refusal
from support.cowriter_gateway import (
    A_REFRESH_TOKEN,
    CowriterStack,
    HeldGateway,
    agent_config,
    attach_cowriter_gateway,
    closed_port_origin,
    stops,
)
from support.fake_oidc_issuer import USER_ACCESS_TOKEN, Person
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client
from support.xmp_packet import read_digital_source_type

from audio_engine.constants import IPTC_TRAINED_ALGORITHMIC_MEDIA
from songmaker_cli import cover_runner
from songmaker_cli.api_models import AgentProblem
from songmaker_cli.constants import JobStatus
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import (
    Album,
    AlbumCoverSuggestion,
    Job,
    Song,
    User,
    UserSession,
    Version,
)
from songmaker_cli.oidc_client import normalised_oidc_issuer

USER_ID = "u-cover"
ALBUM_ID = "alb-cover"
SUGGEST = f"/api/albums/{ALBUM_ID}/cover-suggestions"
NOT_A_MEMBER = ("/apps/songmaker",)


def _image_bytes(image_format: str, size: tuple[int, int] = (16, 16)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, (20, 80, 160)).save(output, format=image_format)
    return output.getvalue()


def _seed_open_windows_album(session) -> None:
    session.add(User(id=USER_ID, username="owner", role="user"))
    session.flush()
    session.add(Album(id=ALBUM_ID, title="Open Windows", artist="Felix", created_by=USER_ID))
    session.add(Song(id="song", album_id=ALBUM_ID, title="Morgenluft", track_number=1))
    session.add(Version(
        id="version", song_id="song", version_number=1, prompt="warm electronic",
        lyrics="the window opens",
    ))
    session.commit()


@dataclass
class CoverWorld:
    client: TestClient
    factory: object
    stack: CowriterStack
    audio_dir: Path

    @property
    def app(self):
        return self.client.app

    def suggest(self):
        return self.client.post(SUGGEST)

    def queue(self) -> str:
        response = self.suggest()
        assert response.status_code == 200, response.text
        return response.json()["id"]

    def run_next(self) -> bool:
        return asyncio.run(cover_runner.run_next_cover_job(self.app))

    def job(self, job_id: str) -> Job:
        with self.factory() as session:
            job = session.get(Job, job_id)
            session.expunge(job)
            return job

    def jobs(self) -> int:
        with self.factory() as session:
            return session.query(Job).count()

    def suggestions(self) -> list[AlbumCoverSuggestion]:
        with self.factory() as session:
            rows = session.query(AlbumCoverSuggestion).all()
            session.expunge_all()
            return rows

    def used_today(self) -> int:
        return self.client.get(SUGGEST).json()["used_today"]

    def picture_requests(self) -> list:
        return [
            request for request in self.stack.gateway_requests
            if request.url.path == "/v1/images/generations"
        ]


def build_world(tmp_path: Path, factory, **attach) -> CoverWorld:
    with factory() as session:
        _seed_open_windows_album(session)
    ctx = make_router_ctx(tmp_path, db=factory)
    app = make_router_app(ctx, user=make_authenticated_user(USER_ID))
    client = web_client(app)
    stack = attach_cowriter_gateway(client, factory, tmp_path, USER_ID, **attach)
    stack.replies(picture(_image_bytes("PNG")))
    return CoverWorld(client, factory, stack, ctx.audio_dir)


@pytest.fixture
def world(tmp_path: Path, pg_factory) -> CoverWorld:
    return build_world(tmp_path, pg_factory)


def _problem_of(response) -> str:
    return response.json()["detail"]["problem"]


# 1 and 23: a member gets one suggestion, and only that run spends the count.
def test_a_member_gets_one_suggestion_drawn_by_the_picture_agent(world):
    job_id = world.queue()

    assert world.run_next() is True

    job = world.job(job_id)
    assert job.status == JobStatus.COMPLETED
    assert job.session_id is None
    [suggestion] = world.suggestions()
    published_path = world.audio_dir / suggestion.png_path
    with Image.open(published_path) as published:
        assert published.format == "PNG"
    assert read_digital_source_type(published_path) == IPTC_TRAINED_ALGORITHMIC_MEDIA
    agent = load_agent(files("songmaker_cli") / "agents" / "cover.md", [])
    [request] = world.picture_requests()
    body = json.loads(request.content)
    assert body["model"] == agent.model
    assert body["size"] == agent.picture_size
    assert body["prompt"].startswith(agent.prompt)
    assert '"title":"Open Windows"' in body["prompt"]
    assert "the window opens" in body["prompt"]
    asker = Principal(iss=normalised_oidc_issuer(world.stack.issuer.issuer), sub=USER_ID)
    assert body["user"] == person_fingerprint(asker)
    assert world.used_today() == 1


def test_a_jpeg_picture_is_stored_as_png(world):
    world.stack.replies(picture(_image_bytes("JPEG")))
    job_id = world.queue()

    world.run_next()

    assert world.job(job_id).status == JobStatus.COMPLETED
    [suggestion] = world.suggestions()
    with Image.open(world.audio_dir / suggestion.png_path) as published:
        assert published.format == "PNG"


# 2, 7 and 8: the click checks the person's groups and the agent before any job.
@pytest.mark.parametrize(
    ("arrangement", "status", "problem"),
    [
        ("outside-the-api-group", 403, "not_enabled"),
        ("no-refresh-grant", 403, "sign_in_again"),
        ("refresh-grant-refused", 403, "sign_in_again"),
        ("issuer-down", 503, "unavailable"),
        ("agent-unset", 503, "unavailable"),
    ],
)
def test_the_click_refuses_before_any_job_and_any_request(
    tmp_path, arrangement, status, problem, pg_factory,
):
    world = build_world(
        tmp_path, pg_factory,
        groups=NOT_A_MEMBER if arrangement == "outside-the-api-group" else ("/apps/songmaker",
                                                                           "/apps/songmaker/api"),
        refresh_token=None if arrangement == "no-refresh-grant" else "fake-refresh-token",
    )
    if arrangement == "refresh-grant-refused":
        world.stack.issuer.refuses_refresh_with = "invalid_grant"
    if arrangement == "issuer-down":
        world.stack.issuer.unreachable = True
    if arrangement == "agent-unset":
        world.stack.unset()

    response = world.suggest()

    assert response.status_code == status
    assert _problem_of(response) == problem
    declared_suggest_refusal(status).model_validate(response.json())
    assert world.jobs() == 0
    assert world.stack.gateway_requests == []
    assert world.used_today() == 0


# 3, 4, 5, 6 and 7: the job checks again at its start, and a refusal sends nothing.
def _remove_from_the_api_group(world: CoverWorld, _job_id: str) -> None:
    world.stack.issuer.person = Person(subject=USER_ID, groups=NOT_A_MEMBER)


def _log_out(world: CoverWorld, _job_id: str) -> None:
    with world.factory() as session:
        session.query(UserSession).filter_by(id=world.stack.session_id).delete()
        session.commit()


def _let_the_session_expire(world: CoverWorld, _job_id: str) -> None:
    from songmaker_cli.db.queries.auth import delete_expired_sessions

    with world.factory() as session:
        row = session.get(UserSession, world.stack.session_id)
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        session.commit()
        delete_expired_sessions(session)
        session.commit()


def _forget_the_session_as_before_the_deploy(world: CoverWorld, job_id: str) -> None:
    with world.factory() as session:
        session.get(Job, job_id).session_id = None
        session.commit()


def _remove_the_user(world: CoverWorld, job_id: str) -> None:
    """The user's row went, which leaves the job's ``user_id`` empty (``ON DELETE SET NULL``)."""
    with world.factory() as session:
        session.get(Job, job_id).user_id = None
        session.commit()


def _unset_the_agent(world: CoverWorld, _job_id: str) -> None:
    world.stack.unset()


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (_remove_from_the_api_group, AgentProblem.NOT_ENABLED),
        (_log_out, AgentProblem.SIGN_IN_AGAIN),
        (_let_the_session_expire, AgentProblem.SIGN_IN_AGAIN),
        (_forget_the_session_as_before_the_deploy, AgentProblem.SIGN_IN_AGAIN),
        (_remove_the_user, AgentProblem.NOT_ENABLED),
        (_unset_the_agent, AgentProblem.UNAVAILABLE),
    ],
)
def test_a_job_refused_at_its_start_ends_before_any_request(world, change, problem):
    job_id = world.queue()
    change(world, job_id)

    world.run_next()

    job = world.job(job_id)
    assert (job.status, job.error_type) == (JobStatus.FAILED, problem.value)
    assert job.session_id is None
    assert world.picture_requests() == []
    assert world.suggestions() == []


# 13-17 and 23: what the gateway answers ends the job as one of the four problems.
_OVER_COVER_PIXELS = (5000, 4001)


def _two_entries() -> Reply:
    entry = {"b64_json": base64.b64encode(_image_bytes("PNG")).decode("ascii")}
    return Reply(body=json.dumps({"data": [entry, entry]}).encode())


def _a_url_entry() -> Reply:
    return Reply(body=json.dumps({"data": [{"url": "https://example.test/x.png"}]}).encode())


def _non_canonical_base64() -> Reply:
    return Reply(body=json.dumps({"data": [{"b64_json": "iVBORw0KGgo"}]}).encode())


def _empty_entry() -> Reply:
    return Reply(body=json.dumps({"data": [{"b64_json": ""}]}).encode())


@pytest.mark.parametrize(
    ("reply", "problem"),
    [
        (Reply(status=422, body=b'{"error":"budget_exceeded"}'), AgentProblem.UNAVAILABLE),
        (Reply(status=400, body=b'{"error":"moderation_blocked"}'), AgentProblem.UNAVAILABLE),
        (Reply(status=403, body=b'{"error":"model not allowed"}'), AgentProblem.UNAVAILABLE),
        (Reply(status=500), AgentProblem.UNAVAILABLE),
        (_two_entries(), AgentProblem.UNAVAILABLE),
        (_a_url_entry(), AgentProblem.UNAVAILABLE),
        (_non_canonical_base64(), AgentProblem.UNAVAILABLE),
        (_empty_entry(), AgentProblem.UNAVAILABLE),
        (picture(b"not an image at all"), AgentProblem.UNAVAILABLE),
        (picture(b"\x89PNG\r\n\x1a\n" + b"\0" * (8 * 1024 * 1024)), AgentProblem.UNAVAILABLE),
        (picture(_image_bytes("PNG", _OVER_COVER_PIXELS)), AgentProblem.UNAVAILABLE),
        (picture(_image_bytes("WEBP")), AgentProblem.UNAVAILABLE),
    ],
    ids=[
        "budget-422", "moderation-400", "model-403", "gateway-500", "two-entries", "url",
        "non-canonical-base64", "empty", "not-an-image", "over-8-mib", "over-20-mp", "webp",
    ],
)
def test_a_picture_that_does_not_come_out_ends_unavailable_and_spends_nothing(
    world, reply, problem,
):
    world.stack.replies(reply)
    job_id = world.queue()

    world.run_next()

    job = world.job(job_id)
    assert (job.status, job.error_type) == (JobStatus.FAILED, problem.value)
    assert job.retry_after_seconds is None
    assert world.suggestions() == []
    assert world.used_today() == 0
    assert not list(world.audio_dir.rglob("*.png"))


def test_a_busy_gateway_ends_busy_and_keeps_the_wait_it_named(world):
    world.stack.replies(Reply(status=429, headers={"Retry-After": "42"}))
    job_id = world.queue()

    world.run_next()

    job = world.job(job_id)
    assert (job.status, job.error_type, job.retry_after_seconds) == (
        JobStatus.FAILED, AgentProblem.BUSY.value, 42,
    )
    served = world.client.get(f"/api/jobs/{job_id}").json()
    assert (served["error_type"], served["retry_after_seconds"]) == ("busy", 42)
    assert world.used_today() == 0


def test_an_unreachable_gateway_ends_unavailable(world, tmp_path):
    from songmaker_cli.agent.tools import cowriter_hand_tools

    key_directory = tmp_path / "unreachable"
    key_directory.mkdir()
    unreachable = agent_config(key_directory, origin=closed_port_origin())
    world.app.state.agent_backend = GatewayBackend(
        unreachable, tools=cowriter_hand_tools(world.factory),
    )
    job_id = world.queue()

    world.run_next()

    assert world.job(job_id).error_type == AgentProblem.UNAVAILABLE.value


def test_a_missing_key_file_ends_unavailable_without_a_request(world):
    world.stack.config.gateway.key_file.unlink()
    job_id = world.queue()

    world.run_next()

    assert world.job(job_id).error_type == AgentProblem.UNAVAILABLE.value
    assert world.picture_requests() == []


# 16 and the one classifier: every stop the client defines maps to one of the four problems.
_REFUSED, _FAILED = TurnStopKind.REFUSED, TurnStopKind.FAILED
_PROBLEM_OF_EVERY_STOP = [
    (TurnStopped(_REFUSED, RejectionCode.NOT_ENABLED), AgentProblem.NOT_ENABLED),
    (TurnStopped(_REFUSED, RejectionCode.FORBIDDEN), AgentProblem.NOT_ENABLED),
    (TurnStopped(_REFUSED, RejectionCode.BUSY), AgentProblem.BUSY),
    (TurnStopped(_FAILED, FailureCode.PROVIDER_UNAVAILABLE), AgentProblem.UNAVAILABLE),
    (TurnStopped(_FAILED, FailureCode.PROVIDER_ERROR), AgentProblem.UNAVAILABLE),
    (TurnStopped(_FAILED, FailureCode.LIMIT_EXCEEDED), AgentProblem.UNAVAILABLE),
]


def test_the_stop_table_names_every_stop_the_client_defines():
    named = {(stopped.kind, stopped.code) for stopped, _problem in _PROBLEM_OF_EVERY_STOP}
    assert named == {
        *((_REFUSED, code) for code in RejectionCode),
        *((_FAILED, code) for code in FailureCode),
    }


@pytest.mark.parametrize(("stopped", "problem"), _PROBLEM_OF_EVERY_STOP, ids=str)
def test_every_stop_of_a_picture_run_is_one_of_the_four_problems(world, stopped, problem):
    world.stack.behaves(stops(stopped))
    job_id = world.queue()

    world.run_next()

    job = world.job(job_id)
    assert (job.status, job.error_type) == (JobStatus.FAILED, problem.value)


def test_the_picture_deadline_reads_unavailable(world):
    world.stack.behaves(stops(TurnStopped(TurnStopKind.FAILED, FailureCode.LIMIT_EXCEEDED)))
    job_id = world.queue()

    world.run_next()

    assert world.job(job_id).error_type == AgentProblem.UNAVAILABLE.value


# 18: an explicit Cancel stops the picture, publishes nothing and the runner goes on.
def test_cancel_during_the_picture_closes_the_request_and_the_next_job_runs(world, caplog):
    held = HeldGateway()
    world.stack.uses(held)
    first = world.queue()

    async def scenario() -> None:
        running = asyncio.create_task(cover_runner.run_next_cover_job(world.app))
        assert await asyncio.to_thread(held.received.wait, 10)
        cancelled = await asyncio.to_thread(world.client.post, f"/api/jobs/{first}/cancel")
        assert cancelled.status_code == 200
        assert await asyncio.wait_for(running, 10) is True

    with caplog.at_level(logging.ERROR):
        asyncio.run(scenario())

    assert held.closed.is_set()
    assert world.job(first).status == JobStatus.CANCELLED
    assert world.suggestions() == []
    assert not list(world.audio_dir.rglob("*.png"))
    assert not list(world.audio_dir.rglob(".*.staging"))
    assert caplog.records == []

    world.stack.replies(picture(_image_bytes("PNG")))
    second = world.queue()
    assert world.run_next() is True
    assert world.job(second).status == JobStatus.COMPLETED


def test_a_cancel_between_the_start_and_the_picture_sends_no_request(world, monkeypatch):
    job_id = world.queue()
    load_cover_start = cover_runner._load_cover_start

    def cancel_once_the_start_is_read(db_factory, loaded_job_id):
        start = load_cover_start(db_factory, loaded_job_id)
        cancelled = world.client.post(f"/api/jobs/{loaded_job_id}/cancel")
        assert cancelled.status_code == 200
        return start

    monkeypatch.setattr(cover_runner, "_load_cover_start", cancel_once_the_start_is_read)

    assert world.run_next() is True

    assert world.picture_requests() == []
    assert world.job(job_id).status == JobStatus.CANCELLED
    assert world.suggestions() == []
    assert not list(world.audio_dir.rglob(".*.staging"))


def test_a_runner_that_stops_cancels_its_picture(world):
    held = HeldGateway()
    world.stack.uses(held)
    job_id = world.queue()

    async def scenario() -> None:
        running = asyncio.create_task(cover_runner.run_next_cover_job(world.app))
        assert await asyncio.to_thread(held.received.wait, 10)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running

    asyncio.run(scenario())

    assert held.closed.is_set()
    assert world.job(job_id).status == JobStatus.RUNNING
    assert world.suggestions() == []


def test_the_runner_loop_survives_a_cancelled_picture(world):
    from songmaker_cli.health_types import BackgroundLoopName, BackgroundLoopRegistry

    class TickSignallingRegistry(BackgroundLoopRegistry):
        ticked: asyncio.Event

        def record_success(self, name: BackgroundLoopName) -> None:
            super().record_success(name)
            self.ticked.set()

    held = HeldGateway()
    world.stack.uses(held)
    job_id = world.queue()
    registry = TickSignallingRegistry(tuple(BackgroundLoopName))

    async def scenario() -> None:
        registry.ticked = asyncio.Event()
        loop = asyncio.create_task(cover_runner.cover_runner_loop(world.app, registry))
        assert await asyncio.to_thread(held.received.wait, 10)
        await asyncio.to_thread(world.client.post, f"/api/jobs/{job_id}/cancel")
        assert await asyncio.to_thread(held.closed.wait, 10)
        world.stack.replies(picture(_image_bytes("PNG")))
        second = await asyncio.to_thread(world.queue)
        async with asyncio.timeout(10):
            while world.job(second).status != JobStatus.COMPLETED:
                registry.ticked.clear()
                await registry.ticked.wait()
        assert not loop.done()
        health = registry.loop_health()[BackgroundLoopName.COVER_RUNNER]
        assert (health.consecutive_failures, health.last_error) == (0, None)
        loop.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop

    asyncio.run(scenario())

    assert held.closed.is_set()
    assert world.job(job_id).status == JobStatus.CANCELLED


# 26: no key, session id or fingerprint on any surface the person or a log can see.
def test_no_key_session_or_fingerprint_reaches_any_surface(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    outcomes = []
    for reply in (picture(_image_bytes("PNG")), Reply(status=429), Reply(status=400)):
        world = build_world(
            tmp_path / str(len(outcomes)), init_test_db(tmp_path / str(len(outcomes)) / "cover.db"),
        )
        world.stack.replies(reply)
        job_id = world.queue()
        world.run_next()
        [request] = world.picture_requests()
        fingerprint = json.loads(request.content)["user"]
        key = world.stack.config.gateway.key_file.read_text().strip()
        seen = [
            world.job(job_id).error or "",
            world.client.get(f"/api/jobs/{job_id}").text,
            world.client.get(SUGGEST).text,
        ]
        outcomes.append((key, world.stack.session_id, fingerprint, seen))
    refused = build_world(
        tmp_path / "refused", init_test_db(tmp_path / "refused" / "cover.db"), groups=NOT_A_MEMBER,
    )
    refusal = refused.suggest().text
    refused_key = refused.stack.config.gateway.key_file.read_text().strip()
    outcomes.append((refused_key, refused.stack.session_id, None, [refusal]))

    for key, session_id, fingerprint, seen in outcomes:
        canaries = [key, session_id, A_REFRESH_TOKEN, USER_ACCESS_TOKEN]
        if fingerprint is not None:
            canaries.append(fingerprint)
        for canary in canaries:
            assert canary not in caplog.text
            assert canary not in refusal
            for surface in seen:
                assert canary not in surface


# 9 and 26: the co-writer's cover runs as the turn's session, and its frames carry no secret.
def _turn_that_asks_for_a_cover(world: CoverWorld) -> str:
    world.stack.replies(
        tool_round(tool_call("call-1", "suggest_album_cover", {"album_id": ALBUM_ID})),
        completion("I asked for a cover."),
        picture(_image_bytes("PNG")),
    )
    response = world.client.post("/api/chat/turn", json={"message": "make a cover"})
    assert response.status_code == 200
    return response.text


def test_the_co_writers_cover_runs_as_the_turns_session_and_completes(world):
    frames = _turn_that_asks_for_a_cover(world)
    with world.factory() as session:
        job = session.query(Job).filter_by(type="cover").one()
        job_id, asked_from = job.id, job.session_id

    world.run_next()

    assert asked_from == world.stack.session_id
    assert world.job(job_id).status == JobStatus.COMPLETED
    [request] = world.picture_requests()
    fingerprint = json.loads(request.content)["user"]
    key = world.stack.config.gateway.key_file.read_text().strip()
    for canary in (key, world.stack.session_id, fingerprint):
        assert canary not in frames


def test_after_the_turns_session_logs_out_its_next_cover_signs_in_again(world):
    _turn_that_asks_for_a_cover(world)
    world.run_next()
    _turn_that_asks_for_a_cover(world)
    _log_out(world, "")

    world.run_next()

    with world.factory() as session:
        latest = session.query(Job).filter_by(type="cover").order_by(Job.started_at.desc()).first()
        assert (latest.status, latest.error_type) == (
            JobStatus.FAILED, AgentProblem.SIGN_IN_AGAIN.value,
        )

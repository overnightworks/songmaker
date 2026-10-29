"""A person's hal token on the REST API and the take files, against a fake Keycloak realm.

Every case drives the real app through the ASGI client. The relying party verifies
the tokens exactly as in production; only its key set and token endpoint are the
fake issuer's. Matrix cells T1 to T26 of the work item are named in the case ids.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.orm import Session
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp
from support.compose_config import run_compose_config
from support.token_world import TokenWorld, make_token_world
from support.web_app import TEST_ORIGIN, make_test_app, seed_session, seed_user

from songmaker_cli.auth_stores import DatabaseAuditSink
from songmaker_cli.constants import OIDC_ADMIN_GROUP, OIDC_LEEWAY_SECONDS, OIDC_LOGIN_GROUP
from songmaker_cli.db.models import (
    Album,
    ChatMessage,
    Job,
    UserSession,
)
from songmaker_cli.db.queries.resource_events import create_generation_created_event


@pytest.fixture
def token_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TokenWorld:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    return make_token_world(tmp_path)



# -- T1, T2: the token is the person -------------------------------------------------


def test_t1_a_members_token_lists_only_their_songs_and_makes_the_account_without_a_session(
    token_world: TokenWorld,
) -> None:
    token_world.seed_take(TokenWorld.BOB, "bobs")

    first = token_world.client.get("/api/songs", headers=token_world.bearer(TokenWorld.ALICE))
    token_world.seed_take(TokenWorld.ALICE, "alices")
    second = token_world.client.get("/api/songs", headers=token_world.bearer(TokenWorld.ALICE))

    assert first.json()["items"] == []
    assert [song["title"] for song in second.json()["items"]] == ["Song alices"]
    assert token_world.users().count((TokenWorld.ALICE, "alice", "user")) == 1
    assert token_world.audits().count((None, "create", "user", TokenWorld.ALICE)) == 1
    assert token_world.rows(UserSession, "id") == []


def test_t2_a_token_reaches_its_own_take_file_and_not_anothers(token_world: TokenWorld) -> None:
    token_world.seed_take(TokenWorld.ALICE, "alices")
    token_world.seed_take(TokenWorld.BOB, "bobs")
    headers = token_world.bearer(TokenWorld.ALICE)

    own = token_world.client.get(f"/audio/{TokenWorld.ALICE}/alices.mp3", headers=headers)
    other = token_world.client.get(f"/audio/{TokenWorld.BOB}/bobs.mp3", headers=headers)

    assert (own.status_code, own.content) == (200, b"ID3 not really audio")
    assert other.status_code == 404


# -- T3, T4, T5, T25: which tokens count ---------------------------------------------


@pytest.mark.parametrize(
    "claims",
    [
        pytest.param({"azp": "other-client"}, id="t3-azp-not-admitted"),
        pytest.param({"azp": "HAL"}, id="t25-azp-case-differs"),
        pytest.param({"azp": " hal"}, id="t25-azp-padded"),
        pytest.param({"azp": None}, id="t3-no-azp"),
        pytest.param({"aud": "another-app"}, id="t4-foreign-audience"),
        pytest.param({"aud": ["songmaker-test", "another-app"]}, id="t25-shared-audience"),
        pytest.param({"exp": -(OIDC_LEEWAY_SECONDS + 1)}, id="t5-expired-past-leeway"),
    ],
)
def test_a_token_that_is_not_for_this_app_is_refused_as_invalid(
    token_world: TokenWorld, claims: dict[str, object],
) -> None:
    claims = {
        name: (int(token_world.issuer.now) + value if name == "exp" else value)
        for name, value in claims.items()
    }

    response = token_world.client.get("/api/songs", headers=token_world.bearer(**claims))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert token_world.users() == []


# -- T6, T7: rights ------------------------------------------------------------------


def test_t6_a_token_of_a_non_member_is_refused_and_writes_nothing(token_world: TokenWorld) -> None:
    response = token_world.client.get("/api/songs", headers=token_world.bearer(groups=()))

    assert (response.status_code, response.json()) == (403, {"detail": "No access"})
    assert (token_world.users(), token_world.audits()) == ([], [])


def test_t7_an_admin_route_needs_the_admin_group(token_world: TokenWorld) -> None:
    refused = token_world.client.get("/api/admin/voices", headers=token_world.bearer())
    admitted = token_world.client.get(
        "/api/admin/voices",
        headers=token_world.bearer(TokenWorld.BOB, groups=(OIDC_LOGIN_GROUP, OIDC_ADMIN_GROUP)),
    )

    assert (refused.status_code, refused.json()) == (403, {"detail": "Admin access required"})
    assert admitted.status_code == 200


# -- T8, T9, T10, T19, T20: CSRF and the cookie --------------------------------------


def test_t8_a_token_write_without_provenance_passes_csrf_and_is_committed(
    token_world: TokenWorld,
) -> None:
    body = {"title": "From the CLI"}

    without_token = token_world.client.post("/api/albums", json=body)
    with_token = token_world.client.post("/api/albums", json=body, headers=token_world.bearer())

    assert without_token.status_code == 403
    assert with_token.status_code == 200
    assert token_world.albums() == [("From the CLI", TokenWorld.ALICE)]


def test_t9_a_cookie_only_cross_origin_write_is_still_refused(token_world: TokenWorld) -> None:
    with token_world.factory() as session:
        seed_user(session, "cookie-user", user_id=TokenWorld.BOB)
        session.commit()
    seed_session(token_world.client, "cookie-user")

    response = token_world.client.post(
        "/api/albums", json={"title": "Forged"}, headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert token_world.albums() == []


def _a_session_of_bob(token_world: TokenWorld) -> tuple:
    with token_world.factory() as session:
        seed_user(session, "bob", user_id=TokenWorld.BOB)
        session.commit()
    seed_session(token_world.client, "bob")
    return token_world.rows(UserSession, "id", "user_id", "expires_at")


def test_t10_a_token_beside_a_valid_cookie_decides_and_leaves_the_session_alone(
    token_world: TokenWorld,
) -> None:
    session_before = _a_session_of_bob(token_world)

    response = token_world.client.get("/api/auth/me", headers=token_world.bearer(TokenWorld.ALICE))

    assert response.json()["id"] == TokenWorld.ALICE
    assert token_world.rows(UserSession, "id", "user_id", "expires_at") == session_before


def test_t19_a_token_write_beside_another_persons_cookie_belongs_to_the_token(
    token_world: TokenWorld,
) -> None:
    session_before = _a_session_of_bob(token_world)

    response = token_world.client.post(
        "/api/albums", json={"title": "Alices"}, headers=token_world.bearer(TokenWorld.ALICE),
    )

    assert response.status_code == 200
    assert token_world.albums() == [("Alices", TokenWorld.ALICE)]
    assert (TokenWorld.ALICE, "create", "album", response.json()["id"]) in token_world.audits()
    assert token_world.rows(UserSession, "id", "user_id", "expires_at") == session_before


@pytest.mark.parametrize(
    "authorization",
    ["Bearer not-a-token", "Bearer", "Bearer two tokens", "Bearer " + "a" * 3 + "." + "b" * 3],
)
def test_t20_an_invalid_bearer_beside_a_valid_cookie_is_refused_without_a_write(
    token_world: TokenWorld, authorization: str,
) -> None:
    _a_session_of_bob(token_world)

    response = token_world.client.post(
        "/api/albums", json={"title": "Smuggled"}, headers={"Authorization": authorization},
    )

    assert response.status_code == 401
    assert token_world.albums() == []


# -- T11, T12: configuration ---------------------------------------------------------


def test_t11_without_token_clients_a_bearer_is_not_admitted_and_the_app_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOKEN_CLIENTS", "")
    world = make_token_world(tmp_path)

    response = world.client.get("/api/songs", headers=world.bearer())

    assert response.status_code == 401
    assert world.users() == []


@pytest.mark.parametrize("malformed", ["hal,", ",hal", "hal,,other", " "])
def test_t12_a_malformed_token_clients_list_stops_the_app_at_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, malformed: str,
) -> None:
    from songmaker_cli.settings import get_settings

    monkeypatch.setenv("TOKEN_CLIENTS", malformed)
    get_settings.cache_clear()

    with pytest.raises(ValidationError, match="TOKEN_CLIENTS"):
        make_test_app(tmp_path)


# -- T13: the co-writer ----------------------------------------------------------------


def test_t13_the_co_writer_turn_refuses_a_token_before_writing_any_chat_state(
    token_world: TokenWorld,
) -> None:
    response = token_world.client.post(
        "/api/chat/turn", json={"message": "hello"}, headers=token_world.bearer(),
    )

    assert (response.status_code, response.json()) == (
        403, {"detail": "The co-writer needs a browser sign-in."},
    )
    assert token_world.rows(Job, "id") == []
    assert token_world.rows(ChatMessage, "id") == []


# -- T14, T26: what the gate leaves alone ---------------------------------------------


@pytest.mark.parametrize("path", ["/mcp", "/shared/nobody", "/login/oidc", "/auth/callback"])
def test_t14_a_path_outside_the_person_paths_answers_as_without_a_bearer(
    token_world: TokenWorld, path: str,
) -> None:
    def answer(headers: dict[str, str]) -> tuple:
        response = token_world.client.get(path, headers=headers, follow_redirects=False)
        location = urlsplit(response.headers.get("location", ""))
        return response.status_code, (location.netloc, location.path), response.content

    plain = answer({})
    for authorization in (token_world.bearer()["Authorization"], "Bearer garbage"):
        assert answer({"Authorization": authorization}) == plain
    assert token_world.users() == []


@pytest.mark.parametrize(
    ("requested_header", "status"),
    [("content-type", 200), ("authorization", 400)],
)
def test_t26_a_preflight_keeps_authorization_out_of_the_allowed_headers(
    token_world: TokenWorld, requested_header: str, status: int,
) -> None:
    response = token_world.client.options(
        "/api/albums",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": requested_header,
        },
    )

    assert response.status_code == status
    assert "authorization" not in response.headers.get("access-control-allow-headers", "").lower()


# -- T15: the deployment ---------------------------------------------------------------


def test_t15_compose_hands_token_clients_to_the_web_service_only(tmp_path: Path) -> None:
    env_file = tmp_path / "scratch.env"
    env_file.write_text(
        "GRAFANA_PASSWORD=scratch-grafana-password-not-a-secret\n"
        "OIDC_ISSUER=https://keycloak.invalid/realms/scratch\n"
        f"TOKEN_CLIENTS={TokenWorld.HAL}\n",
    )

    result: subprocess.CompletedProcess[str] = run_compose_config(
        ("-f", "docker-compose.yml", "-p", "songmaker-person-token-paths-test"),
        ("--format", "json"),
        env_file=env_file,
        environment={},
    )

    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    carrying = {
        name for name, service in services.items()
        if service.get("environment", {}).get("TOKEN_CLIENTS") == TokenWorld.HAL
    }
    assert carrying == {"songmaker-web"}


# -- T16, T17, T18: the account ---------------------------------------------------------


@pytest.mark.parametrize(
    ("before", "groups", "after"),
    [
        pytest.param("user", (OIDC_LOGIN_GROUP, OIDC_ADMIN_GROUP), "admin", id="promoted"),
        pytest.param("admin", (OIDC_LOGIN_GROUP,), "user", id="demoted"),
    ],
)
def test_t16_the_groups_of_a_token_rewrite_the_stored_role_and_audit_it(
    token_world: TokenWorld, before: str, groups: tuple[str, ...], after: str,
) -> None:
    with token_world.factory() as session:
        seed_user(session, "alice", before, user_id=TokenWorld.ALICE)
        session.commit()

    response = token_world.client.get("/api/songs", headers=token_world.bearer(groups=groups))

    assert response.status_code == 200
    assert token_world.users() == [(TokenWorld.ALICE, "alice", after)]
    assert (None, "update", "user", TokenWorld.ALICE) in token_world.audits()


def _fail_the_audit(_world: TokenWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(_sink: DatabaseAuditSink, _event: object) -> None:
        raise RuntimeError("the audit store is down")

    monkeypatch.setattr(DatabaseAuditSink, "account_event", refuse)


def _fail_the_commit(world: TokenWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    """Let the lock's preliminary commit pass; refuse the one that persists the admission."""
    commits_seen: list[Session] = []

    def refuse_the_admission_commit(session: Session) -> None:
        commits_seen.append(session)
        if len(commits_seen) == 2:
            raise RuntimeError("the transaction cannot commit")

    event.listen(world.factory, "before_commit", refuse_the_admission_commit)


@pytest.mark.parametrize(
    "fail", [_fail_the_audit, _fail_the_commit], ids=["audit-fails", "commit-fails"],
)
def test_t17_a_failing_admission_is_a_500_with_no_account_and_no_session(
    token_world: TokenWorld, monkeypatch: pytest.MonkeyPatch, fail: object,
) -> None:
    fail(token_world, monkeypatch)

    response = token_world.client.get("/api/songs", headers=token_world.bearer())

    assert response.status_code == 500
    assert (token_world.users(), token_world.audits(), token_world.rows(UserSession, "id")) == (
        [], [], [],
    )


# -- T21, T22: deletion and sharing ----------------------------------------------------


def test_t21_a_token_deletes_its_own_album_and_not_anothers(token_world: TokenWorld) -> None:
    token_world.seed_take(TokenWorld.ALICE, "alices")
    token_world.seed_take(TokenWorld.BOB, "bobs")
    headers = token_world.bearer(TokenWorld.ALICE)

    own = token_world.client.delete("/api/albums/album-alices", headers=headers)
    other = token_world.client.delete("/api/albums/album-bobs", headers=headers)

    assert own.status_code == 200
    assert other.status_code == 404
    assert token_world.client.get("/api/albums/album-alices", headers=headers).status_code == 404
    with token_world.factory() as session:
        assert session.get(Album, "album-bobs").deleted_at is None


def test_t22_another_persons_shared_take_stays_private_under_audio_and_public_under_shared(
    token_world: TokenWorld,
) -> None:
    take = token_world.seed_take(TokenWorld.BOB, "bobs")
    bob = token_world.bearer(TokenWorld.BOB, username="bob")
    shared = token_world.client.post(f"/api/generations/{take}/share", headers=bob)
    slug = shared.json()["share_slug"]

    through_audio = token_world.client.get(
        f"/audio/{TokenWorld.BOB}/bobs.mp3", headers=token_world.bearer(TokenWorld.ALICE),
    )
    public_url = token_world.client.get(f"/shared/gen/{slug}").json()["audio_url"]
    through_share = token_world.client.get(public_url)

    assert through_audio.status_code == 404
    assert through_share.status_code == 200


# -- T23, T24: other doors --------------------------------------------------------------


def test_t23_a_bearer_alone_does_not_register_a_worker_and_the_internal_token_still_does(
    token_world: TokenWorld,
) -> None:
    from songmaker_cli.settings import get_settings

    worker = {"worker_id": "w1", "host": "gpu-1", "port": 8001}
    internal = {"X-Internal-Token": get_settings().songmaker_internal_token.get_secret_value()}

    bearer_only = token_world.client.post(
        "/api/internal/workers/register", json=worker, headers=token_world.bearer(),
    )
    worker_request = token_world.client.post(
        "/api/internal/workers/register", json=worker, headers=internal,
    )

    assert bearer_only.status_code == 422
    assert worker_request.status_code == 200


async def _read_stream_until(
    app: ASGIApp, path: str, headers: dict[str, str], *, until: str,
) -> tuple[int, str]:
    """GET a stream through the app's ASGI interface; the client leaves once `until` has arrived."""
    status = 0
    body = ""
    # The request arrives once; a second read of the receive channel never returns.
    receive: asyncio.Queue[dict] = asyncio.Queue()
    receive.put_nowait({"type": "http.request", "body": b"", "more_body": False})

    async def send(message: dict) -> None:
        nonlocal status, body
        if message["type"] == "http.response.start":
            status = message["status"]
        else:
            body += message.get("body", b"").decode()
            if until in body:
                raise OSError("client disconnected")

    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1", "method": "GET", "scheme": "https", "path": path,
        "raw_path": path.encode(), "query_string": b"", "root_path": "",
        "headers": [(b"host", urlsplit(TEST_ORIGIN).netloc.encode())]
        + [(name.lower().encode(), value.encode()) for name, value in headers.items()],
        "client": ("testclient", 50_000), "server": ("testserver", 443),
    }
    with suppress(ClientDisconnect):
        await asyncio.wait_for(app(scope, receive.get, send), timeout=10)
    return status, body


def test_t24_the_event_streams_admit_a_token_and_keep_their_per_person_filter(
    token_world: TokenWorld,
) -> None:
    with token_world.factory() as session:
        seed_user(session, "bob", user_id=TokenWorld.BOB)
        session.add(Job(id="bobs-job", type="generate", status="completed", user_id=TokenWorld.BOB))
        session.commit()
    for owner, name in ((TokenWorld.BOB, "bobs"), (TokenWorld.ALICE, "alices")):
        token_world.seed_take(owner, name)
        with token_world.factory() as session:
            create_generation_created_event(
                session, user_id=owner, song_id=f"song-{name}", generation_id=f"take-{name}",
            )
            session.commit()
    headers = token_world.bearer(TokenWorld.ALICE)

    status, frames = asyncio.run(_read_stream_until(
        token_world.client.app, "/api/resource-events/stream",
        {**headers, "Last-Event-ID": "0"}, until="take-alices",
    ))
    foreign_job = token_world.client.get("/api/jobs/bobs-job/stream", headers=headers)

    assert (status, "event: generation.created" in frames, "take-bobs" in frames) == (
        200, True, False,
    )
    assert foreign_job.status_code == 404

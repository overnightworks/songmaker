"""The co-writer's MCP endpoint (#1832): who may call a tool, with which arguments.

Every case drives songmaker's composition (``compose_mcp_endpoint``) as a raw ASGI app, so
duplicate headers and odd paths reach it as written. The matrix rows (M, K, D) are named in
the test names.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import jwt
import pytest
from agent_runtime_client.capability import CAPABILITY_TOKEN_TYPE
from agent_runtime_client.mcp_server import CapabilityVerificationKey, UnsoundVerificationKey
from conftest import make_test_app
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from songmaker_cli.cowriter import service_runs
from songmaker_cli.cowriter.mcp_endpoint import (
    CAPABILITY_AGENT,
    McpKeyProblem,
    compose_mcp_endpoint,
    cowriter_mcp_availability,
)
from songmaker_cli.cowriter.service_runs import RunPerson
from songmaker_cli.cowriter.tools import COWRITER_TOOLS
from songmaker_cli.db.models import Album, Generation, Job, Score, Song, User, Version
from songmaker_cli.server import run_server
from songmaker_cli.settings import get_settings

ORIGIN = "https://songmaker.mcp.internal"
HOST = b"songmaker.mcp.internal"
ISSUER = "https://issuer.test/realms/test"
VERSION = "2025-11-25"
LIFETIME = 600
ALL_TOOLS = tuple(tool.name for tool in COWRITER_TOOLS)
MEGABYTE = 1024 * 1024


def _public_pem(private_key: rsa.RSAPrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _private_pem(private_key: rsa.RSAPrivateKey) -> bytes:
    return private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


@pytest.fixture(scope="module")
def foreign_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


def settings_now():
    """Settings as the environment stands now, whatever an earlier fixture cached."""
    get_settings.cache_clear()
    return get_settings()


def mint(
    signing_key: rsa.RSAPrivateKey,
    run_id: str,
    *,
    person: tuple[str, str] = (ISSUER, "anna"),
    app: str = "songmaker",
    agent: str | None = CAPABILITY_AGENT,
    token_type: str = CAPABILITY_TOKEN_TYPE,
    extra_claims: dict[str, Any] | None = None,
    audience: str = ORIGIN,
    tools: tuple[str, ...] = ALL_TOOLS,
    issued_at: float | None = None,
    lifetime: int = LIFETIME,
) -> str:
    issued = int(time.time() if issued_at is None else issued_at)
    claims = {
        "iss": "agent-service",
        "aud": audience,
        "sub": run_id,
        "iat": issued,
        "exp": issued + lifetime,
        "app": app,
        "principal": {"iss": person[0], "sub": person[1]},
        "tools": list(tools),
        **({} if agent is None else {"agent": agent}),
        **(extra_claims or {}),
    }
    return jwt.encode(
        claims,
        _private_pem(signing_key),
        algorithm="RS256",
        headers={"kid": "test-key", "typ": token_type},
    )


@dataclass
class Reply:
    status: int
    body: bytes

    def tool_result(self) -> tuple[bool, str]:
        assert self.status == 200, self.body
        result = json.loads(self.body)["result"]
        return result["isError"], result["content"][0]["text"]


def drive(
    app: Any,
    headers: list[tuple[bytes, bytes]],
    body: bytes = b"",
    *,
    path: str = "/mcp",
    method: str = "POST",
    receive: Callable[[], Any] | None = None,
) -> Reply:
    sent: list[dict[str, Any]] = []
    inbox = [{"type": "http.request", "body": body, "more_body": False}]

    async def default_receive() -> dict[str, Any]:
        return inbox.pop(0) if inbox else {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": b"",
        "headers": headers,
        "client": ("172.18.0.5", 40000),
    }
    asyncio.run(app(scope, receive or default_receive, send))
    start = next(message for message in sent if message["type"] == "http.response.start")
    reply_body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return Reply(start["status"], reply_body)


def headers_for(
    token: str | None, *, host: bytes = HOST, extra: tuple[tuple[bytes, bytes], ...] = (),
) -> list[tuple[bytes, bytes]]:
    headers = [(b"host", host), (b"mcp-protocol-version", VERSION.encode()), *extra]
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    return headers


def rpc(method: str, params: dict[str, Any] | None = None) -> bytes:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        message["params"] = params
    return json.dumps(message).encode()


def call_body(name: str, **arguments: Any) -> bytes:
    return rpc("tools/call", {"name": name, "arguments": arguments})


def _seed(session) -> None:
    for identity in ("anna", "ben"):
        session.add(User(id=identity, username=identity, role="user"))
        session.flush()
        session.add(Album(
            id=f"album-{identity}", title=identity, artist=identity, created_by=identity,
        ))
        session.add(Song(
            id=f"song-{identity}", title=f"Track {identity}",
            album_id=f"album-{identity}", track_number=1,
        ))
        session.add(Version(
            id=f"version-{identity}", song_id=f"song-{identity}",
            version_number=1, lyrics="original", prompt="rock",
        ))
        take = f"generation-{identity}"
        session.add(Generation(
            id=take, song_id=f"song-{identity}", version_id=f"version-{identity}",
            generation_number=1, mp3_path=f"{identity}/take.mp3", whisper_text="sung words",
        ))
        session.add(Score(generation_id=take, scorer="batch", value={"bpm_detected": 96.0}))


@dataclass
class Endpoint:
    app: Any
    factory: Any

    def snapshot(self) -> tuple[list[tuple[str, str]], int]:
        with self.factory() as session:
            versions = sorted(
                (version.song_id, version.lyrics) for version in session.query(Version)
            )
            return versions, session.query(Job).count()

    def call(self, token: str, name: str, **arguments: Any) -> Reply:
        return drive(self.app, headers_for(token), call_body(name, **arguments))


@pytest.fixture
def mcp_environment(tmp_path, monkeypatch, signing_key):
    key_file = tmp_path / "public.pem"
    key_file.write_bytes(_public_pem(signing_key))
    monkeypatch.setenv("AGENT_SERVICE_MCP_ORIGIN", ORIGIN)
    monkeypatch.setenv("AGENT_SERVICE_CAPABILITY_KEY_FILE", str(key_file))
    return key_file


@pytest.fixture
def web(tmp_path, mcp_environment):
    client, factory = make_test_app(tmp_path, seed_db=_seed)
    return client.app, factory


@pytest.fixture
def endpoint(web, mcp_environment) -> Endpoint:
    app, factory = web
    wrapped, verdict = compose_mcp_endpoint(app, settings_now())
    assert verdict.problem is None
    return Endpoint(wrapped, factory)


@contextmanager
def running_run(run_id: str, person: str = "anna") -> Iterator[None]:
    service_runs.register(run_id, RunPerson(ISSUER, person))
    try:
        yield
    finally:
        service_runs.release(run_id)


@pytest.fixture
def run_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def capability(signing_key, run_id) -> str:
    return mint(signing_key, run_id)


# ── M1 to M8: the tools ──────────────────────────────────────────────


def test_m1_tools_list_offers_exactly_the_capabilitys_tools_with_the_declarations(
    endpoint, signing_key, run_id,
):
    offered = ("get_song", "update_song_lyrics")
    token = mint(signing_key, run_id, tools=offered)
    with running_run(run_id):
        reply = drive(endpoint.app, headers_for(token), rpc("tools/list"))

    listed = json.loads(reply.body)["result"]["tools"]
    declared = {tool.name: tool for tool in COWRITER_TOOLS}
    assert sorted(tool["name"] for tool in listed) == sorted(offered)
    for tool in listed:
        assert tool["inputSchema"] == declared[tool["name"]].parameters
        assert tool["description"] == declared[tool["name"]].description


def test_m1_tools_list_offers_every_cowriter_tool_to_a_full_capability(endpoint, capability):
    reply = drive(endpoint.app, headers_for(capability), rpc("tools/list"))

    listed = json.loads(reply.body)["result"]["tools"]
    assert [tool["name"] for tool in listed] == [tool.name for tool in COWRITER_TOOLS]


def test_m2_a_read_and_a_write_on_the_persons_own_song_succeed_and_the_write_commits_one_version(
    endpoint, capability, run_id,
):
    with running_run(run_id):
        read_error, read_text = endpoint.call(
            capability, "get_song", song_id="song-anna",
        ).tool_result()
        versions_before, _ = endpoint.snapshot()
        write_error, _ = endpoint.call(
            capability, "update_song_lyrics", song_id="song-anna", lyrics="new words",
        ).tool_result()
        versions_after, _ = endpoint.snapshot()

    assert read_error is False
    assert "Track anna" in read_text
    assert write_error is False
    assert len(versions_after) == len(versions_before) + 1
    assert ("song-anna", "new words") in versions_after


def test_m3_a_call_on_another_persons_song_is_not_found_and_changes_no_row(
    endpoint, capability, run_id,
):
    before = endpoint.snapshot()
    with running_run(run_id):
        read = endpoint.call(capability, "get_song", song_id="song-ben").tool_result()
        write = endpoint.call(
            capability, "update_song_lyrics", song_id="song-ben", lyrics="stolen",
        ).tool_result()

    assert read[0] is True
    assert "not found" in read[1]
    assert write[0] is True
    assert "not found" in write[1]
    assert endpoint.snapshot() == before


@pytest.mark.parametrize(
    ("owner", "stored"), [("anna", True), ("ben", False)], ids=["own take", "foreign take"])
def test_the_coherence_verdict_is_stored_on_the_persons_own_take_only(
    endpoint, capability, run_id, owner, stored,
):
    with running_run(run_id):
        is_error, text = endpoint.call(
            capability, "save_coherence_verdict",
            generation_id=f"generation-{owner}", score=8, summary="Coherent.").tool_result()

    assert is_error is not stored
    with endpoint.factory() as session:
        values = {row.generation_id: dict(row.value) for row in session.query(Score)}
    assert values["generation-ben"] == {"bpm_detected": 96.0}
    assert (values["generation-anna"].get("lyrical_coherence") == 8) is stored
    assert stored or text == "Generation not found"
    assert not stored or json.loads(text)["scores"]["lyrical_coherence"] == 8


def _refused_write(endpoint: Endpoint, token: str) -> tuple[bool, str]:
    return endpoint.call(
        token, "update_song_lyrics", song_id="song-anna", lyrics="refused words",
    ).tool_result()


def test_m4_a_valid_capability_whose_run_is_not_registered_is_refused_and_runs_no_handler(
    endpoint, capability,
):
    before = endpoint.snapshot()

    is_error, _ = _refused_write(endpoint, capability)

    assert is_error is True
    assert endpoint.snapshot() == before


def test_m5_a_registered_run_held_by_another_person_is_refused(endpoint, capability, run_id):
    before = endpoint.snapshot()
    with running_run(run_id, person="ben"):
        is_error, _ = _refused_write(endpoint, capability)

    assert is_error is True
    assert endpoint.snapshot() == before


def test_a_trailing_slash_on_the_configured_issuer_still_lets_the_tool_call_through(
    web, mcp_environment, monkeypatch, capability, run_id,
):
    """defect:#1896: the issuer is compared without its trailing slash."""
    monkeypatch.setenv("OIDC_ISSUER", f"{ISSUER}/")
    app, factory = web
    wrapped, verdict = compose_mcp_endpoint(app, settings_now())
    assert verdict.problem is None
    try:
        with running_run(run_id):
            is_error, _ = Endpoint(wrapped, factory).call(
                capability, "get_song", song_id="song-anna",
            ).tool_result()
    finally:
        get_settings.cache_clear()

    assert is_error is False


def test_m5_a_registered_run_held_by_the_same_subject_of_another_issuer_is_refused(
    endpoint, capability, run_id,
):
    service_runs.register(run_id, RunPerson("https://other.issuer/realms/x", "anna"))
    try:
        is_error, _ = _refused_write(endpoint, capability)
    finally:
        service_runs.release(run_id)

    assert is_error is True


def test_c4_a_run_id_that_is_already_registered_is_not_registered_again(run_id):
    other_person = RunPerson(ISSUER, "ben")
    with running_run(run_id, person="anna"):
        with pytest.raises(service_runs.RunAlreadyRegisteredError):
            service_runs.register(run_id, other_person)

        assert service_runs.holder(run_id) == RunPerson(ISSUER, "anna")


def test_m6_the_same_capability_after_the_turn_ended_is_refused(endpoint, capability, run_id):
    with running_run(run_id):
        accepted, _ = endpoint.call(capability, "get_song", song_id="song-anna").tool_result()
    before = endpoint.snapshot()

    replayed, _ = _refused_write(endpoint, capability)

    assert accepted is False
    assert replayed is True
    assert endpoint.snapshot() == before


def test_m6_a_capability_of_an_earlier_run_is_refused_during_the_next_turn_of_the_same_person(
    endpoint, signing_key,
):
    earlier, current = str(uuid.uuid4()), str(uuid.uuid4())
    with running_run(current):
        is_error, _ = _refused_write(endpoint, mint(signing_key, earlier))

    assert is_error is True


@pytest.mark.parametrize(
    "claim_changes",
    [
        {"app": "other-app"},
        {"agent": "other-agent"},
        {"person": ("https://other.issuer/realms/x", "anna")},
    ],
    ids=["app", "agent", "issuer"],
)
def test_m7_a_capability_for_another_app_agent_or_issuer_is_refused(
    endpoint, signing_key, run_id, claim_changes,
):
    token = mint(signing_key, run_id, **claim_changes)
    service_runs.register(
        run_id, RunPerson(claim_changes.get("person", (ISSUER, "anna"))[0], "anna"),
    )
    before = endpoint.snapshot()
    try:
        is_error, _ = _refused_write(endpoint, token)
    finally:
        service_runs.release(run_id)

    assert is_error is True
    assert endpoint.snapshot() == before


@pytest.mark.parametrize(
    ("name", "arguments", "named_field"),
    [
        ("update_song_lyrics", {"song_id": "song-anna", "lyrics": None}, "lyrics"),
        ("update_song_style", {"song_id": "song-anna", "bpm": "120"}, "bpm"),
        ("update_song_style", {"song_id": "song-anna", "bpm": True}, "bpm"),
        ("update_song_lyrics", {"lyrics": "words"}, "song_id"),
        ("update_song_lyrics", {"song_id": "song-anna", "lyrics": "x", "extra": 1}, "extra"),
        ("suggest_album_cover", {"album_id": 7}, "album_id"),
    ],
)
def test_m8_malformed_arguments_are_a_tool_error_naming_the_field_and_change_nothing(
    endpoint, capability, run_id, name, arguments, named_field,
):
    before = endpoint.snapshot()
    with running_run(run_id):
        is_error, text = endpoint.call(capability, name, **arguments).tool_result()

    assert is_error is True
    assert named_field in text
    assert endpoint.snapshot() == before


# ── M9 to M11: the head checks ───────────────────────────────────────


def _token(kind: str, signing_key, foreign_key, run_id) -> str | None:
    now = time.time()
    return {
        "valid": lambda: mint(signing_key, run_id),
        "wrong-audience": lambda: mint(signing_key, run_id, audience="https://other.mcp.internal"),
        "foreign-key": lambda: mint(foreign_key, run_id),
        "unsigned": lambda: "e30.e30.",
        "expired": lambda: mint(signing_key, run_id, issued_at=now - 2 * LIFETIME),
        "old-type": lambda: mint(signing_key, run_id, token_type="agent-capability+jwt"),
        "purpose-claim": lambda: mint(
            signing_key, run_id, agent=None, extra_claims={"purpose": "cowriter"},
        ),
        "purpose-beside-agent": lambda: mint(
            signing_key, run_id, extra_claims={"purpose": "cowriter"},
        ),
        "no-agent": lambda: mint(signing_key, run_id, agent=None),
    }[kind]()


@pytest.mark.parametrize(
    ("kind", "status"),
    [
        ("wrong-audience", 401), ("foreign-key", 401), ("unsigned", 401), ("expired", 401),
        ("old-type", 401), ("purpose-claim", 401), ("purpose-beside-agent", 401),
        ("no-agent", 401),
    ],
)
def test_m9_a_capability_that_does_not_verify_is_401_with_an_empty_body(
    endpoint, signing_key, foreign_key, run_id, kind, status,
):
    token = _token(kind, signing_key, foreign_key, run_id)

    reply = drive(endpoint.app, headers_for(token), rpc("tools/list"))

    assert (reply.status, reply.body) == (status, b"")


def test_m9_a_wrong_host_is_403_with_an_empty_body(endpoint, capability):
    reply = drive(endpoint.app, headers_for(capability, host=b"songmaker-web:8080"), rpc("ping"))

    assert (reply.status, reply.body) == (403, b"")


def test_m9_any_origin_header_is_403_with_an_empty_body(endpoint, capability):
    reply = drive(
        endpoint.app,
        headers_for(capability, extra=((b"origin", b"https://songmaker.mcp.internal"),)),
        rpc("ping"),
    )

    assert (reply.status, reply.body) == (403, b"")


def test_m9_two_authorization_headers_are_401_with_an_empty_body(endpoint, capability):
    reply = drive(
        endpoint.app,
        headers_for(capability, extra=((b"authorization", f"Bearer {capability}".encode()),)),
        rpc("ping"),
    )

    assert (reply.status, reply.body) == (401, b"")


@pytest.mark.parametrize(
    ("method", "path", "status"), [("GET", "/mcp", 405), ("POST", "/mcp/x", 404)],
)
def test_m9_another_method_or_path_is_refused_with_an_empty_body(
    endpoint, capability, method, path, status,
):
    reply = drive(endpoint.app, headers_for(capability), rpc("ping"), path=path, method=method)

    assert (reply.status, reply.body) == (status, b"")


def test_m9_a_body_over_one_mebibyte_is_413_with_an_empty_body(endpoint, capability):
    reply = drive(endpoint.app, headers_for(capability), b"x" * (MEGABYTE + 1))

    assert (reply.status, reply.body) == (413, b"")


def test_m10_a_request_without_authorization_is_refused_before_its_body_is_read(endpoint):
    async def never_read() -> dict[str, Any]:
        raise AssertionError("the body was read")

    reply = drive(endpoint.app, headers_for(None), receive=never_read)

    assert (reply.status, reply.body) == (401, b"")


def test_m11_neither_the_logs_nor_the_answers_carry_the_capability(
    endpoint, capability, signing_key, foreign_key, run_id, caplog,
):
    signature = capability.rsplit(".", 1)[-1]
    answers = []
    with caplog.at_level(logging.DEBUG), running_run(run_id):
        answers.append(drive(endpoint.app, headers_for(capability), rpc("tools/list")))
        answers.append(endpoint.call(capability, "get_song", song_id="song-anna"))
        answers.append(endpoint.call(capability, "get_song", song_id="song-ben"))
        answers.append(endpoint.call(capability, "update_song_lyrics", song_id="song-anna"))
        answers.append(endpoint.call(capability, "no_such_tool"))
    answers.append(endpoint.call(capability, "get_song"))
    answers.append(drive(
        endpoint.app, headers_for(_token("expired", signing_key, foreign_key, run_id)), rpc("ping"),
    ))

    assert all(signature.encode() not in reply.body for reply in answers)
    assert signature not in caplog.text


# ── K1 to K3: a missing or malformed key leaves the web up ───────────


def _two_blocks(signing_key: rsa.RSAPrivateKey) -> bytes:
    return _public_pem(signing_key) + _public_pem(signing_key)


KEY_FILE_CASES = {
    "empty": (lambda path, key: path.write_bytes(b""), McpKeyProblem.UNSOUND_KEY),
    "two-blocks": (lambda path, key: path.write_bytes(_two_blocks(key)), McpKeyProblem.UNSOUND_KEY),
    "private-key": (
        lambda path, key: path.write_bytes(_private_pem(key)), McpKeyProblem.UNSOUND_KEY,
    ),
    "rsa-2048": (
        lambda path, key: path.write_bytes(
            _public_pem(rsa.generate_private_key(public_exponent=65537, key_size=2048)),
        ),
        McpKeyProblem.UNSOUND_KEY,
    ),
    "directory": (lambda path, key: path.mkdir(), McpKeyProblem.NOT_A_FILE),
    "missing": (lambda path, key: None, McpKeyProblem.MISSING),
}


@pytest.fixture
def broken_key(request, mcp_environment, signing_key) -> McpKeyProblem:
    mcp_environment.unlink()
    arrange, problem = KEY_FILE_CASES[request.param]
    arrange(mcp_environment, signing_key)
    return problem


@pytest.mark.parametrize("broken_key", list(KEY_FILE_CASES), indirect=True)
def test_k1_to_k3_a_broken_key_file_leaves_the_web_up_and_mcp_answering_503(
    broken_key, web, mcp_environment, signing_key, caplog, mock_arq_pool,
):
    app, _ = web
    served: dict[str, Any] = {}

    with (
        caplog.at_level(logging.INFO),
        patch("uvicorn.run", side_effect=lambda wrapped, **_: served.update(app=wrapped)),
        patch("songmaker_cli.server.create_app", return_value=app),
    ):
        run_server(project_root=mcp_environment.parent, port=9999)

    wrapped = served["app"]
    with TestClient(wrapped, base_url="https://testserver") as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/songs").status_code == 401
    mcp_replies = [
        drive(wrapped, headers_for(token), rpc("tools/list"))
        for token in (mint(signing_key, str(uuid.uuid4())), None)
    ]
    assert [(reply.status, reply.body) for reply in mcp_replies] == [(503, b"")] * 2
    verdict_lines = [r.getMessage() for r in caplog.records if "agent_service" in r.getMessage()]
    assert len(verdict_lines) == 1
    assert "agent_service_capability_key_file" in verdict_lines[0]
    assert broken_key.value in verdict_lines[0]
    assert "BEGIN" not in caplog.text


@pytest.mark.parametrize(
    "broken_key", ["empty", "two-blocks", "private-key", "rsa-2048"], indirect=True,
)
def test_k3_an_unsound_key_is_logged_with_the_rule_the_verifier_names_never_the_bytes(
    broken_key, web, mcp_environment, caplog,
):
    app, _ = web
    pem = mcp_environment.read_bytes()
    with pytest.raises(UnsoundVerificationKey) as rule:
        CapabilityVerificationKey.from_pem(pem)

    with caplog.at_level(logging.INFO):
        _, verdict = compose_mcp_endpoint(app, settings_now())

    assert verdict.problem is McpKeyProblem.UNSOUND_KEY
    assert str(rule.value) in caplog.text
    assert "BEGIN" not in caplog.text


@pytest.mark.parametrize("locked", ["file", "parent_directory"])
def test_k_an_unreadable_key_file_is_unavailable_unreadable(web, mcp_environment, locked):
    (mcp_environment if locked == "file" else mcp_environment.parent).chmod(0)
    app, _ = web
    try:
        _, verdict = compose_mcp_endpoint(app, settings_now())
    finally:
        mcp_environment.parent.chmod(0o700)

    assert verdict.problem is McpKeyProblem.UNREADABLE


@pytest.mark.parametrize(
    ("origin", "problem"),
    [
        (None, McpKeyProblem.ORIGIN_MISSING),
        ("http://songmaker.mcp.internal", McpKeyProblem.ORIGIN_INVALID),
    ],
)
def test_k_a_missing_or_invalid_origin_leaves_mcp_answering_503(
    web, mcp_environment, monkeypatch, origin, problem,
):
    if origin is None:
        monkeypatch.delenv("AGENT_SERVICE_MCP_ORIGIN")
    else:
        monkeypatch.setenv("AGENT_SERVICE_MCP_ORIGIN", origin)
    app, _ = web

    wrapped, verdict = compose_mcp_endpoint(app, settings_now())

    assert verdict.problem is problem
    assert drive(wrapped, headers_for(None), rpc("ping")).status == 503


def _surrogate_description(tools):
    return [replace(tools[0], description="\ud800"), *tools[1:]], "\ud800"


def _surrogate_property_name(tools):
    parameters = {
        "type": "object",
        "properties": {"\ud800": {"type": "string"}},
        "additionalProperties": False,
    }
    return [replace(tools[0], parameters=parameters), *tools[1:]], "\ud800"


def _duplicate_tool_name(tools):
    return [*tools, tools[0]], tools[0].name


@pytest.mark.parametrize(
    "declare_rejected_tools",
    [_surrogate_description, _surrogate_property_name, _duplicate_tool_name],
)
def test_k_a_tool_declaration_the_mcp_library_rejects_leaves_mcp_answering_503(
    web, mcp_environment, monkeypatch, caplog, declare_rejected_tools,
):
    rejected_tools, content = declare_rejected_tools(COWRITER_TOOLS)
    monkeypatch.setattr("songmaker_cli.cowriter.mcp_endpoint.COWRITER_TOOLS", rejected_tools)
    app, _ = web

    with caplog.at_level(logging.WARNING):
        wrapped, verdict = compose_mcp_endpoint(app, settings_now())

    assert verdict.problem is McpKeyProblem.TOOLS_INVALID
    assert drive(wrapped, headers_for(None), rpc("ping")).status == 503
    assert content not in caplog.text


def test_k_an_unset_key_file_setting_is_unavailable_missing(web, monkeypatch):
    monkeypatch.delenv("AGENT_SERVICE_CAPABILITY_KEY_FILE")
    app, _ = web

    _, verdict = compose_mcp_endpoint(app, settings_now())

    assert verdict.problem is McpKeyProblem.MISSING


# ── D1: the MCP name opens nothing else ──────────────────────────────


def test_d1_a_non_mcp_path_with_the_mcp_host_is_400_from_the_host_check(web, endpoint):
    client = TestClient(endpoint.app, base_url=ORIGIN)
    replies = [client.get("/health"), client.get("/api/songs"), client.get("/mcpx")]

    assert [reply.status_code for reply in replies] == [400, 400, 400]


def test_run_server_serves_mcp_outside_the_middleware_with_the_ci_fixture_key(
    tmp_path, monkeypatch,
):
    """An unauthenticated /mcp call meets the endpoint's own head checks: 401 with an empty
    body, where the Host check of the middleware would answer 400."""
    fixture_key = Path(__file__).parent / "fixtures" / "agent_service_capability_public_key.pem"
    monkeypatch.setenv("AGENT_SERVICE_MCP_ORIGIN", ORIGIN)
    monkeypatch.setenv("AGENT_SERVICE_CAPABILITY_KEY_FILE", str(fixture_key))
    client, _ = make_test_app(tmp_path)
    served: dict[str, Any] = {}

    with (
        patch("uvicorn.run", side_effect=lambda wrapped, **_: served.update(app=wrapped)),
        patch("songmaker_cli.server.create_app", return_value=client.app),
    ):
        run_server(project_root=tmp_path)

    reply = drive(served["app"], headers_for(None), rpc("ping"))
    assert (reply.status, reply.body) == (401, b"")


def test_c20_run_server_publishes_the_mcp_verdict_for_the_turns_pre_run_guard(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.delenv("AGENT_SERVICE_CAPABILITY_KEY_FILE", raising=False)
    monkeypatch.delenv("AGENT_SERVICE_MCP_ORIGIN", raising=False)
    settings_now()
    app = make_test_app(tmp_path)[0].app
    assert cowriter_mcp_availability(app).problem is McpKeyProblem.NOT_COMPOSED

    with (
        patch("uvicorn.run"),
        patch("songmaker_cli.server.create_app", return_value=app),
    ):
        run_server(project_root=tmp_path, port=9999)

    assert cowriter_mcp_availability(app).problem is McpKeyProblem.ORIGIN_MISSING

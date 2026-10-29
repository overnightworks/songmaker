"""Drive the co-writer's MCP endpoint as a raw ASGI app, with capabilities minted for it."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import jwt
from agent_runtime_client.capability import CAPABILITY_TOKEN_TYPE
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from songmaker_cli.cowriter import service_runs
from songmaker_cli.cowriter.mcp_endpoint import CAPABILITY_AGENT
from songmaker_cli.cowriter.service_runs import RunPerson
from songmaker_cli.cowriter.tools import COWRITER_TOOLS
from songmaker_cli.settings import get_settings

ORIGIN = "https://songmaker.mcp.internal"
HOST = b"songmaker.mcp.internal"
ISSUER = "https://issuer.test/realms/test"
VERSION = "2025-11-25"
LIFETIME = 600
ALL_TOOLS = tuple(tool.name for tool in COWRITER_TOOLS)


def public_pem(private_key: rsa.RSAPrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def private_pem(private_key: rsa.RSAPrivateKey) -> bytes:
    return private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


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
        private_pem(signing_key),
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


@contextmanager
def running_run(run_id: str, person: str = "anna") -> Iterator[None]:
    service_runs.register(run_id, RunPerson(ISSUER, person))
    try:
        yield
    finally:
        service_runs.release(run_id)

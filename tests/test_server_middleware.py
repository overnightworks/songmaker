"""Tests for the server's middleware: `SelectiveGZipMiddleware` and the stack order."""

from __future__ import annotations

import asyncio
import gzip as gzip_stdlib
import io
import json
import logging
from dataclasses import replace
from pathlib import Path

import anyio
import pytest
from conftest import issued_cookies, make_test_app
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from starlette.middleware.trustedhost import TrustedHostMiddleware
from webauth.config import install_web_auth_config, installed_web_auth_config
from webauth.middleware import (
    BodySizeLimitMiddleware,
    CsrfOriginMiddleware,
    IpRateLimitMiddleware,
    SecurityHeadersMiddleware,
)

from songmaker_cli.constants import GZIP_COMPRESS_LEVEL, GZIP_MINIMUM_SIZE_BYTES, LOGOUT_PATH
from songmaker_cli.middleware.access_log import AccessLogMiddleware
from songmaker_cli.middleware.gzip import SelectiveGZipMiddleware, _accepts_gzip
from songmaker_cli.middleware.resource_stream_deadline import ResourceStreamDeadlineMiddleware

_LARGE_JSON_PAYLOAD = {"lyrics": "la " * 1000}
_TINY_JSON_PAYLOAD = {"status": "ok"}
_LARGE_AUDIO_BODY = b"\x00" * 4096
_LARGE_IMAGE_BODY = b"\xff\xd8\xff" + b"\x00" * 4096
_LARGE_JS_BODY = b"const x = 1;\n" * 200
_SSE_CHUNKS = [f"data: chunk-{i}-{'x' * 200}\n\n".encode() for i in range(6)]
_JSON_STREAM_CHUNKS = [b'{"items": [', b'"a"' * 300, b", ", b'"b"' * 300, b"]}"]


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/songs/s1")
    def get_song():
        return _LARGE_JSON_PAYLOAD

    @app.get("/api/health")
    def health():
        return _TINY_JSON_PAYLOAD

    @app.get("/audio/u-test/g1.mp3")
    def get_audio() -> Response:
        return Response(content=_LARGE_AUDIO_BODY, media_type="audio/mpeg")

    @app.get("/shared/slug/cover")
    def get_cover() -> Response:
        return Response(content=_LARGE_IMAGE_BODY, media_type="image/jpeg")

    @app.get("/api/range-test")
    def get_range() -> Response:
        return Response(
            content=("la " * 1000),
            media_type="text/plain",
            status_code=206,
            headers={"Content-Range": "bytes 0-99/3000"},
        )

    @app.get("/_app/immutable/bundle.js")
    def get_bundle() -> Response:
        return Response(
            content=_LARGE_JS_BODY,
            media_type="application/javascript",
            headers={"Accept-Ranges": "bytes"},
        )

    app.add_middleware(
        SelectiveGZipMiddleware,
        minimum_size=GZIP_MINIMUM_SIZE_BYTES,
        compresslevel=GZIP_COMPRESS_LEVEL,
    )
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_build_app())


def test_large_json_response_is_gzip_compressed(client: TestClient) -> None:
    resp = client.get("/api/songs/s1", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") == "gzip"
    assert resp.headers.get("vary") == "Accept-Encoding"


def test_tiny_json_response_is_not_gzip_compressed(client: TestClient) -> None:
    resp = client.get("/api/health", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers


def test_compressible_response_gets_vary_even_without_client_gzip_support(
    client: TestClient,
) -> None:
    """A cache must know this resource varies by encoding for *any* client,
    not just ones that happened to request gzip -- otherwise it could serve
    this client's uncompressed copy to a gzip-capable one, or vice versa.
    """
    resp = client.get("/api/songs/s1", headers={"Accept-Encoding": "identity"})
    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers
    assert resp.headers.get("vary") == "Accept-Encoding"


@pytest.mark.parametrize(
    ("accept_encoding", "expects_gzip"),
    [
        ("", False),
        ("*", True),
        ("*;q=0", False),
        ("*;q=0, gzip", True),
        ("gzip;q=0", False),
        ("gzip;Q=0", False),
        ("identity;q=0", False),
        ("br, gzip;q=0.8", True),
    ],
)
def test_accepts_gzip_negotiation(accept_encoding: str, expects_gzip: bool) -> None:
    assert _accepts_gzip(accept_encoding) is expects_gzip


def test_audio_response_is_never_gzip_compressed(client: TestClient) -> None:
    resp = client.get("/audio/u-test/g1.mp3", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers
    assert resp.content == _LARGE_AUDIO_BODY


def test_cover_image_response_is_never_gzip_compressed(client: TestClient) -> None:
    resp = client.get("/shared/slug/cover", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers
    assert resp.content == _LARGE_IMAGE_BODY


def test_partial_content_response_is_never_gzip_compressed(client: TestClient) -> None:
    resp = client.get("/api/range-test", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 206
    assert "content-encoding" not in resp.headers
    assert resp.headers["content-range"] == "bytes 0-99/3000"


def test_static_bundle_is_compressed_and_loses_accept_ranges(client: TestClient) -> None:
    """A `FileResponse`-served JS/CSS asset (e.g. the SvelteKit `/_app`
    bundle) always carries `Accept-Ranges: bytes` -- that must not exclude
    it from compression, and once compressed the header must be dropped
    (byte offsets into the gzip stream no longer match the original file).
    """
    resp = client.get(
        "/_app/immutable/bundle.js", headers={"Accept-Encoding": "gzip"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") == "gzip"
    assert "accept-ranges" not in resp.headers
    assert resp.content == _LARGE_JS_BODY


async def _drive_middleware(app, headers: list[tuple[bytes, bytes]]) -> tuple[dict, list[bytes]]:
    """Send one GET request straight into an ASGI app's `send` callable.

    Bypasses TestClient/httpx entirely: httpx's response reading re-buffers
    at its own internal boundary, hiding the individual ASGI messages a
    middleware actually emits. This is the only layer where "one send per
    source chunk, no accumulation" and the exact header set are observable,
    matching the pattern `test_body_size_streaming_too_large` in
    `test_server.py` already uses for `BodySizeLimitMiddleware`.
    """
    start_message: dict = {}
    body_messages: list[bytes] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            start_message.update(message)
        elif message["type"] == "http.response.body":
            body_messages.append(message.get("body", b""))

    scope = {"type": "http", "method": "GET", "path": "/api/stream", "headers": headers}
    await app(scope, receive, send)
    return start_message, body_messages


def test_sse_stream_is_never_gzip_compressed_and_forwards_each_chunk_immediately() -> None:
    async def sse_app(scope, receive, send) -> None:
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"text/event-stream"]],
        })
        for i, chunk in enumerate(_SSE_CHUNKS):
            await send({
                "type": "http.response.body",
                "body": chunk,
                "more_body": i < len(_SSE_CHUNKS) - 1,
            })

    middleware = SelectiveGZipMiddleware(
        sse_app, minimum_size=GZIP_MINIMUM_SIZE_BYTES, compresslevel=GZIP_COMPRESS_LEVEL,
    )

    start_message, body_messages = asyncio.run(
        _drive_middleware(middleware, [(b"accept-encoding", b"gzip")]),
    )

    headers = dict(start_message["headers"])
    assert b"content-encoding" not in headers
    assert body_messages == _SSE_CHUNKS


def test_streaming_json_response_is_compressed_chunk_by_chunk() -> None:
    """A multi-chunk `application/json` `StreamingResponse` (unknown final
    size up front) must still compress: `Content-Length` can't be set (the
    compressed size isn't known until the stream ends), so it's removed
    instead, and `Vary` is set on the single deferred `http.response.start`.
    """

    async def streaming_json_app(scope, receive, send) -> None:
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                [b"content-type", b"application/json"],
                [b"content-length", b"9999"],
            ],
        })
        for i, chunk in enumerate(_JSON_STREAM_CHUNKS):
            await send({
                "type": "http.response.body",
                "body": chunk,
                "more_body": i < len(_JSON_STREAM_CHUNKS) - 1,
            })

    middleware = SelectiveGZipMiddleware(
        streaming_json_app,
        minimum_size=GZIP_MINIMUM_SIZE_BYTES,
        compresslevel=GZIP_COMPRESS_LEVEL,
    )

    start_message, body_messages = asyncio.run(
        _drive_middleware(middleware, [(b"accept-encoding", b"gzip")]),
    )

    headers = dict(start_message["headers"])
    assert headers[b"content-encoding"] == b"gzip"
    assert headers[b"vary"] == b"Accept-Encoding"
    assert b"content-length" not in headers
    assert len(body_messages) == len(_JSON_STREAM_CHUNKS)

    decompressed = gzip_stdlib.decompress(b"".join(body_messages))
    assert decompressed == b"".join(_JSON_STREAM_CHUNKS)


def test_created_app_stacks_its_middleware_in_the_documented_security_order(
    tmp_path: Path,
) -> None:
    """defect:#1590, defect:#1521 -- pin the security-critical middleware order.

    Outermost first, because Starlette runs the last-added layer first. CORS is
    registered for every configuration (`CORS_ORIGIN` only picks its policy), so
    the default one is built here. An intended reorder updates this list and the
    comment block in `server.py` together.
    """
    client, _ = make_test_app(tmp_path)

    assert [layer.cls for layer in client.app.user_middleware] == [
        ResourceStreamDeadlineMiddleware,
        SelectiveGZipMiddleware,
        CORSMiddleware,
        SecurityHeadersMiddleware,
        BodySizeLimitMiddleware,
        IpRateLimitMiddleware,
        CsrfOriginMiddleware,
        TrustedHostMiddleware,
        AccessLogMiddleware,
    ]


@pytest.mark.parametrize(("outcome", "started"), [
    ("success", True),
    ("error", False),
    ("error", True),
    ("cancel", False),
    ("cancel", True),
])
@pytest.mark.parametrize("metrics_fail", [False, True])
def test_access_log_restores_context_and_records_each_http_outcome(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, outcome: str, started: bool,
    metrics_fail: bool,
) -> None:
    """defect:#1576 -- preserve streaming, status, metrics and caller context on every exit."""
    import structlog

    client, _ = make_test_app(tmp_path)
    metrics = client.app.state.http_metrics
    metrics_error = RuntimeError("metrics unavailable")

    class FailingMetrics:
        def record(self, method, status_code, duration_ms):
            raise metrics_error

    if metrics_fail:
        client.app.state.http_metrics = FailingMetrics()
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=[structlog.contextvars.merge_contextvars],
    ))
    logger = logging.getLogger("songmaker_cli.middleware.access_log")
    stream_error = RuntimeError("stream failed")
    messages = []
    chunks = [b"first", b"second"]

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    async def app(scope, receive, send):
        assert structlog.contextvars.get_contextvars() == {
            "ip": "203.0.113.9", "method": "GET", "path": "/stream",
        }
        structlog.contextvars.bind_contextvars(user_id="request-user")
        if started or outcome == "success":
            await send({"type": "http.response.start", "status": 206, "headers": []})
            for chunk in chunks:
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
                assert messages[-1]["body"] == chunk
        if outcome == "error":
            raise stream_error
        if outcome == "cancel":
            asyncio.current_task().cancel()
            await asyncio.sleep(0)
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def drive():
        structlog.contextvars.bind_contextvars(ip="outer", user_id="outer-user", caller="test")
        previous = structlog.contextvars.get_contextvars()
        scope = {
            "type": "http", "method": "GET", "path": "/stream", "headers": [],
            "client": ("203.0.113.9", 1234), "app": client.app,
        }
        try:
            await AccessLogMiddleware(app)(scope, receive, send)
        finally:
            assert structlog.contextvars.get_contextvars() == previous

    async def run_request():
        task = asyncio.create_task(drive())
        if outcome == "success":
            await task
        else:
            error = RuntimeError if outcome == "error" else asyncio.CancelledError
            with pytest.raises(error) as raised:
                await task
            if outcome == "error":
                assert raised.value is stream_error

    logger.addHandler(handler)
    try:
        with caplog.at_level("INFO", logger=logger.name):
            asyncio.run(run_request())
    finally:
        logger.removeHandler(handler)
        handler.close()

    status = 206 if started or outcome == "success" else 500
    records = [r for r in caplog.records if r.name == "songmaker_cli.middleware.access_log"]
    assert len(records) == (2 if metrics_fail else 1)
    entries = [json.loads(line) for line in output.getvalue().splitlines()]
    for entry in entries:
        assert entry["ip"] == "203.0.113.9"
        assert entry["method"] == "GET"
        assert entry["path"] == "/stream"
        assert entry["user_id"] == "request-user"
    assert entries[0]["event"].startswith("ACCESS ")
    assert f"GET /stream {status} " in entries[0]["event"]
    if metrics_fail:
        assert records[1].levelno == logging.ERROR
        assert records[1].exc_info[1] is metrics_error
    snapshot = metrics.snapshot()
    assert snapshot["http_requests_total"] == ({} if metrics_fail else {f"GET {status}": 1})
    assert snapshot["http_requests_count"] == (0 if metrics_fail else 1)
    assert snapshot["http_request_duration_total_ms"] >= 0
    if outcome == "success":
        assert messages[-1] == {"type": "http.response.body", "body": b"", "more_body": False}
    elif started:
        assert messages[-1] == {"type": "http.response.body", "body": b"second", "more_body": True}
    else:
        assert messages == []


@pytest.mark.parametrize("scope_type", ["lifespan", "websocket"])
def test_access_log_passes_non_http_scopes_through(
    caplog: pytest.LogCaptureFixture, scope_type: str,
) -> None:
    """defect:#1576 -- non-HTTP exchanges retain their protocol and emit no access record."""
    import structlog

    scope = {"type": scope_type}
    incoming = {"type": f"{scope_type}.disconnect"}
    outgoing = {"type": f"{scope_type}.close"}
    messages = []

    async def receive():
        return incoming

    async def send(message):
        messages.append(message)

    async def app(received_scope, receive, send):
        assert received_scope == scope
        assert await receive() == incoming
        assert structlog.contextvars.get_contextvars()["caller"] == "outer"
        await send(outgoing)

    async def drive():
        structlog.contextvars.bind_contextvars(caller="outer")
        await AccessLogMiddleware(app)(scope, receive, send)

    with caplog.at_level("INFO", logger="songmaker_cli.middleware.access_log"):
        asyncio.run(drive())
    assert messages == [outgoing]
    assert not [r for r in caplog.records if r.name == "songmaker_cli.middleware.access_log"]


@pytest.fixture
def security_exchange(tmp_path: Path):
    """Drive the installed host stack without a TestClient worker thread."""
    client, _ = make_test_app(tmp_path)
    app = client.app

    @app.post("/api/internal/security-proof")
    async def read_body(request: Request) -> Response:
        await request.body()
        return Response(b"ok")

    @app.post("/api/security-proof")
    async def protected() -> Response:
        return Response(b"ok")

    @app.get("/api/security-proof/failure")
    async def fail() -> Response:
        raise RuntimeError("route failed")

    @app.get("/api/security-proof/validate")
    async def validate(count: int) -> Response:
        return Response(str(count))

    async def exchange(
        path="/api/internal/security-proof", method="POST", headers=(), body=b"",
        *, expected_error=None,
    ):
        messages = []

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1", "scheme": "http", "method": method,
            "path": path, "raw_path": path.encode(), "query_string": b"",
            "root_path": "", "headers": [(b"host", b"localhost"), *headers],
            "client": ("203.0.113.9", 1234), "server": ("localhost", 80),
        }
        if expected_error is None:
            await app(scope, receive, send)
        else:
            with pytest.raises(expected_error):
                await app(scope, receive, send)
        starts = [m for m in messages if m["type"] == "http.response.start"]
        assert len(starts) == 1
        return (
            starts[0]["status"], dict(starts[0]["headers"]),
            b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body"),
        )

    return app, exchange


@pytest.mark.parametrize("outcome", ["declared", "streamed", "error", "origin", "token"])
def test_installed_stack_adds_security_headers_to_refusals(security_exchange, outcome):
    """defect:#1590 -- 413, unhandled 500 and both CSRF 403 paths keep policy headers."""
    from songmaker_cli.settings import get_settings

    app, exchange = security_exchange
    arguments = {}
    expected = 403
    if outcome in {"declared", "streamed"}:
        size = get_settings().max_request_body_bytes + 1
        arguments = (
            {"headers": [(b"content-length", str(size).encode())]}
            if outcome == "declared" else {"body": b"x" * size}
        )
        expected = 413
    elif outcome == "error":
        app.debug = True
        arguments = {
            "path": "/api/security-proof/failure", "method": "GET",
            "expected_error": RuntimeError,
        }
        expected = 500
    elif outcome == "origin":
        arguments = {
            "path": "/api/security-proof", "headers": [(b"origin", b"https://foreign.example")],
        }
    else:
        arguments = {"path": "/api/security-proof"}
    status, headers, body = asyncio.run(exchange(**arguments))
    assert status == expected
    assert headers[b"x-content-type-options"] == b"nosniff"
    assert headers[b"x-frame-options"] == b"DENY"
    assert headers[b"referrer-policy"] == b"strict-origin-when-cross-origin"
    assert b"content-security-policy" in headers
    assert b"permissions-policy" in headers
    assert headers[b"cache-control"] == b"no-store"
    if outcome == "error":
        assert body == b"Internal Server Error"


def test_csrf_refusals_spend_ip_budget_and_429_keeps_security_headers(
    monkeypatch, tmp_path: Path,
):
    """defect:#1590 -- the rate limiter runs before CSRF and remains inside headers."""
    import httpx

    monkeypatch.setenv("IP_RATE_LIMIT", "1")
    client, _ = make_test_app(tmp_path)

    async def drive():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://localhost",
        ) as http:
            for expected in (403, 429):
                response = await http.post(
                    LOGOUT_PATH, headers={"Origin": "https://foreign.example"},
                )
                assert response.status_code == expected
                assert response.headers["x-content-type-options"] == "nosniff"
                assert response.headers["x-frame-options"] == "DENY"
                assert "content-security-policy" in response.headers
                if expected == 429:
                    assert int(response.headers["retry-after"]) > 0

    asyncio.run(drive())


@pytest.mark.parametrize(("allowed", "origin", "expected"), [
    ("app.example", "https://app.example", 200),
    ("app.example", "https://app.example:8443", 200),
    ("app.example:8443", "https://app.example:8443", 200),
    ("app.example:8443", "https://app.example:443", 403),
    ("app.example", "https://app.example.foreign", 403),
    ("app.example", "https://user@app.example", 403),
    ("app.example", "https://user:password@app.example", 403),
    ("app.example", "https:///missing", 403),
    ("[::1]", "https://[::1]:8080", 200),
    ("[::1]:8080", "https://[::1]:8080", 200),
    ("[::1]:8080", "https://[::1]:8081", 403),
    ("[::1]", "https://user@[::1]", 403),
    ("[::1]", "https://[::1", 403),
])
def test_host_origin_parser_applies_exact_port_and_ipv6_rules(
    security_exchange, monkeypatch, allowed, origin, expected,
):
    """defect:#1590 -- host configuration feeds the library's parsed origin checks."""
    from songmaker_cli.app_context import allowed_hosts
    from songmaker_cli.settings import get_settings

    app, exchange = security_exchange
    monkeypatch.setenv("ALLOWED_HOSTS", allowed)
    get_settings.cache_clear()
    install_web_auth_config(app, replace(
        installed_web_auth_config(app),
        allowed_hosts_exact=frozenset(allowed_hosts(get_settings())),
    ))
    status, _, _ = asyncio.run(
        exchange("/api/security-proof", headers=[(b"origin", origin.encode())]),
    )
    assert status == expected


def test_a_form_post_without_origin_is_refused(security_exchange):
    """defect:#1891 -- a form post without Origin is refused."""
    _, exchange = security_exchange
    status, _, body = asyncio.run(exchange(
        "/api/security-proof",
        headers=[(b"content-type", b"application/x-www-form-urlencoded")],
        body=b"title=X",
    ))
    assert status == 403
    assert b"Missing Origin header" in body


def test_a_worker_registration_without_origin_or_fetch_metadata_passes_the_origin_layer(
    security_exchange,
):
    """K7, cell 8 -- the internal path passes with neither header; its token is its proof."""
    _, exchange = security_exchange
    status, _, _ = asyncio.run(exchange(
        "/api/internal/security-proof",
        headers=[(b"content-type", b"application/json")],
        body=b"{}",
    ))
    assert status == 200


@pytest.mark.parametrize("path", ["/api/internalx/security-proof", "/auth/backchannel-logoutx"])
def test_the_origin_exemption_is_the_exact_path_and_the_exact_prefix(security_exchange, path):
    """K7, cell 9 -- a path that only starts like an exempt one is not exempt."""
    _, exchange = security_exchange
    status, _, _ = asyncio.run(exchange(path, headers=[(b"content-type", b"application/json")]))
    assert status == 403


@pytest.mark.parametrize("headers", [(), [(b"referer", b"https://localhost/")]])
def test_a_json_write_without_origin_or_fetch_metadata_is_refused_and_referer_does_not_admit_it(
    security_exchange, headers,
):
    """K6, cell 10."""
    _, exchange = security_exchange
    status, _, body = asyncio.run(exchange(
        "/api/security-proof", headers=[(b"content-type", b"application/json"), *headers],
        body=b"{}",
    ))
    assert status == 403
    assert b"Missing Origin header" in body


@pytest.mark.parametrize(("site", "expected"), [
    (b"cross-site", 403), (b"none", 403), (b"same-origin", 200),
])
def test_a_write_is_admitted_by_fetch_metadata_alone(security_exchange, site, expected):
    """K6, cell 11 -- same-origin passes with no token header; cross-site and none do not."""
    _, exchange = security_exchange
    status, _, _ = asyncio.run(exchange("/api/security-proof", headers=[(b"sec-fetch-site", site)]))
    assert status == expected


@pytest.mark.parametrize(("origin", "expected"), [
    (b"http://localhost", 403), (b"https://localhost", 200),
])
def test_a_listed_host_named_over_http_is_refused_while_cookies_are_secure(
    security_exchange, origin, expected,
):
    """K6, cell 12."""
    _, exchange = security_exchange
    status, _, _ = asyncio.run(exchange("/api/security-proof", headers=[(b"origin", origin)]))
    assert status == expected


@pytest.mark.parametrize("path", [LOGOUT_PATH, "/api/security-proof"])
def test_every_path_but_the_exempt_ones_rejects_foreign_origins(security_exchange, path):
    """K6 -- the logout is behind the origin check like every other write."""
    _, exchange = security_exchange
    status, _, _ = asyncio.run(exchange(path, headers=[(b"origin", b"https://foreign.example")]))
    assert status == 403


def test_the_internal_path_no_longer_rejects_a_foreign_origin(security_exchange):
    """K7 -- workers have no browser; the internal token decides."""
    _, exchange = security_exchange
    status, _, _ = asyncio.run(exchange(
        "/api/internal/security-proof", headers=[(b"origin", b"https://foreign.example")],
    ))
    assert status == 200


@pytest.mark.parametrize("cookie_kind", ["tampered", "non-ascii"])
def test_a_bad_session_cookie_is_refused_with_401_and_never_a_500(security_exchange, cookie_kind):
    """defect:#1590 -- malformed input cannot turn a refusal into an exception."""
    app, exchange = security_exchange
    config = installed_web_auth_config(app)
    cookie = issued_cookies("proof-session", config)[config.session_cookie_name]
    cookie = "altered-" + cookie if cookie_kind == "tampered" else "é"
    headers = [(b"cookie", f"{config.session_cookie_name}={cookie}".encode("latin-1"))]
    status, _, _ = asyncio.run(exchange("/api/auth/me", method="GET", headers=headers))
    assert status == 401


@pytest.mark.parametrize(("path", "expected"), [
    ("/api/security-proof/validate", 422), ("/api/security-proof/missing", 404),
])
def test_installed_stack_preserves_host_error_handlers(security_exchange, path, expected):
    """defect:#1590 -- validation and API 404 responses retain the host's JSON contract."""
    _, exchange = security_exchange
    status, headers, body = asyncio.run(exchange(path, method="GET"))
    assert status == expected
    assert headers[b"content-type"] == b"application/json"
    detail = json.loads(body)["detail"]
    assert detail == ("Validation error on: query.count" if expected == 422 else "Not Found")


def test_cors_preflight_remains_outside_security_stack(security_exchange):
    """defect:#1590 -- a CORS preflight keeps its policy, bypassing the inner stack."""
    _, exchange = security_exchange
    status, headers, _ = asyncio.run(exchange(method="OPTIONS", headers=[
        (b"origin", b"http://localhost"), (b"access-control-request-method", b"POST"),
    ]))
    assert status == 200
    assert headers[b"access-control-allow-origin"] == b"http://localhost"
    assert b"x-content-type-options" not in headers


@pytest.mark.parametrize("failure", ["blocked-start", "body-after-start"])
def test_body_limit_bounds_start_and_never_restarts_a_stream(failure):
    """defect:#1590 -- stalled starts time out; an oversized late body aborts the stream."""
    from songmaker_cli.request_policies import build_body_size_policy
    from songmaker_cli.settings import get_settings

    policy = build_body_size_policy(get_settings())
    assert policy.start_send_seconds == 10.0
    policy = replace(policy, default_max_bytes=1, start_send_seconds=0.01)
    messages = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"first", "more_body": True})
        await receive()

    async def receive():
        return {"type": "http.request", "body": b"oversized", "more_body": False}

    async def send(message):
        messages.append(message)
        if failure == "blocked-start":
            await anyio.sleep_forever()

    async def drive():
        middleware = BodySizeLimitMiddleware(app, policy=policy)
        scope = {"type": "http", "method": "POST", "path": "/api/proof", "headers": []}
        with anyio.fail_after(1):
            with pytest.raises(TimeoutError if failure == "blocked-start" else Exception) as raised:
                await middleware(scope, receive, send)
            if failure == "body-after-start":
                assert not isinstance(raised.value, TimeoutError)

    asyncio.run(drive())
    assert [m["status"] for m in messages if m["type"] == "http.response.start"] == [200]
    if failure == "body-after-start":
        assert messages[-1] == {
            "type": "http.response.body", "body": b"first", "more_body": True,
        }
    else:
        assert len(messages) == 1

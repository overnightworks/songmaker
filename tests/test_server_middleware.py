"""Tests for the server's middleware: `SelectiveGZipMiddleware` and the stack order."""

from __future__ import annotations

import asyncio
import gzip as gzip_stdlib
from pathlib import Path

import pytest
from conftest import make_test_app
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from webauth.middleware import (
    BodySizeLimitMiddleware,
    CsrfOriginMiddleware,
    CsrfTokenMiddleware,
    IpRateLimitMiddleware,
    SecurityHeadersMiddleware,
)

from songmaker_cli.constants import GZIP_COMPRESS_LEVEL, GZIP_MINIMUM_SIZE_BYTES
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
    """defect:#1521 -- the middleware order is security-critical and was only a comment.

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
        BodySizeLimitMiddleware,
        IpRateLimitMiddleware,
        CsrfOriginMiddleware,
        CsrfTokenMiddleware,
        AccessLogMiddleware,
        SecurityHeadersMiddleware,
    ]


@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
@pytest.mark.parametrize("started", [False, True])
def test_access_log_restores_context_and_records_each_http_outcome(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, outcome: str, started: bool,
) -> None:
    """defect:#1576 -- preserve streaming, status, metrics and caller context on every exit."""
    import structlog

    client, _ = make_test_app(tmp_path)
    metrics = client.app.state.http_metrics
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
            raise RuntimeError("stream failed")
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
            with pytest.raises(error):
                await task

    with caplog.at_level("INFO", logger="songmaker_cli.middleware.access_log"):
        asyncio.run(run_request())

    status = 206 if started or outcome == "success" else 500
    records = [r for r in caplog.records if r.name == "songmaker_cli.middleware.access_log"]
    assert len(records) == 1
    assert f"GET /stream {status} " in records[0].getMessage()
    snapshot = metrics.snapshot()
    assert snapshot["http_requests_total"] == {f"GET {status}": 1}
    assert snapshot["http_requests_count"] == 1
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

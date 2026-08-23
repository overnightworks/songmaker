"""Tests for `SelectiveGZipMiddleware` — the server's response-compression layer."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from songmaker_cli.constants import GZIP_MINIMUM_SIZE_BYTES
from songmaker_cli.middleware import SelectiveGZipMiddleware

_LARGE_JSON_PAYLOAD = {"lyrics": "la " * 1000}
_TINY_JSON_PAYLOAD = {"status": "ok"}
_LARGE_AUDIO_BODY = b"\x00" * 4096
_LARGE_IMAGE_BODY = b"\xff\xd8\xff" + b"\x00" * 4096
_SSE_CHUNKS = [f"data: chunk-{i}-{'x' * 200}\n\n".encode() for i in range(6)]


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

    app.add_middleware(SelectiveGZipMiddleware, minimum_size=GZIP_MINIMUM_SIZE_BYTES)
    return app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(_build_app())


def test_large_json_response_is_gzip_compressed(client: TestClient) -> None:
    resp = client.get("/api/songs/s1", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") == "gzip"


def test_tiny_json_response_is_not_gzip_compressed(client: TestClient) -> None:
    resp = client.get("/api/health", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers


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


def test_sse_stream_is_never_gzip_compressed_and_forwards_each_chunk_immediately() -> None:
    """Drive the raw ASGI middleware directly (no TestClient/httpx transport).

    httpx's response streaming re-buffers reads at its own internal
    boundary, so message-by-message forwarding can't be observed through
    it. Sending straight into the middleware's `send` callable, the way
    `test_body_size_streaming_too_large` in `test_server.py` already does
    for `BodySizeLimitMiddleware`, is the only layer where "one ASGI send
    per source chunk, no accumulation" is actually the visible contract.
    """

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

    middleware = SelectiveGZipMiddleware(sse_app, minimum_size=GZIP_MINIMUM_SIZE_BYTES)

    async def run() -> tuple[dict, list[bytes]]:
        start_message: dict = {}
        body_messages: list[bytes] = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                start_message.update(message)
            elif message["type"] == "http.response.body":
                body_messages.append(message.get("body", b""))

        scope = {
            "type": "http", "method": "GET", "path": "/api/stream",
            "headers": [(b"accept-encoding", b"gzip")],
        }
        await middleware(scope, receive, send)
        return start_message, body_messages

    start_message, body_messages = asyncio.run(run())

    headers = dict(start_message["headers"])
    assert b"content-encoding" not in headers
    assert body_messages == _SSE_CHUNKS

"""Tests for `SelectiveGZipMiddleware` — the server's response-compression layer."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from songmaker_cli.constants import GZIP_MINIMUM_SIZE_BYTES
from songmaker_cli.middleware import SelectiveGZipMiddleware

_LARGE_JSON_PAYLOAD = {"lyrics": "la " * 1000}
_TINY_JSON_PAYLOAD = {"status": "ok"}
_LARGE_AUDIO_BODY = b"\x00" * 4096


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

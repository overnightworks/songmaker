"""Tests for the CLI HTTP client utilities."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from songmaker_cli.cli_client import (
    ServerError,
    api_get,
    api_post,
    api_put,
    resolve_song,
)


def _mock_response(status: int = 200, json_data: object = None):
    resp = MagicMock()
    resp.is_success = 200 <= status < 300
    resp.status_code = status
    resp.text = str(json_data)
    resp.json.return_value = json_data
    return resp


# ── api_get ─────────────────────────────────────────────────────────


def test_api_get_success() -> None:
    with patch("httpx.get", return_value=_mock_response(json_data=[{"id": "a1"}])):
        result = api_get("http://localhost:8080", "/api/albums")
    assert result == [{"id": "a1"}]


def test_api_get_connection_error() -> None:
    import httpx
    with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
        with pytest.raises(ServerError, match="Cannot connect"):
            api_get("http://localhost:8080", "/api/albums")


def test_api_get_error_response() -> None:
    with patch("httpx.get", return_value=_mock_response(status=404, json_data={"error": "nope"})):
        with pytest.raises(ServerError, match="404"):
            api_get("http://localhost:8080", "/api/songs/bad")


# ── api_post ────────────────────────────────────────────────────────


def test_api_post_success() -> None:
    with patch("httpx.post", return_value=_mock_response(json_data={"id": "j1"})):
        result = api_post("http://localhost:8080", "/api/songs/s1/generate", {"count": 2})
    assert result["id"] == "j1"


def test_api_post_connection_error() -> None:
    import httpx
    with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
        with pytest.raises(ServerError, match="Cannot connect"):
            api_post("http://localhost:8080", "/api/songs/s1/generate")


def test_api_post_error_response() -> None:
    with patch("httpx.post", return_value=_mock_response(status=400, json_data="bad")):
        with pytest.raises(ServerError, match="400"):
            api_post("http://localhost:8080", "/api/songs/s1/generate")


# ── api_put ─────────────────────────────────────────────────────────


def test_api_put_success() -> None:
    with patch("httpx.put", return_value=_mock_response(json_data={"id": "s1"})):
        result = api_put("http://localhost:8080", "/api/songs/s1", {"lyrics": "new"})
    assert result["id"] == "s1"


def test_api_put_connection_error() -> None:
    import httpx
    with patch("httpx.put", side_effect=httpx.ConnectError("refused")):
        with pytest.raises(ServerError, match="Cannot connect"):
            api_put("http://localhost:8080", "/api/songs/s1", {"lyrics": "x"})


# ── resolve_song ────────────────────────────────────────────────────


def test_resolve_song_exact_match() -> None:
    songs = [{"title": "Thunder", "id": "s1"}, {"title": "Rain", "id": "s2"}]
    with patch("songmaker_cli.cli_client.api_get", return_value=songs):
        result = resolve_song("http://localhost:8080", "Thunder")
    assert result["id"] == "s1"


def test_resolve_song_case_insensitive() -> None:
    songs = [{"title": "Thunder", "id": "s1"}]
    with patch("songmaker_cli.cli_client.api_get", return_value=songs):
        result = resolve_song("http://localhost:8080", "thunder")
    assert result["id"] == "s1"


def test_resolve_song_partial_match() -> None:
    songs = [{"title": "With A Little Help", "id": "s1"}, {"title": "Rain", "id": "s2"}]
    with patch("songmaker_cli.cli_client.api_get", return_value=songs):
        result = resolve_song("http://localhost:8080", "little")
    assert result["id"] == "s1"


def test_resolve_song_multiple_matches() -> None:
    songs = [{"title": "Thunder Storm", "id": "s1"}, {"title": "Thunder Road", "id": "s2"}]
    with patch("songmaker_cli.cli_client.api_get", return_value=songs):
        with pytest.raises(ServerError, match="Multiple matches"):
            resolve_song("http://localhost:8080", "thunder")


def test_resolve_song_no_match() -> None:
    songs = [{"title": "Thunder", "id": "s1"}]
    with patch("songmaker_cli.cli_client.api_get", return_value=songs):
        with pytest.raises(ServerError, match="No song found"):
            resolve_song("http://localhost:8080", "nonexistent")

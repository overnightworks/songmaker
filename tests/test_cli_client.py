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
    resp.cookies = {}
    return resp


def _mock_client(response: MagicMock | None = None, side_effect: Exception | None = None):
    """Build a mock httpx.Client that returns the given response for any HTTP method."""
    client = MagicMock()
    client.cookies = MagicMock()
    client.cookies.get = MagicMock(return_value=None)
    if side_effect:
        client.get.side_effect = side_effect
        client.post.side_effect = side_effect
        client.put.side_effect = side_effect
    else:
        client.get.return_value = response
        client.post.return_value = response
        client.put.return_value = response
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    return client


# ── api_get ─────────────────────────────────────────────────────────


def test_api_get_success() -> None:
    client = _mock_client(_mock_response(json_data=[{"id": "a1"}]))
    with patch("songmaker_cli.cli_client._build_client", return_value=client):
        result = api_get("http://localhost:8080", "/api/albums")
    assert result == [{"id": "a1"}]


def test_api_get_connection_error() -> None:
    import httpx
    client = _mock_client(side_effect=httpx.ConnectError("refused"))
    with patch("songmaker_cli.cli_client._build_client", return_value=client):
        with pytest.raises(ServerError, match="Cannot connect"):
            api_get("http://localhost:8080", "/api/albums")


def test_api_get_error_response() -> None:
    client = _mock_client(_mock_response(status=404, json_data={"error": "nope"}))
    with patch("songmaker_cli.cli_client._build_client", return_value=client):
        with pytest.raises(ServerError, match="404"):
            api_get("http://localhost:8080", "/api/songs/bad")


def test_api_get_401_suggests_login() -> None:
    client = _mock_client(_mock_response(status=401, json_data={"detail": "auth required"}))
    with patch("songmaker_cli.cli_client._build_client", return_value=client):
        with pytest.raises(ServerError, match="songmaker login"):
            api_get("http://localhost:8080", "/api/albums")


# ── api_post ────────────────────────────────────────────────────────


def test_api_post_success() -> None:
    client = _mock_client(_mock_response(json_data={"id": "j1"}))
    with patch("songmaker_cli.cli_client._build_client", return_value=client):
        result = api_post("http://localhost:8080", "/api/songs/s1/generate", {"count": 2})
    assert result["id"] == "j1"


def test_api_post_connection_error() -> None:
    import httpx
    client = _mock_client(side_effect=httpx.ConnectError("refused"))
    with patch("songmaker_cli.cli_client._build_client", return_value=client):
        with pytest.raises(ServerError, match="Cannot connect"):
            api_post("http://localhost:8080", "/api/songs/s1/generate")


def test_api_post_error_response() -> None:
    client = _mock_client(_mock_response(status=400, json_data="bad"))
    with patch("songmaker_cli.cli_client._build_client", return_value=client):
        with pytest.raises(ServerError, match="400"):
            api_post("http://localhost:8080", "/api/songs/s1/generate")


# ── api_put ─────────────────────────────────────────────────────────


def test_api_put_success() -> None:
    client = _mock_client(_mock_response(json_data={"id": "s1"}))
    with patch("songmaker_cli.cli_client._build_client", return_value=client):
        result = api_put("http://localhost:8080", "/api/songs/s1", {"lyrics": "new"})
    assert result["id"] == "s1"


def test_api_put_connection_error() -> None:
    import httpx
    client = _mock_client(side_effect=httpx.ConnectError("refused"))
    with patch("songmaker_cli.cli_client._build_client", return_value=client):
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


# ── api_put error response ───────────────────────────────────────────


def test_api_put_error_response() -> None:
    client = _mock_client(_mock_response(status=400, json_data="bad request"))
    with patch("songmaker_cli.cli_client._build_client", return_value=client):
        with pytest.raises(ServerError, match="400"):
            api_put("http://localhost:8080", "/api/songs/s1", {"lyrics": "x"})


# ── poll_job ─────────────────────────────────────────────────────────


def test_poll_job_completed() -> None:
    from songmaker_cli.cli_client import poll_job

    job_completed = {"status": "completed", "progress": 1.0}

    with (
        patch("songmaker_cli.cli_client.api_get", return_value=job_completed),
        patch("songmaker_cli.cli_client._print_progress"),
        patch("time.sleep"),
    ):
        result = poll_job("http://localhost:8080", "j1")

    assert result["status"] == "completed"


def test_poll_job_failed() -> None:
    from songmaker_cli.cli_client import poll_job

    job_failed = {"status": "failed", "progress": 0.5, "error": "GPU exploded"}

    with (
        patch("songmaker_cli.cli_client.api_get", return_value=job_failed),
        patch("songmaker_cli.cli_client._print_progress"),
        patch("time.sleep"),
    ):
        with pytest.raises(ServerError, match="GPU exploded"):
            poll_job("http://localhost:8080", "j1")


def test_poll_job_polls_until_done() -> None:
    from songmaker_cli.cli_client import poll_job

    responses = [
        {"status": "running", "progress": 0.3},
        {"status": "running", "progress": 0.7},
        {"status": "completed", "progress": 1.0},
    ]

    with (
        patch("songmaker_cli.cli_client.api_get", side_effect=responses),
        patch("songmaker_cli.cli_client._print_progress"),
        patch("time.sleep"),
    ):
        result = poll_job("http://localhost:8080", "j1")

    assert result["status"] == "completed"


def test_poll_job_failed_unknown_error() -> None:
    from songmaker_cli.cli_client import poll_job

    job_failed = {"status": "failed", "progress": 0.0}

    with (
        patch("songmaker_cli.cli_client.api_get", return_value=job_failed),
        patch("songmaker_cli.cli_client._print_progress"),
        patch("time.sleep"),
    ):
        with pytest.raises(ServerError, match="Unknown error"):
            poll_job("http://localhost:8080", "j1")


# ── _print_progress ──────────────────────────────────────────────────


def test_print_progress_full() -> None:
    import io

    from songmaker_cli.cli_client import _print_progress

    buf = io.StringIO()
    with patch("sys.stderr", buf):
        _print_progress(1.0, "completed")

    output = buf.getvalue()
    assert "100%" in output
    assert "completed" in output


def test_print_progress_partial() -> None:
    import io

    from songmaker_cli.cli_client import _print_progress

    buf = io.StringIO()
    with patch("sys.stderr", buf):
        _print_progress(0.5, "running")

    output = buf.getvalue()
    assert "50%" in output
    assert "running" in output


def test_print_progress_zero() -> None:
    import io

    from songmaker_cli.cli_client import _print_progress

    buf = io.StringIO()
    with patch("sys.stderr", buf):
        _print_progress(0.0, "queued")

    output = buf.getvalue()
    assert "0%" in output


# ── cli_login / cli_logout ──────────────────────────────────────────


def test_cli_login_success(tmp_path) -> None:
    import httpx

    from songmaker_cli.cli_client import cli_login

    resp = MagicMock()
    resp.is_success = True
    resp.status_code = 200
    resp.json.return_value = {"username": "admin", "role": "admin"}
    resp.cookies = httpx.Cookies()
    resp.cookies.set("session_id", "tok123")
    resp.cookies.set("csrf_token", "csrf456")
    resp.headers = {"content-type": "application/json"}

    with (
        patch("httpx.post", return_value=resp),
        patch("songmaker_cli.cli_client.SESSION_DIR", tmp_path),
        patch("songmaker_cli.cli_client.SESSION_FILE", tmp_path / "session.json"),
    ):
        result = cli_login("http://localhost:8080", "admin", "password")

    assert result["username"] == "admin"
    assert (tmp_path / "session.json").exists()


def test_cli_login_failure() -> None:

    from songmaker_cli.cli_client import cli_login

    resp = MagicMock()
    resp.is_success = False
    resp.status_code = 401
    resp.json.return_value = {"detail": "Invalid credentials"}
    resp.headers = {"content-type": "application/json"}

    with patch("httpx.post", return_value=resp):
        with pytest.raises(ServerError, match="Login failed"):
            cli_login("http://localhost:8080", "admin", "wrong")


def test_cli_login_connection_error() -> None:
    import httpx

    from songmaker_cli.cli_client import cli_login

    with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
        with pytest.raises(ServerError, match="Cannot connect"):
            cli_login("http://localhost:8080", "admin", "pass")

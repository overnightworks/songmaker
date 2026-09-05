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


@pytest.mark.parametrize(
    ("client_request", "args"),
    [
        pytest.param(api_get, ("/api/albums",), id="get"),
        pytest.param(api_post, ("/api/songs/s1/generate",), id="post"),
        pytest.param(api_put, ("/api/songs/s1", {"lyrics": "x"}), id="put"),
        pytest.param(
            "upload",
            ("/api/audio/upload", [("file", ("clip.wav", b"audio", "audio/wav"))]),
            id="upload",
        ),
    ],
)
def test_unauthenticated_requests_suggest_login(client_request, args: tuple) -> None:
    from songmaker_cli.cli_client import api_upload

    client = _mock_client(_mock_response(status=401, json_data={"detail": "auth required"}))
    call = api_upload if client_request == "upload" else client_request
    with patch("songmaker_cli.cli_client._build_client", return_value=client):
        with pytest.raises(ServerError, match="songmaker login"):
            call("http://localhost:8080", *args)


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


def test_cli_login_non_json_error() -> None:
    from songmaker_cli.cli_client import cli_login

    resp = MagicMock()
    resp.is_success = False
    resp.status_code = 500
    resp.text = "Internal Server Error"
    resp.headers = {"content-type": "text/plain"}

    with patch("httpx.post", return_value=resp):
        with pytest.raises(ServerError, match="Internal Server Error"):
            cli_login("http://localhost:8080", "admin", "wrong")


# ── _load_session / _save_session / _clear_session ────────────────


def test_load_session_no_file(tmp_path) -> None:
    from songmaker_cli.cli_client import _load_session

    with patch("songmaker_cli.cli_client.SESSION_FILE", tmp_path / "nonexistent.json"):
        result = _load_session("http://localhost:8080")
    assert result == {}


def test_load_session_valid_file(tmp_path) -> None:
    import json

    from songmaker_cli.cli_client import _load_session

    sf = tmp_path / "session.json"
    sf.write_text(json.dumps({"http://localhost:8080": {"session_id": "tok"}}))
    with patch("songmaker_cli.cli_client.SESSION_FILE", sf):
        result = _load_session("http://localhost:8080")
    assert result == {"session_id": "tok"}


def test_load_session_corrupt_file(tmp_path) -> None:
    from songmaker_cli.cli_client import _load_session

    sf = tmp_path / "session.json"
    sf.write_text("not json{{{")
    with patch("songmaker_cli.cli_client.SESSION_FILE", sf):
        result = _load_session("http://localhost:8080")
    assert result == {}


def test_load_session_missing_server(tmp_path) -> None:
    import json

    from songmaker_cli.cli_client import _load_session

    sf = tmp_path / "session.json"
    sf.write_text(json.dumps({"http://other:9000": {"tok": "abc"}}))
    with patch("songmaker_cli.cli_client.SESSION_FILE", sf):
        result = _load_session("http://localhost:8080")
    assert result == {}


def test_save_session_creates_file(tmp_path) -> None:
    import json

    from songmaker_cli.cli_client import _save_session

    sf = tmp_path / "session.json"
    with (
        patch("songmaker_cli.cli_client.SESSION_DIR", tmp_path),
        patch("songmaker_cli.cli_client.SESSION_FILE", sf),
    ):
        _save_session("http://localhost:8080", {"session_id": "tok"})
    data = json.loads(sf.read_text())
    assert data["http://localhost:8080"]["session_id"] == "tok"


def test_save_session_merges_with_existing(tmp_path) -> None:
    import json

    from songmaker_cli.cli_client import _save_session

    sf = tmp_path / "session.json"
    sf.write_text(json.dumps({"http://other:9000": {"tok": "abc"}}))
    with (
        patch("songmaker_cli.cli_client.SESSION_DIR", tmp_path),
        patch("songmaker_cli.cli_client.SESSION_FILE", sf),
    ):
        _save_session("http://localhost:8080", {"session_id": "new"})
    data = json.loads(sf.read_text())
    assert data["http://other:9000"]["tok"] == "abc"
    assert data["http://localhost:8080"]["session_id"] == "new"


def test_save_session_handles_corrupt_existing(tmp_path) -> None:
    import json

    from songmaker_cli.cli_client import _save_session

    sf = tmp_path / "session.json"
    sf.write_text("not json{{{")
    with (
        patch("songmaker_cli.cli_client.SESSION_DIR", tmp_path),
        patch("songmaker_cli.cli_client.SESSION_FILE", sf),
    ):
        _save_session("http://localhost:8080", {"session_id": "tok"})
    data = json.loads(sf.read_text())
    assert data["http://localhost:8080"]["session_id"] == "tok"


def test_clear_session_removes_server(tmp_path) -> None:
    import json

    from songmaker_cli.cli_client import _clear_session

    sf = tmp_path / "session.json"
    sf.write_text(json.dumps({
        "http://localhost:8080": {"tok": "a"},
        "http://other:9000": {"tok": "b"},
    }))
    with patch("songmaker_cli.cli_client.SESSION_FILE", sf):
        _clear_session("http://localhost:8080")
    data = json.loads(sf.read_text())
    assert "http://localhost:8080" not in data
    assert "http://other:9000" in data


def test_clear_session_no_file(tmp_path) -> None:
    from songmaker_cli.cli_client import _clear_session

    with patch("songmaker_cli.cli_client.SESSION_FILE", tmp_path / "nonexistent.json"):
        _clear_session("http://localhost:8080")


def test_clear_session_corrupt_file(tmp_path) -> None:
    from songmaker_cli.cli_client import _clear_session

    sf = tmp_path / "session.json"
    sf.write_text("not json{{{")
    with patch("songmaker_cli.cli_client.SESSION_FILE", sf):
        _clear_session("http://localhost:8080")


# ── _build_client ──────────────────────────────────────────────────


def test_build_client_with_cookies(tmp_path) -> None:
    import json

    from songmaker_cli.cli_client import _build_client

    sf = tmp_path / "session.json"
    cookies = {"session_id": "tok", "csrf_token": "csrf"}
    sf.write_text(json.dumps({"http://localhost:8080": cookies}))
    with patch("songmaker_cli.cli_client.SESSION_FILE", sf):
        client = _build_client("http://localhost:8080")
    assert client.cookies.get("session_id") == "tok"
    assert client.cookies.get("csrf_token") == "csrf"
    client.close()


def test_build_client_no_cookies(tmp_path) -> None:
    from songmaker_cli.cli_client import _build_client

    with patch("songmaker_cli.cli_client.SESSION_FILE", tmp_path / "nonexistent.json"):
        client = _build_client("http://localhost:8080")
    assert len(list(client.cookies.jar)) == 0
    client.close()


# ── cli_logout ─────────────────────────────────────────────────────


def test_cli_logout_success(tmp_path) -> None:
    import json

    from songmaker_cli.cli_client import cli_logout

    sf = tmp_path / "session.json"
    sf.write_text(json.dumps({"http://localhost:8080": {"session_id": "tok"}}))
    client = _mock_client(_mock_response(json_data={"ok": True}))
    with (
        patch("songmaker_cli.cli_client._build_client", return_value=client),
        patch("songmaker_cli.cli_client.SESSION_FILE", sf),
    ):
        cli_logout("http://localhost:8080")
    data = json.loads(sf.read_text())
    assert "http://localhost:8080" not in data


def test_cli_logout_connection_error(tmp_path) -> None:
    import json

    import httpx

    from songmaker_cli.cli_client import cli_logout

    sf = tmp_path / "session.json"
    sf.write_text(json.dumps({"http://localhost:8080": {"session_id": "tok"}}))
    client = _mock_client(side_effect=httpx.ConnectError("refused"))
    client.delete = MagicMock(side_effect=httpx.ConnectError("refused"))
    with (
        patch("songmaker_cli.cli_client._build_client", return_value=client),
        patch("songmaker_cli.cli_client.SESSION_FILE", sf),
    ):
        cli_logout("http://localhost:8080")
    data = json.loads(sf.read_text())
    assert "http://localhost:8080" not in data

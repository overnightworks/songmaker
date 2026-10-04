"""Tests for CLI helper functions."""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from unittest.mock import patch

import numpy as np
import pytest
from conftest import login_and_csrf, make_test_app, stored_hash
from fastapi.testclient import TestClient
from redis import Redis

from songmaker_cli.app_context import build_password_hasher
from songmaker_cli.db.models import User, UserSession
from songmaker_cli.errors import GenerationError, ValidationError
from songmaker_cli.generate import (
    DecodedAudio,
    _decode_audio,
    _write_output,
)
from songmaker_cli.main import app, main
from songmaker_cli.parser import AlbumMeta, SongMeta


def test_decode_audio_success(make_stereo_wav_bytes: Callable[..., bytes]) -> None:
    from acestep_engine.models import AceStepResult

    wav_bytes = make_stereo_wav_bytes()
    result = AceStepResult(wav_bytes=wav_bytes, seed=1)
    audio = _decode_audio(result)
    assert audio.sample_rate == 44100
    assert audio.duration > 0


def test_decode_audio_empty() -> None:
    from acestep_engine.models import AceStepResult

    result = AceStepResult(wav_bytes=b"not wav", seed=1)
    with pytest.raises(GenerationError, match="decode failed"):
        _decode_audio(result)


def test_write_output(tmp_path: Path) -> None:
    left = np.sin(np.linspace(0, 2 * np.pi * 440, 44100)) * 0.3
    right = left.copy()
    audio = DecodedAudio(left=left, right=right, sample_rate=44100, duration=1.0)

    mp3_path = tmp_path / "song_v1.mp3"
    wav_path = tmp_path / "song_v1.wav"
    meta = SongMeta(title="Song", prompt="rock", lyrics="hello", album="test")
    album_meta = AlbumMeta(title="Album", artist="Artist")

    _write_output(audio, 42, mp3_path, wav_path, meta, album_meta)

    assert mp3_path.exists()
    assert mp3_path.stat().st_size > 0
    assert wav_path.exists()
    assert wav_path.stat().st_size > 0



def test_write_output_mastering_error(tmp_path: Path) -> None:
    left = np.array([], dtype=np.float64)
    right = left.copy()
    audio = DecodedAudio(left=left, right=right, sample_rate=44100, duration=0.0)

    mp3_path = tmp_path / "song_v1.mp3"
    wav_path = tmp_path / "song_v1.wav"
    meta = SongMeta(title="Song", prompt="rock", lyrics="hello", album="test")
    album_meta = AlbumMeta(title="Album", artist="Artist")

    with pytest.raises(GenerationError, match="empty"):
        _write_output(audio, 42, mp3_path, wav_path, meta, album_meta)


def test_write_output_encode_error(tmp_path: Path) -> None:
    left = np.sin(np.linspace(0, 2 * np.pi * 440, 44100)) * 0.3
    right = left.copy()
    audio = DecodedAudio(left=left, right=right, sample_rate=44100, duration=1.0)

    mp3_path = tmp_path / "song_v1.mp3"
    wav_path = tmp_path / "song_v1.wav"
    meta = SongMeta(title="Song", prompt="rock", lyrics="hello", album="test")
    album_meta = AlbumMeta(title="Album", artist="Artist")

    with patch("shutil.which", return_value=None):
        with pytest.raises(GenerationError, match="ffmpeg not found"):
            _write_output(audio, 42, mp3_path, wav_path, meta, album_meta)


def test_main_error_handling() -> None:
    with (
        patch("songmaker_cli.main._launcher", side_effect=ValidationError("test error")),
        pytest.raises(SystemExit),
    ):
        main()


# ── reset-password (local DB escape hatch) ──────────────────────────

RESET_USERNAME = "alice"
OLD_PASSWORD = "old-Passw0rd"
NEW_PASSWORD = "fresh-Passw0rd"
OLD_PASSWORD_HASH = stored_hash(OLD_PASSWORD)
CLOSED_REDIS_URL = "redis://127.0.0.1:1/0"


@pytest.fixture
def served_app(tmp_path: Path, monkeypatch) -> TestClient:
    """A running app whose database and session cache the CLI reaches as well."""

    def seed_alice(session) -> None:
        session.add(User(username=RESET_USERNAME, password_hash=OLD_PASSWORD_HASH, role="admin"))

    client, factory = make_test_app(tmp_path, seed_db=seed_alice)
    monkeypatch.setattr("songmaker_cli.db.engine.resolve_database_url", lambda: "sqlite://")
    monkeypatch.setattr("songmaker_cli.db.engine.init_db", lambda _url: factory)
    monkeypatch.setattr(
        "songmaker_cli.redis_client.create_redis", lambda _url: client.app.state.ctx.redis,
    )
    return client


@pytest.fixture
def database_must_stay_closed(served_app: TestClient, monkeypatch) -> TestClient:
    """The served app, with any CLI attempt to open its database failing the test."""

    def refuse_to_open(*_args) -> None:
        raise AssertionError("the command opened the database")

    monkeypatch.setattr("songmaker_cli.db.engine.resolve_database_url", refuse_to_open)
    monkeypatch.setattr("songmaker_cli.db.engine.init_db", refuse_to_open)
    return served_app


def _hash_in_db(client: TestClient) -> str:
    with client.app.state.ctx.db() as session:
        return session.query(User).filter_by(username=RESET_USERNAME).one().password_hash


def _session_count(client: TestClient) -> int:
    with client.app.state.ctx.db() as session:
        return session.query(UserSession).count()


def _reset_password(password: str, repeated: str | None = None) -> None:
    typed = [password, password if repeated is None else repeated]
    with patch("getpass.getpass", side_effect=typed):
        app(["reset-password", RESET_USERNAME], result_action="return_value")


@pytest.fixture
def sent_logins(monkeypatch) -> list[tuple[str, str]]:
    """The (username, password) pairs the login command sends to the server."""
    sent: list[tuple[str, str]] = []

    def record_login(_server: str, username: str, password: str) -> dict:
        sent.append((username, password))
        return {"username": username, "role": "admin"}

    monkeypatch.setattr("songmaker_cli.main.cli_login", record_login)
    return sent


def test_reset_password_stores_the_new_password(served_app, capsys) -> None:
    _reset_password(NEW_PASSWORD)

    assert build_password_hasher().verify(NEW_PASSWORD, _hash_in_db(served_app))
    assert capsys.readouterr().out == (
        f"Password reset for '{RESET_USERNAME}' (role=admin); 0 sessions ended\n"
    )


def test_reset_password_ends_every_session_of_the_account(served_app, capsys) -> None:
    login_and_csrf(served_app, RESET_USERNAME, OLD_PASSWORD)
    assert served_app.get("/api/auth/me").status_code == 200

    _reset_password(NEW_PASSWORD)

    assert served_app.get("/api/auth/me").status_code == 401
    assert _session_count(served_app) == 0
    assert capsys.readouterr().out.endswith("; 1 session ended\n")
    fresh_login = served_app.post(
        "/api/auth/login", json={"username": RESET_USERNAME, "password": NEW_PASSWORD},
    )
    assert fresh_login.status_code == 200


def test_reset_password_changes_nothing_when_the_session_cache_is_unreachable(
    served_app, capsys, monkeypatch,
) -> None:
    login_and_csrf(served_app, RESET_USERNAME, OLD_PASSWORD)
    monkeypatch.setattr(
        "songmaker_cli.redis_client.create_redis", lambda _url: Redis.from_url(CLOSED_REDIS_URL),
    )

    with pytest.raises(SystemExit) as exit_info:
        _reset_password(NEW_PASSWORD)

    assert exit_info.value.code == 1
    assert capsys.readouterr().out == (
        "Error: the session cache is unreachable, so nothing was changed\n"
    )
    assert _hash_in_db(served_app) == OLD_PASSWORD_HASH
    assert _session_count(served_app) == 1
    assert served_app.get("/api/auth/me").status_code == 200


@pytest.mark.parametrize(
    "password, message",
    [
        ("Ab1!xyz", "Error: Password must be at least 8 characters"),
        ("Ab1!xyz" * 19, "Error: Password must be at most 128 characters"),
        ("password123", "Error: Password is too common — choose something less predictable"),
        ("aaaabbbb", "Error: Password must contain at least 4 unique characters"),
    ],
)
def test_reset_password_refuses_a_weak_password_in_plain_words_without_echoing_it(
    served_app, capsys, password: str, message: str,
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _reset_password(password)

    output = capsys.readouterr().out
    assert exit_info.value.code == 1
    assert output == f"{message}\n"
    assert password not in output
    assert _hash_in_db(served_app) == OLD_PASSWORD_HASH


def test_reset_password_refuses_mismatched_passwords_before_opening_the_database(
    database_must_stay_closed, capsys,
) -> None:
    login_and_csrf(database_must_stay_closed, RESET_USERNAME, OLD_PASSWORD)

    with pytest.raises(SystemExit) as exit_info:
        _reset_password(NEW_PASSWORD, repeated=NEW_PASSWORD + "x")

    assert exit_info.value.code == 1
    assert capsys.readouterr().out == "Error: the passwords do not match\n"
    assert _hash_in_db(database_must_stay_closed) == OLD_PASSWORD_HASH
    assert _session_count(database_must_stay_closed) == 1


@pytest.mark.parametrize(
    ("command", "typed"),
    [
        ("login", [EOFError]),
        ("reset-password", [EOFError]),
        ("reset-password", [NEW_PASSWORD, EOFError]),
    ],
    ids=["login", "reset-password-first-prompt", "reset-password-repeat-prompt"],
)
def test_closed_input_at_a_password_prompt_is_a_plain_error(
    database_must_stay_closed, sent_logins, capsys, command: str, typed: list,
) -> None:
    with (
        patch("getpass.getpass", side_effect=typed),
        pytest.raises(SystemExit) as exit_info,
    ):
        app([command, RESET_USERNAME], result_action="return_value")

    assert exit_info.value.code == 1
    assert capsys.readouterr().out == "Error: no password given\n"
    assert sent_logins == []
    assert _hash_in_db(database_must_stay_closed) == OLD_PASSWORD_HASH


def test_login_sends_the_password_typed_at_the_prompt(sent_logins) -> None:
    with patch("getpass.getpass", return_value=OLD_PASSWORD):
        app(["login", RESET_USERNAME], result_action="return_value")

    assert sent_logins == [(RESET_USERNAME, OLD_PASSWORD)]


@pytest.mark.parametrize("command", ["login", "reset-password"])
def test_password_on_the_command_line_is_a_usage_error(
    served_app, sent_logins, capsys, command: str,
) -> None:
    with (
        patch("getpass.getpass", return_value=NEW_PASSWORD),
        pytest.raises(SystemExit) as exit_info,
    ):
        app([command, RESET_USERNAME, NEW_PASSWORD], result_action="return_value")

    printed = "".join(capsys.readouterr())
    assert exit_info.value.code == 1
    assert "Error: unexpected extra argument; passwords are only read at the prompt" in printed
    assert NEW_PASSWORD not in printed
    assert sent_logins == []
    assert _hash_in_db(served_app) == OLD_PASSWORD_HASH

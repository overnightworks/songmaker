"""POST /api/playback-diagnostics — the transient playback recorder's upload."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import apply_csrf_header, make_test_app
from webauth.cookies import DEFAULT_SESSION_COOKIE_NAME
from webauth.passwords import hash_password

from songmaker_cli.db.models import User
from songmaker_cli.db.queries import create_user

_ENDPOINT = "/api/playback-diagnostics"
_LISTENER = "listener"
_PASSWORD = "listener12345"
_DIAGNOSTICS_LOGGER = "songmaker.playback_diagnostics"


def _seed_listener(session) -> None:
    create_user(session, _LISTENER, hash_password(_PASSWORD))


def _event(**overrides) -> dict:
    return {
        "at_ms": 1_759_400_000_000,
        "kind": "promote",
        "take_id": "6f1c2a4e-9b0d-4c3e-8a51-2f7d9e0b1c34",
        "position": 12.5,
        "ready_state": 4,
        "deck": "active",
        "visibility": "hidden",
        "detail": "standby had future data",
        **overrides,
    }


def _report(events: list[dict]) -> dict:
    return {
        "session_id": "a1b2c3",
        "user_agent": "Mozilla/5.0 (Linux; Android 14) Chrome/129",
        "mse_mp3_supported": True,
        "was_discarded": False,
        "events": events,
    }


@pytest.fixture
def app(tmp_path: Path):
    return make_test_app(tmp_path, seed_db=_seed_listener)


@pytest.fixture
def signed_in(app):
    client, _ = app
    response = client.post(
        "/api/auth/login",
        json={"username": _LISTENER, "password": _PASSWORD},
    )
    assert response.status_code == 200
    return client


@pytest.fixture
def listener_id(app) -> str:
    _, factory = app
    with factory() as session:
        return session.query(User).filter_by(username=_LISTENER).one().id


@pytest.fixture
def json_logging(monkeypatch: pytest.MonkeyPatch, isolated_logging):
    monkeypatch.setenv("LOG_FORMAT", "json")


def _start_json_logging() -> None:
    from songmaker_cli.logging_config import configure_logging

    configure_logging()


def _diagnostic_log_lines(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    lines = (json.loads(line) for line in capsys.readouterr().err.splitlines())
    return [line for line in lines if line.get("logger") == _DIAGNOSTICS_LOGGER]


def test_rejects_an_upload_whose_session_has_ended(signed_in) -> None:
    apply_csrf_header(signed_in)
    ended_session_cookie = signed_in.cookies.get(DEFAULT_SESSION_COOKIE_NAME)
    assert signed_in.delete("/api/auth/session").status_code == 200
    signed_in.cookies.set(DEFAULT_SESSION_COOKIE_NAME, ended_session_cookie)

    response = signed_in.post(_ENDPOINT, json=_report([_event()]))

    assert response.status_code == 401


def test_rejects_a_signed_in_upload_without_the_csrf_header(signed_in) -> None:
    response = signed_in.post(_ENDPOINT, json=_report([_event()]))

    assert response.status_code == 403


@pytest.mark.parametrize(
    "report",
    [
        pytest.param(_report([_event(kind="teleported")]), id="unknown-kind"),
        pytest.param(_report([_event()] * 501), id="more-than-500-events"),
        pytest.param(_report([_event(detail="x" * 201)]), id="detail-over-200-chars"),
        pytest.param(_report([_event(deck="third")]), id="unknown-deck"),
        pytest.param(_report([_event(take_id="not-a-uuid")]), id="take-id-not-a-uuid"),
    ],
)
def test_rejects_a_malformed_report(signed_in, report: dict) -> None:
    apply_csrf_header(signed_in)

    response = signed_in.post(_ENDPOINT, json=report)

    assert response.status_code == 422


@pytest.mark.usefixtures("json_logging")
def test_logs_one_line_per_event_carrying_the_user_id(
    signed_in,
    listener_id: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    apply_csrf_header(signed_in)
    _start_json_logging()
    events = [
        _event(kind="fresh_load", deck="standby", visibility="visible"),
        _event(kind="play_rejected", take_id=None, detail="NotAllowedError"),
    ]

    response = signed_in.post(_ENDPOINT, json=_report(events))

    assert response.status_code == 204
    lines = _diagnostic_log_lines(capsys)
    assert [(line["user_id"], line["kind"], line["take_id"]) for line in lines] == [
        (listener_id, "fresh_load", events[0]["take_id"]),
        (listener_id, "play_rejected", None),
    ]
    assert {line["session_id"] for line in lines} == {"a1b2c3"}
    assert all(line["was_discarded"] is False for line in lines)


@pytest.mark.usefixtures("json_logging")
def test_accepts_a_report_with_exactly_500_events(
    signed_in,
    capsys: pytest.CaptureFixture[str],
) -> None:
    apply_csrf_header(signed_in)
    _start_json_logging()

    response = signed_in.post(_ENDPOINT, json=_report([_event()] * 500))

    assert response.status_code == 204
    assert len(_diagnostic_log_lines(capsys)) == 500

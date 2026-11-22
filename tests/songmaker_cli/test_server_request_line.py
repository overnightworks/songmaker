"""The request line's person and client address, as the whole app writes them."""

from __future__ import annotations

from pathlib import Path

import pytest
from logline.testing import configured
from support.request_lines import request_lines
from support.web_app import make_test_app, seed_session, seed_user, web_client

_PROXY_PEER = "172.18.0.1"
_STRANGER = "198.51.100.9"
_FORWARDED_CLIENT = "203.0.113.7"
_PERSON_ID = "person-id"


def _client_behind_the_proxy(tmp_path: Path, pg_factory, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRUSTED_PROXIES", f"{_PROXY_PEER}/32")
    server_app, _ = make_test_app(
        tmp_path, factory=pg_factory,
        seed_db=lambda session: seed_user(session, "owner", user_id=_PERSON_ID),
    )
    return web_client(server_app.app, client=(_PROXY_PEER, 55000), raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("path", "signed_in", "status", "sub"),
    [
        ("/api/auth/me", True, 200, _PERSON_ID),
        ("/api/jobs/no-such-job/stream", True, 404, _PERSON_ID),
        ("/api/jobs/no-such-job/stream", False, 401, None),
    ],
    ids=["a-signed-in-request", "a-stream-request", "an-anonymous-request"],
)
def test_each_request_leaves_one_line_with_its_person_and_its_forwarded_client(
    tmp_path: Path, pg_factory, fresh_settings, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], path: str, signed_in: bool, status: int, sub: str | None,
) -> None:
    """Webauth writes the account and the address the line reports, once."""
    client = _client_behind_the_proxy(tmp_path, pg_factory, monkeypatch)
    if signed_in:
        seed_session(client, "owner")

    with configured("songmaker-web"):
        response = client.get(path, headers={"x-forwarded-for": _FORWARDED_CLIENT})

    (line,) = request_lines(capsys.readouterr().out)
    assert response.status_code == status
    assert (line["sub"], line["ip"]) == (sub, _FORWARDED_CLIENT)


def test_a_cors_preflight_leaves_a_line_naming_the_forwarded_client(
    tmp_path: Path, pg_factory, fresh_settings, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CORS answers a preflight itself; the client address writer sits outside it."""
    client = _client_behind_the_proxy(tmp_path, pg_factory, monkeypatch)

    with configured("songmaker-web"):
        response = client.options(
            "/api/auth/me",
            headers={
                "x-forwarded-for": _FORWARDED_CLIENT,
                "origin": "http://localhost:5173",
                "access-control-request-method": "GET",
            },
        )

    (line,) = request_lines(capsys.readouterr().out)
    assert response.status_code == 200
    assert line["ip"] == _FORWARDED_CLIENT


def test_a_request_from_an_untrusted_peer_leaves_a_line_naming_the_peer(
    tmp_path: Path, pg_factory, fresh_settings, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A forged X-Forwarded-For from a peer no proxy setting trusts names nobody but the peer."""
    monkeypatch.setenv("TRUSTED_PROXIES", f"{_PROXY_PEER}/32")
    server_app, _ = make_test_app(tmp_path, factory=pg_factory)
    stranger = web_client(server_app.app, client=(_STRANGER, 55000))

    with configured("songmaker-web"):
        stranger.get("/api/auth/me", headers={"x-forwarded-for": _FORWARDED_CLIENT})

    (line,) = request_lines(capsys.readouterr().out)
    assert line["ip"] == _STRANGER

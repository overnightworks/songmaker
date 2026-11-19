"""The request line's person and client address, as the whole app writes them."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from logline.testing import configured
from support.request_lines import request_lines
from support.web_app import make_test_app, seed_session, seed_user, web_client
from webauth.config import install_web_auth_config, installed_web_auth_config
from webauth.proxies import TrustedProxies

_PROXY_PEER = "172.18.0.1"
_FORWARDED_CLIENT = "203.0.113.7"
_PERSON_ID = "person-id"


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
    tmp_path: Path, pg_factory, capsys: pytest.CaptureFixture[str],
    path: str, signed_in: bool, status: int, sub: str | None,
) -> None:
    """Both the account and the address the line reports are written by webauth, once."""
    server_app, _ = make_test_app(
        tmp_path, factory=pg_factory,
        seed_db=lambda session: seed_user(session, "owner", user_id=_PERSON_ID),
    )
    install_web_auth_config(
        server_app.app,
        dataclasses.replace(
            installed_web_auth_config(server_app.app),
            trusted_proxies=TrustedProxies.parse(f"{_PROXY_PEER}/32"),
        ),
    )
    client = web_client(server_app.app, client=(_PROXY_PEER, 55000), raise_server_exceptions=False)
    if signed_in:
        seed_session(client, "owner")

    with configured("songmaker-web"):
        response = client.get(path, headers={"x-forwarded-for": _FORWARDED_CLIENT})

    (line,) = request_lines(capsys.readouterr().out)
    assert response.status_code == status
    assert (line["sub"], line["ip"]) == (sub, _FORWARDED_CLIENT)

"""The shared rate limit refuses a listener on every presented-audio route."""

from __future__ import annotations

from pathlib import Path

import pytest
from support.web_app import make_test_app, web_client

import songmaker_cli.constants as consts
from songmaker_cli.shared_access import SHARED_RATE_LIMIT_REFUSAL

_BUDGET = 2


@pytest.mark.parametrize(
    "audio_route",
    ["/shared/{slug}/audio/{name}", "/shared/song/{slug}/audio/{name}",
     "/shared/playlist/{slug}/audio/{name}"],
    ids=["album", "song", "playlist"],
)
def test_presented_audio_route_refuses_a_listener_past_the_budget(
    audio_route: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory,
) -> None:
    monkeypatch.setattr(consts, "SHARING_RATE_LIMIT", _BUDGET)
    client, _ = make_test_app(tmp_path, factory=pg_factory)
    listener = web_client(client.app, cookies={})
    url = audio_route.format(slug="unshared", name="g1.mp3")

    responses = [listener.get(url) for _ in range(_BUDGET + 1)]

    assert 429 not in [response.status_code for response in responses[:_BUDGET]]
    assert responses[-1].status_code == 429
    assert responses[-1].json() == {"detail": SHARED_RATE_LIMIT_REFUSAL}

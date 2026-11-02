"""``GET /api/release``: the release the running image was built for, behind sign-in."""

from __future__ import annotations

import pytest
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.settings import UNKNOWN_COMMIT, UNRELEASED_TAG, get_settings


def test_release_is_refused_without_a_session(tmp_path) -> None:
    app = make_router_app(make_router_ctx(tmp_path))

    assert web_client(app, cookies={}).get("/api/release").status_code == 401


@pytest.mark.parametrize(
    ("release", "commit", "expected"),
    [
        ("v2026.10.28.4", "a" * 40, {"tag": "v2026.10.28.4", "commit": "a" * 40}),
        (None, "b" * 40, {"tag": UNRELEASED_TAG, "commit": "b" * 40}),
        (None, None, {"tag": UNRELEASED_TAG, "commit": UNKNOWN_COMMIT}),
    ],
    ids=["release-build", "commit-without-tag", "neither"],
)
def test_release_names_what_the_image_was_built_for(
    tmp_path, monkeypatch, fresh_settings, release, commit, expected,
) -> None:
    for name, value in (("SONGMAKER_RELEASE", release), ("SONGMAKER_COMMIT", commit)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    app = make_router_app(make_router_ctx(tmp_path), user=make_authenticated_user("u-member"))

    response = web_client(app).get("/api/release")

    assert response.status_code == 200
    assert response.json() == expected

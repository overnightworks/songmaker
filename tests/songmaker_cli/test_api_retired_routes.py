"""A retired route answers like the same method on a path that never existed."""

from __future__ import annotations

import pytest
from support.web_app import make_authenticated_user, make_test_app

from songmaker_cli.auth_dependencies import get_current_user

_RETIRED_ROUTES = [
    pytest.param("POST", "/api/songs/s1/chat", id="per-song-chat"),
    pytest.param("GET", "/api/settings/claude-models", id="get-claude-models"),
    pytest.param("PUT", "/api/settings/claude-models", id="set-claude-models"),
    pytest.param("GET", "/api/admin/audit-log", id="admin-audit-log"),
    pytest.param("GET", "/api/library/shares", id="library-shares"),
    pytest.param("GET", "/api/scoring/schema", id="scoring-schema"),
    pytest.param("POST", "/api/songs/one-take/reimport", id="song-reimport"),
    pytest.param("GET", "/api/capabilities", id="capabilities"),
    pytest.param("GET", "/api/settings/providers", id="get-providers"),
    pytest.param("GET", "/api/settings/judge", id="get-judge"),
    pytest.param("PUT", "/api/settings/judge", id="set-judge"),
    pytest.param("GET", "/api/settings/cowriter/offer", id="cowriter-offer"),
]


@pytest.mark.parametrize("role", ["admin", "user"])
@pytest.mark.parametrize(("method", "path"), _RETIRED_ROUTES)
def test_retired_route_answers_like_an_unknown_path(
    tmp_path, mock_arq_pool, pg_factory, method, path, role
):
    client = make_test_app(tmp_path, factory=pg_factory)[0]
    client.app.dependency_overrides[get_current_user] = lambda: make_authenticated_user(
        "u", role=role
    )
    with client:
        unknown = client.request(method, "/api/nope", json={})
        retired = client.request(method, path, json={})
    assert retired.status_code == unknown.status_code == 404
    assert retired.content == unknown.content

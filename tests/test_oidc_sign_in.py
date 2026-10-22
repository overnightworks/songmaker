"""Signing in, refusals and signing out against a fake Keycloak realm.

The routes run the real relying party; only its token request and key set are
the fake issuer's, so every ID token is verified as in production.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import (
    TEST_CLIENT_SECRET,
    TEST_ORIGIN,
    login_and_csrf,
    make_test_app,
    web_client,
)
from fake_oidc_issuer import Person
from httpx import Response
from oidc_world import World

from songmaker_cli.db.models import USERNAME_MAX_LENGTH, AuditLog, UserSession

MEMBER = "/apps/songmaker"
ADMIN = "/apps/songmaker/admin"
SUBJECT = "6f1d2c3b-aaaa-4bbb-8ccc-0123456789ab"
OTHER_SUBJECT = "0a9b8c7d-dddd-4eee-8fff-ba9876543210"
SESSION_COOKIE = "__Host-session_id"
CSRF_COOKIE = "__Host-csrf_token"
HINT_COOKIE = "__Secure-oidc_id_token_hint"
PENDING_PREFIX = "__Host-oidc_pending_"
SHELL = "<html>Songmaker</html>"
SIGN_IN_ROUTES = ("/login/oidc", "/auth/callback", "/auth/logout")


def _set_cookies(response: Response) -> dict[str, str]:
    return {
        header.split("=", 1)[0]: header for header in response.headers.get_list("set-cookie")
    }


def _cleared(response: Response, name_prefix: str) -> bool:
    return any(
        name.startswith(name_prefix) and "Max-Age=0" in header
        for name, header in _set_cookies(response).items()
    )


def _member(subject: str = SUBJECT, username: str = "felix", *groups: str) -> Person:
    return Person(subject, username, groups or (MEMBER,))


# -- M2 / M3: who the account is -------------------------------------------------


def test_the_operator_is_admitted_into_the_existing_row_and_made_admin_by_the_group(
    world: World,
) -> None:
    world.seed(SUBJECT, "felix", "user")

    response = world.sign_in(_member(SUBJECT, "felix-in-keycloak", MEMBER, ADMIN))

    assert (response.status_code, response.headers["location"]) == (303, "/")
    assert world.users() == [(SUBJECT, "felix", "admin")]
    assert world.client.get("/api/auth/me").json()["role"] == "admin"


def test_a_new_member_gets_a_fresh_account_even_when_the_username_is_taken(world: World) -> None:
    world.seed(SUBJECT, "felix", "admin")

    response = world.sign_in(_member(OTHER_SUBJECT, "felix"))

    assert response.status_code == 303
    assert world.users() == [
        (OTHER_SUBJECT, "felix", "user"),
        (SUBJECT, "felix", "admin"),
    ]
    assert world.client.get("/api/auth/me").json()["id"] == OTHER_SUBJECT


def test_a_username_longer_than_the_column_is_cut_and_the_sign_in_succeeds(world: World) -> None:
    response = world.sign_in(_member(OTHER_SUBJECT, "n" * 250))

    assert response.status_code == 303
    assert world.users() == [(OTHER_SUBJECT, "n" * USERNAME_MAX_LENGTH, "user")]


def test_creating_an_account_and_changing_a_role_are_audited_without_a_person(
    world: World,
) -> None:
    world.sign_in(_member(SUBJECT, "felix", MEMBER))
    world.sign_in(_member(SUBJECT, "felix", MEMBER, ADMIN))

    with world.factory() as session:
        entries = [(e.user_id, e.action, e.detail) for e in session.query(AuditLog).all()]
    assert entries == [(None, "create", "role=user"), (None, "update", "role=admin")]


# -- M4: outsiders ---------------------------------------------------------------


@pytest.mark.parametrize("groups", [(), ("/apps/other",), ("/apps/songmaker2",)])
def test_an_outsider_is_sent_to_no_access_and_leaves_nothing_behind(
    world: World, groups: tuple[str, ...],
) -> None:
    response = world.sign_in(Person(SUBJECT, "stranger", groups))

    assert (response.status_code, response.headers["location"]) == (303, "/no-access")
    assert world.users() == []
    assert world.session_count() == 0
    assert SESSION_COOKIE not in _set_cookies(response)
    assert _cleared(response, PENDING_PREFIX)


# -- M5: refusals ----------------------------------------------------------------


def _assert_the_failure_page(world: World, response: Response) -> None:
    assert response.status_code == 403
    assert response.text == SHELL
    assert response.headers["content-type"].startswith("text/html")
    assert SESSION_COOKIE not in _set_cookies(response)
    assert world.users() == []
    assert world.session_count() == 0


def test_a_foreign_issuer_gets_the_failure_page_and_writes_nothing(world: World) -> None:
    world.issuer.token_issuer = "https://evil.test/realms/test"

    response = world.sign_in(_member())

    _assert_the_failure_page(world, response)
    assert _cleared(response, PENDING_PREFIX)


def test_a_state_mismatch_gets_the_failure_page_and_keeps_the_real_pending_login(
    world: World,
) -> None:
    started = world.start()

    response = world.callback(_member(), started, state="not-the-state-we-issued")

    _assert_the_failure_page(world, response)
    real_pending_login = {
        name for name in _set_cookies(started) if name.startswith(PENDING_PREFIX)
    }
    cleared = {
        name for name, header in _set_cookies(response).items() if "Max-Age=0" in header
    }
    assert real_pending_login
    assert not real_pending_login & cleared
    assert world.callback(_member(), started).status_code == 303


def test_an_expired_pending_login_gets_the_failure_page_and_clears_the_pending_login(
    world: World,
) -> None:
    started = world.start()
    world.issuer.now += 601

    response = world.callback(_member(), started)

    _assert_the_failure_page(world, response)
    assert _cleared(response, PENDING_PREFIX)


def test_a_callback_without_a_pending_login_gets_the_failure_page(world: World) -> None:
    response = world.client.get(
        "/auth/callback", params={"code": "c", "state": "s"}, follow_redirects=False,
    )

    _assert_the_failure_page(world, response)


# -- M6: a failing commit --------------------------------------------------------


def test_a_commit_failure_leaves_no_cookie_account_or_session(
    world: World, session_commit_failure,
) -> None:
    commits = 0

    def fail_the_commit_that_would_persist_the_account(_session) -> bool:
        nonlocal commits
        commits += 1
        return commits == 2

    failing = web_client(world.client.app, raise_server_exceptions=False, cookies={})
    started = failing.get("/login/oidc", follow_redirects=False)
    state, code = world.issuer.remember_authorization(started.headers["location"])
    world.issuer.person = _member()

    with session_commit_failure(
        world.factory, message="commit failed",
        when=fail_the_commit_that_would_persist_the_account,
    ):
        response = failing.get(
            "/auth/callback", params={"code": code, "state": state}, follow_redirects=False,
        )

    assert response.status_code == 500
    assert SESSION_COOKIE not in _set_cookies(response)
    assert world.users() == []
    assert world.session_count() == 0


# -- M7: where the sign-in returns -----------------------------------------------


@pytest.mark.parametrize(
    ("next_path", "lands_on"),
    [
        ("/albums/x", "/albums/x"),
        ("/albums/x?tab=songs", "/albums/x?tab=songs"),
        ("//evil.example", "/"),
        ("https://evil.example/", "/"),
        ("/\\evil.example", "/"),
        (None, "/"),
    ],
)
def test_the_sign_in_returns_to_a_page_of_this_app_only(
    world: World, next_path: str | None, lands_on: str,
) -> None:
    response = world.sign_in(_member(), next_path)

    assert (response.status_code, response.headers["location"]) == (303, lands_on)


# -- M8: the groups decide at every sign-in --------------------------------------


@pytest.mark.parametrize(
    ("first", "second"),
    [((MEMBER, ADMIN), (MEMBER,)), ((MEMBER,), (MEMBER, ADMIN))],
)
def test_an_admin_change_in_the_realm_applies_at_the_next_sign_in(
    world: World, first: tuple[str, ...], second: tuple[str, ...],
) -> None:
    world.sign_in(Person(SUBJECT, "felix", first))
    role_before = world.client.get("/api/auth/me").json()["role"]

    world.sign_in(Person(SUBJECT, "felix", second))

    role_after = world.client.get("/api/auth/me").json()["role"]
    assert {role_before, role_after} == {"admin", "user"}
    assert role_after == ("admin" if ADMIN in second else "user")


def test_a_member_removed_from_the_group_is_refused_at_the_next_sign_in(world: World) -> None:
    world.sign_in(_member())

    response = world.sign_in(Person(SUBJECT, "felix", ()))

    assert response.headers["location"] == "/no-access"
    assert world.users() == [(SUBJECT, "felix", "user")]


# -- M19: logging out ------------------------------------------------------------


def _same_origin() -> dict[str, str]:
    return {"origin": TEST_ORIGIN}


def test_logging_out_ends_the_session_clears_the_cookies_and_returns_the_hinted_url(
    world: World,
) -> None:
    world.sign_in(_member())
    session_cookie = world.client.cookies.get(SESSION_COOKIE)

    response = world.client.post("/auth/logout", headers=_same_origin())

    assert response.status_code == 200
    logout_url = response.json()["logout_url"]
    assert logout_url.startswith("https://issuer.test/realms/test/protocol/openid-connect/logout?")
    assert "id_token_hint=" in logout_url
    assert "client_id=songmaker-test" in logout_url
    assert all(
        _cleared(response, prefix) for prefix in (SESSION_COOKIE, CSRF_COOKIE, HINT_COOKIE)
    )
    assert world.session_count() == 0
    reused = web_client(world.client.app, cookies={SESSION_COOKIE: session_cookie})
    assert reused.get("/api/auth/me").status_code == 401


def test_logging_out_without_a_session_still_clears_cookies_and_returns_the_url(
    world: World,
) -> None:
    response = world.client.post("/auth/logout", headers=_same_origin())

    assert response.status_code == 200
    assert "id_token_hint=" not in response.json()["logout_url"]
    assert all(
        _cleared(response, prefix) for prefix in (SESSION_COOKIE, CSRF_COOKIE, HINT_COOKIE)
    )


def test_a_cross_origin_logout_is_refused_and_keeps_the_session(world: World) -> None:
    world.sign_in(_member())

    response = world.client.post("/auth/logout", headers={"origin": "https://evil.example"})

    assert response.status_code == 403
    assert world.session_count() == 1


def test_logging_out_is_post_only(world: World) -> None:
    assert world.client.get("/auth/logout").status_code == 405


def test_the_token_exemption_covers_the_logout_and_the_workers_only(world: World) -> None:
    world.seed(SUBJECT, "felix", "admin")
    login_and_csrf(world.client, "felix")
    del world.client.headers["X-CSRF-Token"]

    refused = world.client.post("/api/albums", json={"title": "A"}, headers=_same_origin())
    worker = world.client.post("/api/internal/workers/register", json={})

    assert refused.status_code == 403
    assert worker.status_code != 403


# -- M18: callers without a session ----------------------------------------------


def test_an_anonymous_share_manifest_post_passes_the_csrf_checks(world: World) -> None:
    response = world.client.post("/shared/no-such-share/stream", json={})

    assert response.status_code == 404


def test_a_worker_call_with_the_internal_token_passes_the_csrf_checks(world: World) -> None:
    from songmaker_cli.settings import get_settings

    token = get_settings().songmaker_internal_token.get_secret_value()

    response = world.client.post(
        "/api/internal/workers/register", json={}, headers={"X-Internal-Token": token},
    )

    assert response.status_code == 422


# -- M21 / M23: headers and cookies ----------------------------------------------


def test_the_three_routes_answer_no_store_even_when_they_refuse(world: World) -> None:
    started = world.start()
    refused = world.client.get("/auth/callback", follow_redirects=False)
    admitted = world.callback(_member(), started)
    logged_out = world.client.post("/auth/logout", headers=_same_origin())

    for response in (started, refused, admitted, logged_out):
        assert response.headers["cache-control"] == "no-store"


def test_the_cookies_carry_the_flags_the_library_defines(world: World) -> None:
    started = world.start()
    admitted = world.callback(_member(), started)

    pending = next(h for n, h in _set_cookies(started).items() if n.startswith(PENDING_PREFIX))
    cookies = _set_cookies(admitted)
    assert {"Secure", "HttpOnly", "SameSite=lax", "Path=/"} <= _flags(pending)
    assert {"Secure", "HttpOnly", "SameSite=strict", "Path=/"} <= _flags(cookies[SESSION_COOKIE])
    assert {"Secure", "SameSite=strict", "Path=/"} <= _flags(cookies[CSRF_COOKIE])
    assert "HttpOnly" not in _flags(cookies[CSRF_COOKIE])
    assert {"Secure", "HttpOnly", "SameSite=strict", "Path=/auth/logout"} <= _flags(
        cookies[HINT_COOKIE],
    )


def _flags(set_cookie: str) -> set[str]:
    return {part.strip().replace("samesite", "SameSite") for part in set_cookie.split(";")[1:]}


def test_the_start_route_answers_a_redirect_to_the_realm(world: World) -> None:
    started = world.start("/albums/x")

    assert started.status_code == 303
    assert started.headers["location"].startswith(
        "https://issuer.test/realms/test/protocol/openid-connect/auth?",
    )


# -- M24: the issuer is down -----------------------------------------------------


def test_with_the_issuer_down_signed_in_requests_work_and_a_new_sign_in_shows_the_failure(
    world: World,
) -> None:
    world.sign_in(_member())
    world.issuer.unreachable = True

    assert world.client.get("/api/auth/me").status_code == 200

    other = web_client(world.client.app, cookies={})
    started = other.get("/login/oidc", follow_redirects=False)
    state, code = world.issuer.remember_authorization(started.headers["location"])
    failed = other.get(
        "/auth/callback", params={"code": code, "state": state}, follow_redirects=False,
    )
    assert (failed.status_code, failed.text) == (403, SHELL)
    assert SESSION_COOKIE not in _set_cookies(failed)


# -- M20: the client secret -------------------------------------------------------


@pytest.mark.parametrize("fault", ["missing", "empty", "directory"])
def test_an_unusable_secret_file_stops_the_web_app_and_names_only_its_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fresh_settings, fault: str,
) -> None:
    secret_file = tmp_path / "keycloak_client_secret"
    if fault == "empty":
        secret_file.write_text("")
    elif fault == "directory":
        secret_file.mkdir()
    monkeypatch.setenv("OIDC_CLIENT_SECRET_FILE", str(secret_file))

    with pytest.raises(ValueError, match=str(secret_file)) as stopped:
        make_test_app(tmp_path)

    assert TEST_CLIENT_SECRET not in str(stopped.value)


@pytest.mark.parametrize("missing", ["OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET_FILE"])
def test_a_missing_realm_setting_stops_the_web_app_but_not_the_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fresh_settings, missing: str,
) -> None:
    from songmaker_cli.settings import get_settings

    monkeypatch.delenv(missing)

    assert get_settings().oidc_issuer is None or missing != "OIDC_ISSUER"
    with pytest.raises(ValueError, match=missing):
        make_test_app(tmp_path)


def test_the_music_and_scoring_workers_start_without_any_realm_variable_or_secret_file(
    monkeypatch: pytest.MonkeyPatch, fresh_settings,
) -> None:
    for variable in ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET_FILE"):
        monkeypatch.delenv(variable)
    # Both entry modules read the settings when they are first imported.
    from songmaker_cli.music_worker import MusicWorker, _music_worker_functions
    from songmaker_cli.scoring_worker import ScoringWorker
    from songmaker_cli.settings import get_settings
    from songmaker_cli.worker_base import build_redis_settings

    get_settings.cache_clear()
    settings = get_settings()

    assert (
        settings.oidc_issuer, settings.oidc_client_id, settings.oidc_client_secret_file,
    ) == (None, None, None)
    assert build_redis_settings(settings) is not None
    assert _music_worker_functions(MusicWorker(settings), settings)
    assert ScoringWorker(settings).queue_name


def test_the_secret_is_in_no_log_and_no_response_of_the_sign_in(world: World, caplog) -> None:
    with caplog.at_level("DEBUG"):
        responses = [
            world.sign_in(_member()),
            world.client.get("/api/auth/me"),
            world.client.post("/auth/logout", headers=_same_origin()),
        ]

    assert TEST_CLIENT_SECRET not in caplog.text
    for response in responses:
        assert TEST_CLIENT_SECRET not in response.text
        assert TEST_CLIENT_SECRET not in str(response.headers)


def test_the_refresh_token_is_stored_with_the_session_and_reaches_no_log_or_response(
    world: World, caplog,
) -> None:
    refresh_token = "rt-0123456789-never-shown"
    person = Person(SUBJECT, "felix", (MEMBER,), refresh_token)

    with caplog.at_level("DEBUG"):
        responses = [
            world.sign_in(person),
            world.client.get("/api/auth/me"),
            world.client.post("/auth/logout", headers=_same_origin()),
        ]
        with world.client:
            responses.append(world.client.get("/health"))

    assert refresh_token not in caplog.text
    for response in responses:
        assert refresh_token not in response.text
        assert refresh_token not in str(response.headers)


def test_a_sign_in_keeps_the_issued_refresh_token_in_the_session_row(world: World) -> None:
    person = Person(SUBJECT, "felix", (MEMBER,), "rt-0123456789-stored")

    world.sign_in(person)

    with world.factory() as session:
        stored = session.query(UserSession).one().refresh_token
    assert stored is not None
    assert stored.get_secret_value() == "rt-0123456789-stored"
    assert "rt-0123456789-stored" not in repr(stored)


def test_health_carries_neither_the_secret_nor_the_path_it_is_read_from(world: World) -> None:
    with world.client:
        response = world.client.get("/health")

    assert TEST_CLIENT_SECRET not in response.text
    assert os.environ["OIDC_CLIENT_SECRET_FILE"] not in response.text


# -- M22: the Host header ---------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "status"),
    [
        ("hallucinai.de", 400),
        ("evil.example", 400),
        ("songmaker.hallucinai.de", 401),
        ("localhost:8080", 401),
        ("songmaker-web:8080", 401),
    ],
)
def test_only_the_configured_hosts_are_served(
    tmp_path: Path, fresh_settings, host: str, status: int,
) -> None:
    hosts = "songmaker.hallucinai.de,localhost,127.0.0.1,songmaker-web"
    with patch.dict("os.environ", {"ALLOWED_HOSTS": hosts}):
        client, _ = make_test_app(tmp_path)

    assert client.get("/api/auth/me", headers={"host": host}).status_code == status


def test_the_realm_endpoints_are_derived_from_the_issuer() -> None:
    from songmaker_cli.oidc_client import build_oidc_client_config
    from songmaker_cli.settings import get_settings

    config = build_oidc_client_config(get_settings())

    realm = "https://issuer.test/realms/test/protocol/openid-connect"
    assert (config.authorization_endpoint, config.token_endpoint, config.jwks_url) == (
        f"{realm}/auth", f"{realm}/token", f"{realm}/certs",
    )
    assert config.end_session_endpoint == f"{realm}/logout"
    assert config.redirect_uri == "https://songmaker.test/auth/callback"
    assert config.post_logout_redirect_uri == "https://songmaker.test/login"


# -- M10: the cookies of the password era -----------------------------------------


def test_a_cookie_signed_the_old_way_is_refused_even_for_a_live_session(world: World) -> None:
    import hashlib
    import hmac

    from conftest import TEST_SECRET

    world.sign_in(_member())
    with world.factory() as session:
        session_id = session.query(UserSession).one().id
    legacy_signature = hmac.new(TEST_SECRET, session_id.encode(), hashlib.sha256).hexdigest()
    old = web_client(world.client.app, cookies={SESSION_COOKIE: f"{session_id}.{legacy_signature}"})

    assert old.get("/api/auth/me").status_code == 401

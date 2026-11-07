"""How many sessions one account holds, what ends them, and that no route creates an account."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from support.fake_oidc_issuer import Person
from support.oidc_world import World
from support.web_app import TEST_ORIGIN, web_client

from songmaker_cli.db.models import UserSession
from songmaker_cli.settings import get_settings

MEMBER = "/apps/songmaker"
SUBJECT = "6f1d2c3b-aaaa-4bbb-8ccc-0123456789ab"


def _sign_in_in_a_new_browser(world: World) -> TestClient:
    browser = web_client(world.client.app, cookies={})
    started = browser.get("/login/oidc", follow_redirects=False)
    state, code = world.issuer.remember_authorization(started.headers["location"])
    world.issuer.person = Person(SUBJECT, "felix", (MEMBER,))
    browser.get("/auth/callback", params={"code": code, "state": state}, follow_redirects=False)
    return browser


def _sign_in_each_a_minute_after_the_last(world: World, count: int) -> list[TestClient]:
    """Sign in ``count`` browsers; the clock has second resolution, so age each new row."""
    first_start = datetime.now(timezone.utc) - timedelta(hours=1)
    browsers = []
    for index in range(count):
        with world.factory() as session:
            known = [row.id for row in session.query(UserSession)]
        browsers.append(_sign_in_in_a_new_browser(world))
        with world.factory() as session:
            for row in session.query(UserSession).filter(UserSession.id.not_in(known)):
                row.created_at = first_start + timedelta(minutes=index)
            session.commit()
    return browsers


def _is_signed_in(browser: TestClient) -> bool:
    return browser.get("/api/auth/me").status_code == 200


def test_signing_in_from_a_second_browser_leaves_the_first_session_working(world: World) -> None:
    """Spec: REQ-ADMIN-08 -- two browsers signed in as one account are two live sessions."""
    first = _sign_in_in_a_new_browser(world)

    second = _sign_in_in_a_new_browser(world)

    assert world.session_count() == 2
    assert (_is_signed_in(first), _is_signed_in(second)) == (True, True)


def test_logging_out_one_browser_leaves_the_other_session_working(world: World) -> None:
    """Spec: REQ-ADMIN-09 -- a logout ends the session of its own browser and no other."""
    leaving = _sign_in_in_a_new_browser(world)
    staying = _sign_in_in_a_new_browser(world)

    response = leaving.post("/auth/logout", headers={"origin": TEST_ORIGIN})

    assert response.status_code == 200
    assert world.session_count() == 1
    assert (_is_signed_in(leaving), _is_signed_in(staying)) == (False, True)


def test_past_the_session_limit_the_oldest_sessions_end_and_the_newer_ones_stay(
    world: World,
) -> None:
    """Spec: REQ-ADMIN-11 -- the sessions beyond the cap that end are the oldest, not all."""
    limit = get_settings().max_concurrent_sessions_per_user

    browsers = _sign_in_each_a_minute_after_the_last(world, limit + 2)

    ended, kept = browsers[:2], browsers[2:]
    assert [_is_signed_in(browser) for browser in ended] == [False, False]
    assert all(_is_signed_in(browser) for browser in kept)
    assert world.session_count() == limit


def test_no_operation_of_the_api_creates_an_account(world: World) -> None:
    """Spec: REQ-ADMIN-05 -- the API schema names no operation that adds a user; admission at
    sign-in is the only way an account appears."""
    operations = [
        (method, path)
        for path, methods in world.client.app.openapi()["paths"].items()
        for method in methods
        if method in {"post", "put", "patch"}
    ]

    naming_an_account = [
        (method, path)
        for method, path in operations
        if any(word in path.lower() for word in ("user", "account", "member"))
    ]

    assert naming_an_account == [("put", "/api/memory/user")]
    assert world.users() == []
    _sign_in_in_a_new_browser(world)
    assert [subject for subject, _, _ in world.users()] == [SUBJECT]

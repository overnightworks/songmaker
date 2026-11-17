"""The language of the pages the server answers: the shell, the sign-in start, the sign-out page."""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy.exc import OperationalError
from support.fake_oidc_issuer import Person
from support.oidc_world import World
from support.web_app import TEST_ORIGIN, make_test_app, seed_session, seed_user
from webauth.languages import AppLanguages

from songmaker_cli import page_language
from songmaker_cli.db.models import UserSession
from songmaker_cli.page_language import PageShellError
from songmaker_cli.words import SOURCE_LANGUAGE, text

SHELL = "<html><head></head><body>Songmaker</body></html>"
ENGLISH_SHELL = '<html lang="en"><head></head><body>Songmaker</body></html>'
ENGLISH_AND_GERMAN = AppLanguages(offered=("en", "de"), default="en")
A_PAGE = "/albums/a-song"
MEMBER = "/apps/songmaker"


@pytest.fixture
def offering_german(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page_language, "APP_LANGUAGES", ENGLISH_AND_GERMAN)


def _lang_of(html: str) -> str:
    return html.split("<html lang=", 1)[1].split(">", 1)[0].strip('"')


def _shell_app(tmp_path: Path, pg_factory, index_html: str = SHELL):
    client, factory = make_test_app(
        tmp_path, lambda session: seed_user(session, "felix", "user"),
        index_html=index_html, factory=pg_factory,
    )
    return client, factory


def test_the_shell_names_its_language_and_is_otherwise_the_built_page(
    tmp_path: Path, pg_factory,
) -> None:
    client, _ = _shell_app(tmp_path, pg_factory)

    response = client.get(A_PAGE)

    assert response.status_code == 200
    assert response.text == SHELL.replace("<html>", f'<html lang="{SOURCE_LANGUAGE}">')


def test_the_shell_is_revalidated_and_differs_by_what_picks_its_language(
    tmp_path: Path, pg_factory,
) -> None:
    client, _ = _shell_app(tmp_path, pg_factory)

    response = client.get(A_PAGE)

    assert response.headers["cache-control"] == "no-cache"
    assert "etag" not in response.headers
    assert "last-modified" not in response.headers
    varied = {name.strip().lower() for name in response.headers["vary"].split(",")}
    assert {"accept-language", "cookie"} <= varied


@pytest.mark.parametrize(
    ("accept_language", "expected"),
    [("de-AT,en;q=0.5", "de"), ("en-GB", "en"), ("fr", "en"), ("de;q=0", "en"), (None, "en")],
)
def test_the_shell_follows_the_browser_among_the_offered_languages(
    tmp_path: Path, pg_factory, offering_german: None, accept_language: str | None, expected: str,
) -> None:
    client, _ = _shell_app(tmp_path, pg_factory)
    headers = {} if accept_language is None else {"Accept-Language": accept_language}

    assert _lang_of(client.get(A_PAGE, headers=headers).text) == expected


def _store_account_language(factory, language: str) -> None:
    with factory() as session:
        session.query(UserSession).update({UserSession.account_language: language})
        session.commit()


def test_the_account_language_of_the_session_beats_the_browser(
    tmp_path: Path, pg_factory, offering_german: None,
) -> None:
    client, factory = _shell_app(tmp_path, pg_factory)
    seed_session(client, "felix")
    _store_account_language(factory, "de-AT")

    response = client.get(A_PAGE, headers={"Accept-Language": "en"})

    assert _lang_of(response.text) == "de"


def test_a_failing_session_store_leaves_the_browser_to_decide_and_is_logged(
    tmp_path: Path, pg_factory, offering_german: None, caplog: pytest.LogCaptureFixture,
) -> None:
    client, _ = _shell_app(tmp_path, pg_factory)
    seed_session(client, "felix")

    def unreachable_store():
        raise OperationalError("connect", {}, ConnectionError("store down"))

    client.app.state.ctx.db = unreachable_store
    with caplog.at_level(logging.ERROR, logger=page_language.__name__):
        response = client.get(A_PAGE, headers={"Accept-Language": "de"})

    assert (response.status_code, _lang_of(response.text)) == (200, "de")
    assert [record.levelno for record in caplog.records] == [logging.ERROR]
    assert caplog.records[0].exc_info is not None


MARKUP = '"><script>alert(1)</script>'
FORGED_SESSION_VALUES = {
    "markup as the id": f"{MARKUP}.0123456789abcdef",
    "no signature": "no-signature-at-all",
    "a real id with a wrong signature": "REAL.0123456789abcdef",
}


@pytest.mark.parametrize(
    "accept_language",
    [MARKUP, f"de{MARKUP}", "de-<script>"],
)
def test_a_hostile_accept_language_leaves_the_shell_english_and_free_of_its_markup(
    tmp_path: Path, pg_factory, offering_german: None, accept_language: str,
) -> None:
    client, _ = _shell_app(tmp_path, pg_factory)

    response = client.get(A_PAGE, headers={"Accept-Language": accept_language})

    assert response.status_code == 200
    assert response.text == ENGLISH_SHELL


@pytest.mark.parametrize("forged", FORGED_SESSION_VALUES.values(), ids=FORGED_SESSION_VALUES)
def test_a_forged_session_cookie_leaves_the_shell_english_and_free_of_its_markup(
    tmp_path: Path, pg_factory, offering_german: None, forged: str,
) -> None:
    client, factory = _shell_app(tmp_path, pg_factory)
    seed_session(client, "felix")
    _store_account_language(factory, "de")
    cookie_name, real_cookie = next(iter(client.cookies.items()))
    client.cookies.clear()
    client.cookies.set(cookie_name, forged.replace("REAL", real_cookie.partition(".")[0]))

    response = client.get(A_PAGE)

    assert response.status_code == 200
    assert response.text == ENGLISH_SHELL


@pytest.mark.parametrize(
    "index_html",
    ['<html lang="en"><body></body></html>', "<body>no root</body>", "<html><html></html>"],
)
def test_a_built_page_without_one_bare_html_element_stops_the_start(
    tmp_path: Path, pg_factory, index_html: str,
) -> None:
    with pytest.raises(PageShellError):
        _shell_app(tmp_path, pg_factory, index_html)


def test_a_failed_sign_in_shows_the_shell_in_the_resolved_language(
    world: World, offering_german: None,
) -> None:
    response = world.client.get(
        "/auth/callback", headers={"Accept-Language": "de"}, follow_redirects=False,
    )

    assert response.status_code == 403
    assert _lang_of(response.text) == "de"
    assert "etag" not in response.headers
    assert "accept-language" in response.headers["vary"].lower()
    # The sign-in policy's `no-store` replaces the shell's own `no-cache` on this path.
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("accept_language", "expected"), [("de", "de"), ("fr", "en"), (None, "en")],
)
def test_the_sign_in_start_names_the_resolved_language_to_the_issuer(
    world: World, offering_german: None, accept_language: str | None, expected: str,
) -> None:
    headers = {} if accept_language is None else {"Accept-Language": accept_language}

    response = world.client.get("/login/oidc", headers=headers, follow_redirects=False)

    assert parse_qs(urlsplit(response.headers["location"]).query)["ui_locales"] == [expected]


def test_the_sign_out_page_carries_the_resolved_language_and_its_catalog_label(
    world: World,
) -> None:
    world.sign_in(Person("6f1d2c3b-aaaa-4bbb-8ccc-0123456789ab", "felix", (MEMBER,)))

    response = world.client.post("/auth/logout", headers={"Origin": TEST_ORIGIN})

    assert response.status_code == 200
    assert _lang_of(response.text) == SOURCE_LANGUAGE
    assert f">{text(SOURCE_LANGUAGE, 'logoutPage.logOut')}</button>" in response.text

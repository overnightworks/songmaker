"""The realm's back-channel logout ends the sessions of the subject it names."""

from __future__ import annotations

import pytest
from conftest import web_client
from fake_oidc_issuer import Person
from httpx import Response
from oidc_world import World
from sqlalchemy.orm import Session

from songmaker_cli.auth_stores import DatabaseAuditSink
from songmaker_cli.db.models import AuditLog, UserSession

MEMBER = "/apps/songmaker"
SUBJECT = "6f1d2c3b-aaaa-4bbb-8ccc-0123456789ab"
OTHER_SUBJECT = "0a9b8c7d-dddd-4eee-8fff-ba9876543210"

BACKCHANNEL_PATH = "/auth/backchannel-logout"
BACKCHANNEL_HOST = "songmaker.test:8080"
FORM = {"content-type": "application/x-www-form-urlencoded"}
BACKCHANNEL_MAX_BODY_BYTES = 32 * 1024


def _member(subject: str) -> Person:
    return Person(subject, "felix", (MEMBER,))


def _backchannel(world: World, token: str | None, **headers: str) -> Response:
    sent = {"host": BACKCHANNEL_HOST, **FORM, **headers}
    data = None if token is None else {"logout_token": token}
    # The library answers a failing transaction with 400 and then re-raises it.
    realm = web_client(world.client.app, raise_server_exceptions=False, cookies={})
    return realm.post(BACKCHANNEL_PATH, data=data, headers=sent)


def _sign_in_twice(world: World, subject: str = SUBJECT) -> None:
    """Two browsers, so the subject holds two sessions."""
    world.sign_in(_member(subject))
    other_browser = World(web_client(world.client.app, cookies={}), world.factory, world.issuer)
    other_browser.sign_in(_member(subject))


def test_a_valid_logout_token_ends_every_session_of_its_subject(world: World) -> None:
    _sign_in_twice(world)
    _sign_in_twice(world, OTHER_SUBJECT)

    response = _backchannel(world, world.issuer.logout_token(SUBJECT))

    assert response.status_code == 200
    with world.factory() as session:
        remaining = {row.user_id for row in session.query(UserSession).all()}
        audited = session.query(AuditLog).filter_by(resource_id=SUBJECT, action="delete").count()
    assert remaining == {OTHER_SUBJECT}
    assert audited == 1


def test_a_failing_deleting_transaction_answers_400_and_keeps_the_sessions(
    world: World, session_commit_failure,
) -> None:
    _sign_in_twice(world)

    def ends_the_sessions(session: Session) -> bool:
        """False for the lock's empty pre-commit, true only in the deleting transaction."""
        return session.query(UserSession).filter_by(user_id=SUBJECT).count() == 0

    with session_commit_failure(world.factory, when=ends_the_sessions):
        response = _backchannel(world, world.issuer.logout_token(SUBJECT))

    assert response.status_code == 400
    assert world.session_count() == 2
    with world.factory() as session:
        assert session.query(AuditLog).filter_by(resource_id=SUBJECT, action="delete").count() == 0


def test_an_audit_failure_after_the_deletion_answers_400_and_keeps_the_sessions(
    world: World, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sign_in_twice(world)

    def fail(*_args, **_kwargs) -> None:
        raise RuntimeError("audit sink failed")

    monkeypatch.setattr(DatabaseAuditSink, "account_event", fail)
    response = _backchannel(world, world.issuer.logout_token(SUBJECT))

    assert (response.status_code, response.content) == (400, b"")
    assert world.session_count() == 2


def test_a_failure_to_build_the_database_session_answers_400_and_keeps_the_sessions(
    world: World, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sign_in_twice(world)
    valid_token = world.issuer.logout_token(SUBJECT)

    def fail(*_args, **_kwargs) -> None:
        raise RuntimeError("database session failed")

    with monkeypatch.context() as failing:
        failing.setattr(Session, "__init__", fail)
        response = _backchannel(world, valid_token)

    assert (response.status_code, response.content) == (400, b"")
    assert world.session_count() == 2


def test_a_logout_for_a_subject_without_an_account_is_accepted_and_ends_nothing(
    world: World,
) -> None:
    _sign_in_twice(world)

    response = _backchannel(world, world.issuer.logout_token(OTHER_SUBJECT))

    assert response.status_code == 200
    assert world.session_count() == 2


def _forged(world: World) -> str:
    from cryptography.hazmat.primitives.asymmetric import rsa

    return world.issuer.sign(
        {
            "iss": world.issuer.issuer, "aud": world.issuer.client_id, "sub": SUBJECT,
            "iat": int(world.issuer.now), "exp": int(world.issuer.now) + 60,
            "events": {"http://schemas.openid.net/event/backchannel-logout": {}},
        },
        key=rsa.generate_private_key(65537, 2048),
    )


@pytest.mark.parametrize(
    "make_token",
    [
        pytest.param(_forged, id="forged-signature"),
        pytest.param(lambda w: w.issuer.logout_token(SUBJECT, aud="other"), id="wrong-aud"),
        pytest.param(lambda w: w.issuer.logout_token(SUBJECT, iss="https://evil"), id="wrong-iss"),
        pytest.param(
            lambda w: w.issuer.sign(
                {"iss": w.issuer.issuer, "aud": w.issuer.client_id, "sub": SUBJECT,
                 "iat": int(w.issuer.now), "exp": int(w.issuer.now) + 60,
                 "events": {"http://schemas.openid.net/event/backchannel-logout": {}}},
                token_type="JWT",
            ),
            id="wrong-typ",
        ),
        pytest.param(lambda w: w.issuer.logout_token(None, sid="a-session"), id="sid-only"),
        pytest.param(lambda w: w.issuer.logout_token(SUBJECT, nonce="n"), id="nonce"),
        pytest.param(lambda w: w.issuer.logout_token(SUBJECT, events={}), id="no-event"),
    ],
)
def test_a_refused_logout_token_answers_400_and_ends_nothing(world: World, make_token) -> None:
    _sign_in_twice(world)

    response = _backchannel(world, make_token(world))

    assert response.status_code == 400
    assert world.session_count() == 2


@pytest.mark.parametrize(
    ("headers", "body"),
    [
        pytest.param({"content-type": "application/json"}, b'{"logout_token": "x"}', id="json"),
        pytest.param(FORM, b"", id="empty"),
        pytest.param(FORM, b"logout_token=a&logout_token=b", id="twice"),
    ],
)
def test_a_body_that_is_not_one_logout_token_form_answers_400(
    world: World, headers: dict[str, str], body: bytes,
) -> None:
    response = world.client.post(
        BACKCHANNEL_PATH, content=body, headers={"host": BACKCHANNEL_HOST, **headers},
    )

    assert response.status_code == 400


@pytest.mark.parametrize(
    "host", ["songmaker.test", "songmaker-web:8080", "localhost:8080", "testserver"],
)
def test_a_wrong_host_gets_an_empty_404_and_ends_nothing(world: World, host: str) -> None:
    _sign_in_twice(world)

    response = _backchannel(world, world.issuer.logout_token(SUBJECT), host=host)

    assert (response.status_code, response.content) == (404, b"")
    assert world.session_count() == 2


def test_an_unlisted_host_gets_the_trusted_host_400_and_ends_nothing(world: World) -> None:
    _sign_in_twice(world)

    response = _backchannel(world, world.issuer.logout_token(SUBJECT), host="evil.example:8080")

    assert response.status_code == 400
    assert world.session_count() == 2


def test_a_body_over_32_kib_gets_413(world: World) -> None:
    response = world.client.post(
        BACKCHANNEL_PATH,
        content=b"logout_token=" + b"a" * BACKCHANNEL_MAX_BODY_BYTES,
        headers={"host": BACKCHANNEL_HOST, **FORM},
    )

    assert response.status_code == 413


def test_every_answer_of_the_back_channel_carries_no_store(world: World) -> None:
    _sign_in_twice(world)
    big = b"logout_token=" + b"a" * BACKCHANNEL_MAX_BODY_BYTES

    answers = [
        _backchannel(world, world.issuer.logout_token(SUBJECT)),
        _backchannel(world, "garbage"),
        _backchannel(world, world.issuer.logout_token(SUBJECT), host="localhost:8080"),
        world.client.post(
            BACKCHANNEL_PATH, content=big, headers={"host": BACKCHANNEL_HOST, **FORM},
        ),
    ]

    assert [answer.status_code for answer in answers] == [200, 400, 404, 413]
    assert {answer.headers["cache-control"] for answer in answers} == {"no-store"}


def test_the_back_channel_is_exempt_from_the_origin_check(
    world: World,
) -> None:
    """K7, K8."""
    _sign_in_twice(world)

    response = _backchannel(
        world, world.issuer.logout_token(SUBJECT), origin="https://evil.example",
    )

    assert response.status_code == 200
    assert world.session_count() == 0


@pytest.mark.parametrize("path", [BACKCHANNEL_PATH + "x", BACKCHANNEL_PATH + "/", "/auth/logout"])
def test_the_exemptions_are_exact_to_the_back_channel_path(world: World, path: str) -> None:
    response = world.client.post(
        path,
        data={"logout_token": world.issuer.logout_token(SUBJECT)},
        headers={"host": BACKCHANNEL_HOST, "origin": "https://evil.example", **FORM},
    )

    assert response.status_code == 403


def test_the_rate_limit_exemption_is_exact() -> None:
    """K7, K8."""
    from songmaker_cli.request_policies import build_rate_limit_policy
    from songmaker_cli.settings import get_settings

    exempt = build_rate_limit_policy(get_settings()).exempt

    assert exempt.matches(BACKCHANNEL_PATH)
    assert not exempt.matches(BACKCHANNEL_PATH + "x")


def test_a_logout_completed_after_the_callback_commit_ends_the_new_session(world: World) -> None:
    world.sign_in(_member(SUBJECT))
    assert world.session_count() == 1

    assert _backchannel(world, world.issuer.logout_token(SUBJECT)).status_code == 200

    assert world.session_count() == 0


def test_a_logout_that_completed_before_a_later_sign_in_does_not_end_that_session(
    world: World,
) -> None:
    world.seed(SUBJECT, "felix")
    assert _backchannel(world, world.issuer.logout_token(SUBJECT)).status_code == 200

    world.sign_in(_member(SUBJECT))

    assert world.session_count() == 1

"""#1914: the Models tab reads the agent service's offer for the co-writer's model (A1 to A7, A10).

Every case drives the real ``GET /api/settings/cowriter/offer`` of the full app against a fake
agent service and a fake Keycloak (``fake_agent_service``); the matrix numbers are the item's.
"""

from __future__ import annotations

import logging
import threading

import httpx
import pytest
from agent_runtime_client.wire import RejectionCode
from conftest import make_test_app, seed_user
from fake_agent_service import (
    A_REFRESH_TOKEN,
    SERVICE_URL,
    CowriterStack,
    answers_offer_with,
    attach_cowriter_service,
    never_answers_offer,
    offer_fails_to_connect,
    offered_model,
    offers,
    refuses_offer,
    trickles_offer_forever,
)
from fake_oidc_issuer import USER_ACCESS_TOKEN, WORKLOAD_ACCESS_TOKEN
from fastapi.testclient import TestClient

from songmaker_cli.cowriter import service_offer
from songmaker_cli.db.models import UserSession

OFFER_PATH = "/api/settings/cowriter/offer"
OPUS = "claude/opus"
OFFER_TIMEOUT_CEILING_SECONDS = 10
ROTATED_REFRESH_TOKEN = "fake-rotated-refresh-token"  # noqa: S105
ALL_SECRETS = (USER_ACCESS_TOKEN, WORKLOAD_ACCESS_TOKEN, A_REFRESH_TOKEN, ROTATED_REFRESH_TOKEN)


def _seed(session) -> None:
    seed_user(session, "anna", "admin", user_id="anna")
    seed_user(session, "ben", user_id="ben")


class Web:
    """The full app, signed in as an account, with the fake service and realm around it."""

    def __init__(self, client: TestClient, factory, stack: CowriterStack) -> None:
        self.client = client
        self.factory = factory
        self.stack = stack

    @property
    def agent(self):
        return self.stack.agent

    @property
    def issuer(self):
        return self.stack.issuer

    def offer(self):
        return self.client.get(OFFER_PATH)

    def state(self) -> str:
        response = self.offer()
        assert response.status_code == 200, response.text
        return response.json()["state"]

    def stored_refresh_token(self) -> str:
        with self.factory() as session:
            return session.get(UserSession, self.stack.session_id).refresh_token.get_secret_value()


def _web(tmp_path, monkeypatch, user_id: str, **options) -> Web:
    client, factory = make_test_app(tmp_path, seed_db=_seed)
    stack = attach_cowriter_service(client, factory, monkeypatch, user_id, **options)
    return Web(client, factory, stack)


@pytest.fixture
def web(tmp_path, monkeypatch) -> Web:
    return _web(tmp_path, monkeypatch, "anna")


# ── A1, A3, A4: what an answered offer says (M1, M2, M3, M8, M9) ─────


@pytest.mark.parametrize(
    ("offered", "expected"),
    [
        pytest.param([offered_model(OPUS)], "ready", id="M1-ready"),
        pytest.param([offered_model(OPUS, ready=False)], "not_built", id="M2-not-built"),
        pytest.param(
            [offered_model("claude/sonnet"), offered_model("grok/fast")],
            "no_longer_offered",
            id="M3-other-models-only",
        ),
        pytest.param([], "not_available", id="M8-empty-offer"),
    ],
)
def test_the_offer_names_the_state_of_the_current_models_entry(web, offered, expected):
    web.agent.reply_to_offer_with(offers(*offered))

    response = web.offer()

    assert response.status_code == 200
    assert response.json() == {"state": expected, "model": "opus"}


def test_m9_a_forbidden_answer_reads_as_not_available_for_you(web):
    web.agent.reply_to_offer_with(refuses_offer(403, RejectionCode.FORBIDDEN))

    assert web.state() == "not_available"


def test_a1_a2_the_offer_is_asked_once_with_the_users_token_and_the_workload_token(web):
    web.state()

    [request] = web.agent.offer_requests
    assert request.url == f"{SERVICE_URL}/offer"
    assert request.headers["authorization"] == f"Bearer {USER_ACCESS_TOKEN}"
    assert request.headers["agent-workload-token"] == WORKLOAD_ACCESS_TOKEN


# ── A2: the offer cannot be read (M4 to M7, M19, M20, M22) ───────────


UNREADABLE_OFFERS = [
    pytest.param(
        offer_fails_to_connect(httpx.ConnectError("refused")),
        id="M5-connect-error",
    ),
    pytest.param(never_answers_offer(OFFER_TIMEOUT_CEILING_SECONDS), id="M19-never-answers"),
    pytest.param(refuses_offer(503, RejectionCode.UNAVAILABLE), id="M6-unavailable"),
    pytest.param(refuses_offer(401, RejectionCode.UNAUTHORIZED), id="M6-unauthorized"),
    pytest.param(
        answers_offer_with(502, b"<html>Bad gateway</html>", content_type="text/html"),
        id="M6b-html-502",
    ),
    pytest.param(
        answers_offer_with(200, b'{"object":"list"}', content_type="application/json"),
        id="M7-body-parse-offer-refuses",
    ),
    pytest.param(
        answers_offer_with(
            200,
            b'{"v":2,"code":"forbidden","message":"No."}',
            content_type="application/json",
        ),
        id="M7-a-refusal-body-under-200",
    ),
]


@pytest.mark.parametrize("behavior", UNREADABLE_OFFERS)
def test_an_offer_that_cannot_be_read_reads_as_not_reachable(web, behavior):
    web.agent.reply_to_offer_with(behavior)

    assert web.state() == "not_reachable"


def test_a2_an_offer_that_trickles_past_its_deadline_reads_as_not_reachable(web, monkeypatch):
    monkeypatch.setattr(service_offer, "OFFER_TIMEOUT_SECONDS", 0.2)
    web.agent.reply_to_offer_with(trickles_offer_forever())

    assert web.state() == "not_reachable"


def test_m4_without_an_agent_service_url_nothing_is_fetched_and_no_token_rotates(
    tmp_path,
    monkeypatch,
):
    web = _web(tmp_path, monkeypatch, "anna")
    monkeypatch.delenv("AGENT_SERVICE_URL")
    from songmaker_cli.settings import get_settings

    get_settings.cache_clear()
    web.issuer.rotates_refresh_token_to = ROTATED_REFRESH_TOKEN

    assert web.state() == "not_reachable"
    assert web.issuer.grants_seen == []
    assert web.agent.offer_requests == []
    assert web.stored_refresh_token() == A_REFRESH_TOKEN


def test_m20_a_refused_workload_grant_reads_as_not_reachable_and_asks_nothing(web):
    web.issuer.refuses_workload_grant = True

    assert web.state() == "not_reachable"
    assert web.agent.offer_requests == []


def test_m11_an_unavailable_issuer_reads_as_not_reachable(web):
    web.issuer.unreachable = True

    assert web.state() == "not_reachable"
    assert web.agent.offer_requests == []


# ── A5: the admin's own renewal is refused (M10) ─────────────────────


def test_m10_a_refused_renewal_asks_the_admin_to_sign_in_again(web):
    web.issuer.refuses_refresh_with = "invalid_grant"

    assert web.state() == "sign_in_again"
    assert web.agent.offer_requests == []


def test_a5_m10_a_session_without_a_refresh_token_asks_the_admin_to_sign_in_again(
    tmp_path, monkeypatch
):
    web = _web(tmp_path, monkeypatch, "anna", refresh_token=None)

    assert web.state() == "sign_in_again"
    assert web.issuer.grants_seen == []
    assert web.agent.offer_requests == []


# ── A6: who may read it (M13) ────────────────────────────────────────


def test_m13_a_member_is_refused_and_the_service_gets_no_request(tmp_path, monkeypatch):
    web = _web(tmp_path, monkeypatch, "ben")

    response = web.offer()

    assert response.status_code == 403
    assert web.agent.offer_requests == []
    assert web.issuer.grants_seen == []


def test_a6_the_cowriter_settings_do_not_read_the_offer(web):
    response = web.client.get("/api/settings/cowriter")

    assert response.status_code == 200
    assert web.agent.offer_requests == []
    assert web.issuer.grants_seen == []


# ── A7: no token anywhere (M14) ──────────────────────────────────────


FAILURES = [
    pytest.param(
        lambda web: web.agent.reply_to_offer_with(offer_fails_to_connect(httpx.ConnectError("x"))),
        id="M5",
    ),
    pytest.param(
        lambda web: web.agent.reply_to_offer_with(refuses_offer(503, RejectionCode.UNAVAILABLE)),
        id="M6-503",
    ),
    pytest.param(
        lambda web: web.agent.reply_to_offer_with(refuses_offer(401, RejectionCode.UNAUTHORIZED)),
        id="M6-401",
    ),
    pytest.param(
        lambda web: web.agent.reply_to_offer_with(
            answers_offer_with(502, b"<html></html>", content_type="text/html"),
        ),
        id="M6b",
    ),
    pytest.param(
        lambda web: web.agent.reply_to_offer_with(
            answers_offer_with(200, b"not json", content_type="application/json"),
        ),
        id="M7",
    ),
    pytest.param(
        lambda web: setattr(web.issuer, "refuses_refresh_with", "invalid_grant"), id="M10"
    ),
    pytest.param(lambda web: setattr(web.issuer, "unreachable", True), id="M11"),
]


@pytest.mark.parametrize("fail", FAILURES)
def test_m14_a_failed_read_leaves_no_token_in_a_log_line_or_the_response(web, caplog, fail):
    web.issuer.rotates_refresh_token_to = ROTATED_REFRESH_TOKEN
    fail(web)
    caplog.set_level(logging.DEBUG)

    response = web.offer()

    assert response.status_code == 200
    for secret in ALL_SECRETS:
        assert secret not in response.text
        assert secret not in caplog.text


def test_a7_a_successful_read_leaves_no_token_in_a_log_line_or_the_response(web, caplog):
    web.issuer.rotates_refresh_token_to = ROTATED_REFRESH_TOKEN
    caplog.set_level(logging.DEBUG)

    response = web.offer()

    assert response.json()["state"] == "ready"
    for secret in ALL_SECRETS:
        assert secret not in response.text
        assert secret not in caplog.text
    assert web.stored_refresh_token() == ROTATED_REFRESH_TOKEN


def test_a7_a_failed_read_logs_only_its_closed_state_name(web, caplog):
    web.agent.reply_to_offer_with(refuses_offer(503, RejectionCode.UNAVAILABLE))
    caplog.set_level(logging.INFO, logger="songmaker_cli.cowriter.service_offer")

    web.state()

    assert [record.getMessage() for record in caplog.records] == [
        "The agent service's offer is not readable: not_reachable",
    ]


# ── A10, M21: a page view and a turn renew the same session ──────────


def test_m21_two_readers_of_the_same_refresh_token_both_succeed_and_the_last_rotation_stands(web):
    issued: list[str] = []
    both_read_the_first_token = threading.Barrier(2, timeout=10)

    def after_both_asked():
        both_read_the_first_token.wait()
        web.issuer.rotates_refresh_token_to = f"rotated-{len(issued)}"
        issued.append(web.issuer.rotates_refresh_token_to)

    web.issuer.before_renewal = after_both_asked
    states: list[str] = []
    second_reader = TestClient(web.client.app)
    second_reader.cookies.update(web.client.cookies)

    def read_with(client: TestClient) -> None:
        states.append(client.get(OFFER_PATH).json()["state"])

    threads = [
        threading.Thread(target=read_with, args=(client,)) for client in (web.client, second_reader)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert states == ["ready", "ready"]
    assert web.stored_refresh_token() in issued

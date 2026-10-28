"""#1949 A3: songmaker reads no offer, so the old route answers 404 and the agent service is not asked."""

from __future__ import annotations

from conftest import make_test_app, seed_user
from fake_agent_service import attach_cowriter_service


def test_the_offer_path_answers_404_and_sends_nothing_to_the_agent_service(tmp_path, monkeypatch):
    client, factory = make_test_app(
        tmp_path, seed_db=lambda session: seed_user(session, "anna", "admin", user_id="anna"),
    )
    stack = attach_cowriter_service(client, factory, monkeypatch, "anna")

    response = client.get("/api/settings/cowriter/offer")

    assert response.status_code == 404
    assert stack.agent.runs == []

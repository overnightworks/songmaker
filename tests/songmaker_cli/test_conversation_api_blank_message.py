"""A turn needs text: a blank message is refused before anything is stored."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from support.admin_client import build_admin_client
from support.cowriter_gateway import attach_cowriter_gateway

from songmaker_cli.db.models import ChatMessage, Job, User


@pytest.fixture
def client(tmp_path: Path):
    return build_admin_client(
        tmp_path,
        lambda session: session.add(User(id="u-test", username="u-test", role="admin")),
        user_id="u-test",
        username="u-test",
    )


@pytest.mark.parametrize(
    "blank_message", ["", "   ", "\n\t"], ids=["empty", "spaces", "newline-tab"],
)
def test_a_blank_message_is_refused_before_anything_is_stored(client, blank_message):
    c, factory = client

    response = c.post("/api/chat/turn", json={"message": blank_message})

    assert response.status_code == 422
    with factory() as session:
        assert session.query(Job).count() == 0
        assert session.query(ChatMessage).count() == 0


def test_a_message_with_text_inside_whitespace_is_stored_as_sent(client, tmp_path):
    c, factory = client
    attach_cowriter_gateway(c, factory, tmp_path, "u-test")
    message = "  keep the\n  indent \t "

    response = c.post("/api/chat/turn", json={"message": message})

    events = [
        json.loads(line[len("data: "):])
        for line in response.iter_lines()
        if line.startswith("data: ")
    ]
    final = next(event for event in events if event.get("type") == "final")
    assert final["user_message"]["content"] == message
    with factory() as session:
        assert session.query(ChatMessage).filter_by(role="user").one().content == message

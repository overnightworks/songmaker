"""A person's own agent reads their conversations and notes and starts a new conversation.

Each case drives the real app in-process through ``/mcp`` with both people's content from
``McpWorld.seed_household``.
"""

from __future__ import annotations

import pytest
from support.mcp_tool_table import ALICE, BOB
from support.mcp_world import McpWorld
from support.token_world import TokenWorld
from support.web_app import seed_session

from songmaker_cli.constants import OIDC_ADMIN_GROUP, OIDC_LOGIN_GROUP, OIDC_MCP_GROUP
from songmaker_cli.db.models import Conversation

_FORGED = {"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.test"}
_ADMIN_GROUPS = (OIDC_LOGIN_GROUP, OIDC_ADMIN_GROUP, OIDC_MCP_GROUP)


def _conversations(world: McpWorld) -> set[tuple[str, str, bool]]:
    return {
        (user_id, conversation_id, archived_at is not None)
        for conversation_id, user_id, archived_at in world.rows_of(
            Conversation, "id", "user_id", "archived_at",
        )
    }


def test_list_conversations_returns_only_the_callers_conversations(household: McpWorld) -> None:
    reply = household.call("list_conversations")

    assert reply.is_error is False
    assert [row["id"] for row in reply.json()["conversations"]] == [f"conversation-{ALICE}"]


def test_get_conversation_returns_the_callers_conversation_with_its_messages(
    household: McpWorld,
) -> None:
    reply = household.call("get_conversation", {"conversation_id": f"conversation-{ALICE}"})

    assert reply.is_error is False
    assert [message["content"] for message in reply.json()["messages"]] == [
        f"Hello from {ALICE}"]


def test_get_conversation_of_another_person_is_not_found_and_reveals_nothing(
    household: McpWorld,
) -> None:
    reply = household.call("get_conversation", {"conversation_id": f"conversation-{BOB}"})

    assert reply.is_error
    assert BOB not in reply.text


def test_start_conversation_archives_the_callers_active_one_and_starts_a_new_one(
    household: McpWorld,
) -> None:
    before = _conversations(household)

    reply = household.call("start_conversation")

    assert reply.is_error is False
    started = reply.json()["id"]
    assert _conversations(household) == {
        (TokenWorld.ALICE, f"conversation-{ALICE}", True),
        (TokenWorld.ALICE, started, False),
        (TokenWorld.BOB, f"conversation-{BOB}", False),
    }
    assert before - _conversations(household) == {
        (TokenWorld.ALICE, f"conversation-{ALICE}", False)}


def test_start_conversation_by_cookie_session_without_the_csrf_header_changes_nothing(
    household: McpWorld,
) -> None:
    seed_session(household.world.client, "alice")
    before = household.snapshot()

    reply = household.world.client.post("/api/conversations/new", headers=_FORGED)

    assert reply.status_code == 403
    assert household.snapshot() == before


def test_get_memory_returns_the_callers_notes(household: McpWorld) -> None:
    reply = household.call("get_memory")

    assert reply.is_error is False
    assert reply.json()["user"]["body"] == f"Notes of {ALICE}"
    assert BOB not in reply.text


def test_get_memory_with_the_callers_song_returns_that_songs_notes(household: McpWorld) -> None:
    reply = household.call("get_memory", {"song_id": f"song-{ALICE}"})

    assert reply.is_error is False
    assert reply.json()["song"]["body"] == f"Song notes of {ALICE}"


@pytest.mark.parametrize("groups", [(OIDC_LOGIN_GROUP, OIDC_MCP_GROUP), _ADMIN_GROUPS],
                         ids=["member", "admin"])
def test_get_memory_with_another_persons_song_is_not_found_and_reveals_nothing(
    admins_household: McpWorld, groups: tuple[str, ...],
) -> None:
    reply = admins_household.call("get_memory", {"song_id": f"song-{BOB}"}, groups=groups)

    assert reply.is_error
    assert BOB not in reply.text

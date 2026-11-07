"""An agent that signs in with its own client reaches ``/mcp`` as an account of its own.

The world is `support.mcp_world`: a fake realm, the real app, and header-exact requests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker
from support.mcp_world import AGENT_GROUP, McpWorld, build_mcp_world
from support.token_world import TokenWorld
from webauth.ports import AccountKind

from songmaker_cli.constants import OIDC_ADMIN_GROUP, OIDC_LOGIN_GROUP, OIDC_MCP_GROUP
from songmaker_cli.db.models import AuditLog, User

AGENT_SUBJECT = "7c2e9d41-aaaa-4bbb-8ccc-00000000a9e1"


def _agent_claims(**overrides: object) -> dict[str, object]:
    return {
        "groups": (OIDC_LOGIN_GROUP, OIDC_MCP_GROUP, AGENT_GROUP),
        "username": "service-account-hal",
        "agent_owner": TokenWorld.ALICE,
        "agent_name": "Hal",
        **overrides,
    }


def _account_kinds(mcp: McpWorld) -> dict[str, AccountKind]:
    return dict(mcp.rows_of(User, "id", "kind"))


def test_m29_an_agent_token_creates_an_agent_account_and_a_tool_runs_as_it(
    mcp: McpWorld,
) -> None:
    reply = mcp.call(
        "create_album", {"title": "Agent Album"}, subject=AGENT_SUBJECT, **_agent_claims(),
    )

    created = reply.json()
    assert (reply.is_error, _account_kinds(mcp)[AGENT_SUBJECT]) == (False, AccountKind.AGENT)
    assert mcp.world.albums() == [("Agent Album", AGENT_SUBJECT)]
    assert (AGENT_SUBJECT, "create", "album", created["id"]) in mcp.world.audits()
    assert (None, "create", "user", AGENT_SUBJECT) in mcp.world.audits()


def test_m29_an_agent_is_admitted_as_user_whatever_role_a_stored_account_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory: sessionmaker,
) -> None:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    world = build_mcp_world(tmp_path, monkeypatch, pg_factory, alice_role="admin")

    world.world.seed_take(TokenWorld.ALICE, "alices")
    world.world.seed_take(TokenWorld.BOB, "bobs")
    groups = (OIDC_LOGIN_GROUP, OIDC_ADMIN_GROUP, OIDC_MCP_GROUP, AGENT_GROUP)

    songs = world.call("list_songs", **_agent_claims(username="alice", groups=groups))
    others = world.call("get_song", {"song_id": "song-bobs"},
                        **_agent_claims(username="alice", groups=groups))

    assert [item["title"] for item in songs.json()["items"]] == ["Song alices"]
    assert others.is_error
    assert _account_kinds(world)[TokenWorld.ALICE] == AccountKind.AGENT


def test_m29_a_stored_person_account_met_by_an_agent_token_becomes_an_agent_and_is_audited(
    mcp: McpWorld,
) -> None:
    mcp.call("list_albums", {}, subject=TokenWorld.ALICE, **_agent_claims(username="alice"))

    details = [
        detail
        for (detail,) in mcp.rows_of(AuditLog, "detail")
        if detail and detail.startswith("kind=")
    ]
    assert _account_kinds(mcp)[TokenWorld.ALICE] == AccountKind.AGENT
    assert details == ["kind=person->agent"]


@pytest.mark.parametrize(
    "claims",
    [
        {"agent_owner": None},
        {"agent_owner": ""},
        {"agent_name": None},
        {"agent_name": ""},
        {"agent_name": "x" * 65},
        {"agent_name": "bad\nname"},
    ],
    ids=["no-owner", "empty-owner", "no-name", "empty-name", "name-too-long", "unprintable-name"],
)
def test_m29_an_agent_token_with_bad_agent_claims_is_refused_and_creates_no_account(
    mcp: McpWorld, claims: dict[str, object],
) -> None:
    reply = mcp.rpc(
        "tools/list", headers=mcp.agent(AGENT_SUBJECT, **_agent_claims(**claims)),
    )

    assert reply.status_code == 401
    assert AGENT_SUBJECT not in _account_kinds(mcp)


def test_m29_agent_claims_outside_the_agent_group_are_ignored_as_before(mcp: McpWorld) -> None:
    mcp.call("list_albums", {}, **_agent_claims(groups=(OIDC_LOGIN_GROUP, OIDC_MCP_GROUP)))

    assert _account_kinds(mcp)[TokenWorld.ALICE] == AccountKind.PERSON

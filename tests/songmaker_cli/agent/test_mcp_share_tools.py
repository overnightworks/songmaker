"""Who may make a public share: an agent with its own account, never a person's own agent.

The real app on PostgreSQL through ``/mcp`` and by direct bearer, against the fake realm of
`support.mcp_world`.
"""

from __future__ import annotations

import pytest
from support.mcp_tool_table import ALICE, ALL_TOOLS, BOB, Tool
from support.mcp_world import AGENT_SUBJECT, McpWorld, agent_claims
from support.token_world import TokenWorld

from songmaker_cli.agent.mcp import collect_route_tools
from songmaker_cli.auth_dependencies import PERSONS_AGENT_SHARE_REFUSED_DETAIL
from songmaker_cli.db.models import Generation

AGENTS = "agents"
OTHER_AGENT_SUBJECT = "7c2e9d41-aaaa-4bbb-8ccc-00000000a9e2"
MISSING_SONG_OWNER = "nobody"
SHARE_SONG = "/api/songs/{song_id}/share"


def _is_share_route(method: str, template: str) -> bool:
    return method == "POST" and template.endswith("/share")


SHARE_TOOLS = [tool for tool in ALL_TOOLS if _is_share_route(tool.method, tool.template)]


@pytest.fixture
def agents_world(household: McpWorld) -> McpWorld:
    """The household, and two admitted agent accounts, one of which owns a song."""
    household.world.seed_take(AGENT_SUBJECT, AGENTS)
    household.world.seed_take(OTHER_AGENT_SUBJECT, "others")
    for subject in (AGENT_SUBJECT, OTHER_AGENT_SUBJECT):
        household.call("get_account", subject=subject, **agent_claims())
    return household


@pytest.fixture(params=["member", "admin"])
def persons_world(request: pytest.FixtureRequest) -> McpWorld:
    """The household where Alice, whose own agent acts, is a member or an admin."""
    return request.getfixturevalue("household" if request.param == "member"
                                   else "admins_household")


def _share_direct(world: McpWorld, song_id: str, **options: object):
    return world.world.client.post(
        SHARE_SONG.format(song_id=song_id), headers=world.agent(**options),
    )


def _public_song(world: McpWorld, slug: str):
    return world.world.client.get(f"/shared/song/{slug}")


# -- an agent with its own account shares its own song ----------------------------------------


@pytest.mark.parametrize("through_mcp", [True, False], ids=["through-mcp", "direct-bearer"])
def test_an_agent_account_shares_its_own_song_and_the_link_serves_the_public_page(
    agents_world: McpWorld, through_mcp: bool,
) -> None:
    """Spec: REQ-SHARE-26 -- an agent account's share, on either path, is served to a visitor."""
    options = {"subject": AGENT_SUBJECT, **agent_claims()}
    song_id = f"song-{AGENTS}"

    if through_mcp:
        reply = agents_world.call("share_song", {"song_id": song_id}, **options)
        succeeded = reply.is_error is False
    else:
        reply = _share_direct(agents_world, song_id, **options)
        succeeded = reply.status_code == 200
    shared = reply.json()

    assert succeeded
    assert shared["share_url"].endswith(shared["share_slug"])
    assert _public_song(agents_world, shared["share_slug"]).status_code == 200
    assert (AGENT_SUBJECT, "share", "song", song_id) in agents_world.world.audits()


def test_an_agent_account_ends_its_share_with_unshare_song_and_the_link_stops(
    agents_world: McpWorld,
) -> None:
    """Spec: REQ-SHARE-26 -- the agent account that shared a song ends the share itself."""
    options = {"subject": AGENT_SUBJECT, **agent_claims()}
    slug = agents_world.call("share_song", {"song_id": f"song-{AGENTS}"}, **options).json()[
        "share_slug"]

    ended = agents_world.call("unshare_song", {"song_id": f"song-{AGENTS}"}, **options)

    never = _public_song(agents_world, "never-shared")
    after = _public_song(agents_world, slug)
    assert ended.is_error is False
    assert (after.status_code, after.json()) == (never.status_code, never.json())


@pytest.mark.parametrize(("owner", "song_id"), [
    pytest.param(ALICE, f"song-{ALICE}", id="a-person"),
    pytest.param("others", "song-others", id="another-agent-account"),
])
def test_an_agent_account_gets_no_share_of_a_song_that_is_not_its_own_and_nothing_is_written(
    agents_world: McpWorld, owner: str, song_id: str,
) -> None:
    """Spec: REQ-SHARE-26 -- an agent account shares its own songs only."""
    before = agents_world.snapshot()
    options = {"subject": AGENT_SUBJECT, **agent_claims()}

    through_mcp = agents_world.call("share_song", {"song_id": song_id}, **options)
    direct = _share_direct(agents_world, song_id, **options)

    assert through_mcp.is_error
    assert direct.status_code == 404
    assert agents_world.snapshot() == before


# -- a person's own agent is refused ---------------------------------------------------------


@pytest.mark.parametrize("tool", SHARE_TOOLS, ids=lambda tool: tool.name)
@pytest.mark.parametrize("subject", [ALICE, BOB, MISSING_SONG_OWNER],
                         ids=["own-song", "foreign-song", "missing-song"])
def test_a_persons_own_agent_is_refused_a_share_on_both_paths_and_nothing_is_written(
    persons_world: McpWorld, tool: Tool, subject: str,
) -> None:
    """Spec: REQ-SHARE-27 -- a person's own agent, an admin's included, cannot share."""
    seeded = (f"take-{subject}", True, False) in persons_world.rows_of(
        Generation, "id", "is_picked", "is_kept")
    assert seeded is (subject != MISSING_SONG_OWNER)
    before = persons_world.snapshot()

    through_mcp = persons_world.call(tool.name, tool.arguments_for(subject))
    path, _ = tool.request(subject)
    direct = persons_world.world.client.post(path, headers=persons_world.agent())

    assert (through_mcp.is_error, PERSONS_AGENT_SHARE_REFUSED_DETAIL in through_mcp.text) == (
        True, True)
    assert (direct.status_code, direct.json()["detail"]) == (
        403, PERSONS_AGENT_SHARE_REFUSED_DETAIL)
    assert persons_world.snapshot() == before


def test_a_token_of_a_stored_agent_account_outside_the_agent_group_is_refused(
    household: McpWorld,
) -> None:
    """Spec: REQ-SHARE-27 -- an account stored as an agent is refused outside the agent group."""
    household.call("get_account", subject=TokenWorld.ALICE, **agent_claims(username="alice"))
    before = household.snapshot()

    through_mcp = household.call("share_song", {"song_id": f"song-{ALICE}"})
    direct = _share_direct(household, f"song-{ALICE}")

    assert (through_mcp.is_error, PERSONS_AGENT_SHARE_REFUSED_DETAIL in through_mcp.text) == (
        True, True)
    assert direct.status_code == 403
    assert household.snapshot() == before


# -- the browser session and the hal token share as before -----------------------------------


def test_a_hal_token_shares_its_persons_own_song_and_gets_404_on_a_foreign_one(
    household: McpWorld,
) -> None:
    """Spec: REQ-SHARE-01 -- a person's hal token shares as the person does."""
    hal = household.world.bearer(TokenWorld.ALICE)
    before = household.snapshot()

    foreign = household.world.client.post(f"/api/songs/song-{BOB}/share", headers=hal)
    own = household.world.client.post(f"/api/songs/song-{ALICE}/share", headers=hal)

    assert foreign.status_code == 404
    assert own.status_code == 200
    assert _public_song(household, own.json()["share_slug"]).status_code == 200
    assert household.snapshot() != before


# -- every marked share route has a row of the table ------------------------------------------


def test_the_marked_share_routes_of_the_app_are_the_share_rows_of_the_tool_table(
    household: McpWorld,
) -> None:
    marked = {(mark.method, mark.template)
              for mark in collect_route_tools(household.world.client.app).marks
              if _is_share_route(mark.method, mark.template)}

    assert marked == {(tool.method, tool.template) for tool in SHARE_TOOLS}

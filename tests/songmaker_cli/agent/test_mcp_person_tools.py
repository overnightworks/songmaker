"""The tools of a person's own agent that mirror the person's GET and POST actions.

Each case drives the real app in-process through ``/mcp``: the tool calls the route through
the whole middleware stack, so the ownership checks, the limits and the sessions are the
browser's. Both people's content comes from ``McpWorld.seed_household``.
"""

from __future__ import annotations

import re
from contextlib import ExitStack
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker
from support.mcp_tool_table import (
    ALICE,
    ALL_TOOLS,
    BOB,
    CREATIONS,
    PLAIN_READS,
    READS_OF_ONE_RESOURCE,
    WRITES_ON_ONE_RESOURCE,
    Tool,
    repaint_arguments,
)
from support.mcp_world import SAME_ORIGIN, McpWorld, build_mcp_world, worker_ready
from support.token_world import TokenWorld
from support.web_app import seed_session

from songmaker_cli.constants import (
    OIDC_ADMIN_GROUP,
    OIDC_LOGIN_GROUP,
    OIDC_MCP_GROUP,
    SongWorkKind,
)
from songmaker_cli.db.models import (
    Album,
    CowriterAlbumMemory,
    CowriterSongMemory,
    CowriterUserMemory,
    Generation,
    GenerationPreset,
    Job,
    Playlist,
    PlaylistEntry,
    Rating,
    ReferenceRecording,
    Song,
    UserLora,
    UserLoraSample,
    Version,
)
from songmaker_cli.db.queries.activity import record_song_edit, record_song_played
from songmaker_cli.db.queries.songs import record_playlist_listen
from songmaker_cli.job_types import JobType

_FORGED = {"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.test"}
_NOT_FOUND = {403, 404}
BOBS_LYRICS = "a verse only the member wrote"

_IDS = [tool.name for tool in ALL_TOOLS]


def _browser(world: McpWorld, tool: Tool, subject: str, headers: dict[str, str]):
    path, left = tool.request(subject)
    if tool.method == "GET":
        return world.world.client.get(path, params=left, headers=headers)
    return world.world.client.request(tool.method, path, json=left, headers=headers)


# -- reads of a stranger's content -------------------------------------------------------


@pytest.mark.parametrize("tool", READS_OF_ONE_RESOURCE, ids=lambda t: t.name)
def test_a_read_tool_answers_for_the_persons_own_content_as_the_browser_does(
    household: McpWorld, tool: Tool,
) -> None:
    reply = household.call(tool.name, tool.arguments_for(ALICE))

    browser = _browser(household, tool, ALICE, household.agent())
    assert (reply.is_error, reply.json()) == (False, browser.json())


@pytest.mark.parametrize("tool", READS_OF_ONE_RESOURCE, ids=lambda t: t.name)
def test_a_read_tool_for_another_persons_content_is_refused_as_for_a_stranger_in_the_browser(
    household: McpWorld, tool: Tool,
) -> None:
    reply = household.call(tool.name, tool.arguments_for(BOB))

    browser = _browser(household, tool, BOB, household.agent())
    assert browser.status_code in _NOT_FOUND
    assert reply.is_error
    assert BOB not in re.sub(r"(take|job|song|album|playlist|reference|lora)-bobs",
                             "", reply.text)


@pytest.mark.parametrize("tool", [
    t for t in PLAIN_READS if t.name in {
        "list_loras", "list_own_playable_takes", "list_playlists", "list_references",
        "list_presets",
        "get_library_listen", "get_library_write", "search_library",
        "get_library_pool_queue",
    }
], ids=lambda t: t.name)
def test_a_list_tool_holds_only_the_callers_content(household: McpWorld, tool: Tool) -> None:
    reply = household.call(tool.name, tool.arguments_for(ALICE))

    assert reply.is_error is False
    assert BOB not in reply.text


@pytest.mark.parametrize("tool", PLAIN_READS, ids=lambda t: t.name)
def test_a_plain_read_tool_answers_as_the_browser_does(household: McpWorld, tool: Tool) -> None:
    reply = household.call(tool.name, tool.arguments_for(ALICE))

    browser = _browser(household, tool, ALICE, household.agent())
    assert (reply.is_error, reply.json()) == (False, browser.json())


# -- writes -------------------------------------------------------------------------------


@pytest.mark.parametrize("tool", [*WRITES_ON_ONE_RESOURCE, *CREATIONS], ids=lambda t: t.name)
def test_a_write_tool_on_the_persons_own_resource_succeeds(
    household: McpWorld, tool: Tool,
) -> None:
    with worker_ready():
        reply = household.call(tool.name, tool.arguments_for(ALICE))

    assert reply.is_error is False, reply.text


_REFUSED_CASES = [
    pytest.param(tool, subject, other, id=f"{tool.name}-{subject}-{other}")
    for tool in WRITES_ON_ONE_RESOURCE
    for subject, other in tool.refused_pairs
]


@pytest.mark.parametrize(("tool", "subject", "other"), _REFUSED_CASES)
def test_a_write_tool_that_touches_another_persons_resource_is_refused_and_writes_nothing(
    household: McpWorld, tool: Tool, subject: str, other: str,
) -> None:
    before = household.snapshot()

    with worker_ready() as pool:
        reply = household.call(tool.name, tool.arguments_for(subject, other))

    assert reply.is_error
    assert household.snapshot() == before
    pool.enqueue_job.assert_not_called()


# (tool, arguments, model, columns, row that exists afterwards)
_EFFECTS = [
    ("keep_take", {"gen_id": "take-alices"}, Generation, ("id", "is_kept"),
     ("take-alices", True)),
    ("rate_take", {"gen_id": "take-alices", "rating": 80}, Rating, ("generation_id", "rating"),
     ("take-alices", 80.0)),
    ("archive_album", {"album_id": "album-alices"}, Album, ("id", "is_archived"),
     ("album-alices", True)),
    ("restore_album", {"album_id": "album-gone-alices"}, Album, ("id", "deleted_at"),
     ("album-gone-alices", None)),
    ("restore_song", {"song_id": "song-gone-alices"}, Song, ("id", "deleted_at"),
     ("song-gone-alices", None)),
    ("cancel_job", {"job_id": "job-alices"}, Job, ("id", "status"), ("job-alices", "cancelled")),
    ("keep_reference", {"reference_id": "reference-alices"}, ReferenceRecording,
     ("id", "is_kept"), ("reference-alices", True)),
    ("set_default_preset", {"preset_id": "preset-alices"}, GenerationPreset,
     ("id", "is_default"), ("preset-alices", True)),
    ("add_take_to_playlist", {"playlist_id": "playlist-alices", "generation_id": "take-alices"},
     PlaylistEntry, ("playlist_id", "generation_id"), ("playlist-alices", "take-alices")),
    ("create_playlist", {"title": "Fresh list"}, Playlist, ("title", "created_by"),
     ("Fresh list", TokenWorld.ALICE)),
    ("create_preset", {"name": "Fresh", "model_mode": "sft", "params": {}}, GenerationPreset,
     ("name", "created_by"), ("Fresh", TokenWorld.ALICE)),
    ("create_lora", {"name": "Fresh"}, UserLora, ("name", "user_id"),
     ("Fresh", TokenWorld.ALICE)),
    ("update_album", {"album_id": "album-alices", "title": "Renamed"}, Album, ("id", "title"),
     ("album-alices", "Renamed")),
    ("update_playlist", {"playlist_id": "playlist-alices", "title": "Renamed"}, Playlist,
     ("id", "title"), ("playlist-alices", "Renamed")),
    ("move_playlist_entry", {"playlist_id": "playlist-filled-alices", "entry_id": "entry-alices",
                             "new_position": 1}, PlaylistEntry, ("id", "position"),
     ("entry-alices", 1)),
    ("update_preset", {"preset_id": "preset-alices", "name": "Renamed"}, GenerationPreset,
     ("id", "name"), ("preset-alices", "Renamed")),
    ("rename_song", {"song_id": "song-alices", "title": "Renamed"}, Song, ("id", "title"),
     ("song-alices", "Renamed")),
    ("update_lora_sample", {"lora_id": "lora-alices", "sample_id": "sample-alices-0",
                            "caption": "new caption"}, UserLoraSample, ("id", "caption"),
     ("sample-alices-0", "new caption")),
    ("write_song_memory", {"song_id": "song-alices", "body": "a note"}, CowriterSongMemory,
     ("song_id", "body"), ("song-alices", "a note")),
    ("write_album_memory", {"album_id": "album-alices", "body": "a note"}, CowriterAlbumMemory,
     ("album_id", "body"), ("album-alices", "a note")),
    ("unpick_take", {"gen_id": "take-alices"}, Generation, ("id", "is_picked"),
     ("take-alices", False)),
    ("update_song", {"song_id": "song-alices", "lyrics": "A new verse"}, Version,
     ("song_id", "lyrics"), ("song-alices", "A new verse")),
    ("write_user_memory", {"body": "a note"}, CowriterUserMemory, ("user_id", "body"),
     (TokenWorld.ALICE, "a note")),
]


@pytest.mark.parametrize(
    ("tool", "arguments", "model", "columns", "row"), _EFFECTS, ids=[e[0] for e in _EFFECTS],
)
def test_a_write_tool_changes_the_persons_own_resource_and_not_the_strangers(
    household: McpWorld, tool: str, arguments: dict, model: type, columns: tuple[str, ...],
    row: tuple,
) -> None:
    bobs_before = [r for r in household.rows_of(model, *columns) if BOB in repr(r)]

    reply = household.call(tool, arguments)

    assert reply.is_error is False
    assert row in household.rows_of(model, *columns)
    assert [r for r in household.rows_of(model, *columns) if BOB in repr(r)] == bobs_before


def test_removing_a_playlist_entry_takes_out_the_callers_entry_and_no_other(
    household: McpWorld,
) -> None:
    reply = household.call("remove_playlist_entry", {
        "playlist_id": "playlist-filled-alices", "entry_id": "entry-alices-extra"})

    assert reply.is_error is False
    assert {row[0] for row in household.rows_of(PlaylistEntry, "id")} == {
        "entry-alices", "entry-bobs", "entry-bobs-extra"}


def test_moving_a_song_puts_the_callers_song_into_the_callers_other_album(
    household: McpWorld,
) -> None:
    other = household.call("create_album", {"title": "Second"}).json()["id"]

    reply = household.call("move_song", {"song_id": "song-alices", "album_id": other})

    assert reply.is_error is False
    assert ("song-alices", other) in household.rows_of(Song, "id", "album_id")
    assert ("song-bobs", "album-bobs") in household.rows_of(Song, "id", "album_id")


def test_the_theme_and_the_default_configuration_are_set_for_the_caller_only(
    household: McpWorld,
) -> None:
    theme = household.call("set_theme", {"theme": "dark"})
    config = household.call("set_default_config", {"config": "preset-alices"})

    assert (theme.is_error, config.is_error) == (False, False)
    assert household.call("get_theme").json() == {"theme": "dark"}
    assert household.call("get_default_config").json()["config"] == "preset-alices"
    bob = household.agent(TokenWorld.BOB)
    assert household.world.client.get("/api/settings/theme", headers=bob).json() != {
        "theme": "dark"}
    assert household.world.client.get("/api/settings/default-config", headers=bob).json() == {
        "config": None}


def test_an_album_updated_by_title_alone_keeps_its_subtitle_and_year(household: McpWorld) -> None:
    with household.world.factory() as session:
        album = session.get(Album, "album-alices")
        album.subtitle, album.year = "Kept subtitle", "1999"
        session.commit()

    reply = household.call("update_album", {"album_id": "album-alices", "title": "Only title"})

    assert reply.is_error is False
    assert ("Only title", "Kept subtitle", "1999") in household.rows_of(
        Album, "title", "subtitle", "year")


# -- limits the browser meets --------------------------------------------------------------


@pytest.mark.parametrize("tool", [t for t in WRITES_ON_ONE_RESOURCE
                                  if t.name in {"cover_take", "repaint_take"}],
                         ids=lambda t: t.name)
def test_a_generating_tool_meets_the_persons_generation_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory: sessionmaker,
    lifespans: ExitStack, tool: Tool,
) -> None:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    world = build_mcp_world(tmp_path, monkeypatch, pg_factory, lifespans, generation_limit=1)
    world.seed_household(TokenWorld.ALICE, ALICE)

    with worker_ready():
        first = world.call(tool.name, tool.arguments_for(ALICE))
        second = world.call(tool.name, tool.arguments_for(ALICE))
        browser = _browser(world, tool, ALICE, world.agent())

    assert first.is_error is False
    assert (second.is_error, second.json()) == (True, browser.json())
    assert browser.status_code == 429
    assert world.rows_of(Job, "type").count(("generate",)) == 1


def test_the_score_tool_meets_the_persons_scoring_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory: sessionmaker,
    lifespans: ExitStack,
) -> None:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    monkeypatch.setenv("SCORING_RATE_LIMIT_USER", "1")
    world = build_mcp_world(tmp_path, monkeypatch, pg_factory, lifespans)
    world.seed_household(TokenWorld.ALICE, ALICE)
    arguments = {"gen_id": "take-alices"}

    with worker_ready():
        first = world.call("score_take", arguments)
        second = world.call("score_take", arguments)
        browser = world.world.client.post(
            "/api/generations/take-alices/score", json={}, headers=world.agent(),
        )

    assert first.is_error is False
    assert (second.is_error, second.json()) == (True, browser.json())
    assert browser.status_code == 429
    assert world.rows_of(Job, "type").count(("score",)) == 1


# -- an admin's agent is a member -----------------------------------------------------------


@pytest.fixture
def admins_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory: sessionmaker,
    lifespans: ExitStack,
) -> McpWorld:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    world = build_mcp_world(tmp_path, monkeypatch, pg_factory, lifespans, alice_role="admin")
    world.seed_household(TokenWorld.ALICE, ALICE)
    world.seed_household(TokenWorld.BOB, BOB)
    with world.world.factory() as session:
        record_song_edit(session, user_id=TokenWorld.ALICE, song_id=f"song-{BOB}",
                         kind=SongWorkKind.CREATED)
        record_song_played(session, user_id=TokenWorld.ALICE, song_id=f"song-{BOB}",
                           in_playlist=False)
        session.commit()
    return world


_ADMIN_GROUPS = (OIDC_LOGIN_GROUP, OIDC_ADMIN_GROUP, OIDC_MCP_GROUP)


@pytest.mark.parametrize("tool", [
    t for t in PLAIN_READS if t.name in {"get_library_listen", "get_library_write",
                                          "search_library", "list_own_playable_takes"}
], ids=lambda t: t.name)
def test_the_content_reads_of_an_admins_agent_return_only_the_admins_own_content(
    admins_world: McpWorld, tool: Tool,
) -> None:
    reply = admins_world.call(tool.name, tool.arguments_for(ALICE), groups=_ADMIN_GROUPS)

    assert reply.is_error is False
    assert ALICE in reply.text
    assert BOB not in reply.text


def test_an_admins_agent_reads_its_own_lora_as_the_route_answers_it(admins_world: McpWorld) -> None:
    reply = admins_world.call("get_lora", {"lora_id": f"lora-{ALICE}"}, groups=_ADMIN_GROUPS)

    browser = admins_world.world.client.get(f"/api/loras/lora-{ALICE}",
                                            headers=admins_world.agent(groups=_ADMIN_GROUPS))
    assert (reply.is_error, reply.json()) == (False, browser.json())


def _the_admin_fills_own_containers_with_the_members_content(world: McpWorld) -> None:
    """In the browser an admin may put a member's take into their playlist and a reference of
    theirs on the member's song."""
    with world.world.factory() as session:
        session.get(Version, f"version-{BOB}").lyrics = BOBS_LYRICS
        for name in (ALICE, BOB):
            session.get(Album, f"album-{name}").cover_key = f"cover-{name}"
        session.commit()
    seed_session(world.world.client, "alice")
    for take in (f"take-{ALICE}", f"take-{BOB}"):
        added = world.world.client.post(
            f"/api/playlists/playlist-{ALICE}/entries/generation",
            json={"generation_id": take}, headers=SAME_ORIGIN,
        )
        assert added.status_code == 200
    for song in (ALICE, BOB):
        saved = world.world.client.put(
            f"/api/songs/song-{song}", json={"reference_recording_id": f"reference-{ALICE}"},
            headers=SAME_ORIGIN,
        )
        assert saved.status_code == 200
    world.world.client.cookies.clear()


@pytest.mark.parametrize(("tool", "arguments", "browser_path"), [
    ("get_playlist", {"playlist_id": f"playlist-{ALICE}"}, f"/api/playlists/playlist-{ALICE}"),
    ("list_playlists", {}, "/api/playlists"),
    ("list_reference_uses", {"reference_id": f"reference-{ALICE}"},
     f"/api/references/reference-{ALICE}/uses"),
], ids=["get_playlist", "list_playlists", "list_reference_uses"])
def test_an_admins_agent_reads_none_of_a_members_content_in_the_admins_own_containers(
    admins_world: McpWorld, tool: str, arguments: dict, browser_path: str,
) -> None:
    _the_admin_fills_own_containers_with_the_members_content(admins_world)

    reply = admins_world.call(tool, arguments, groups=_ADMIN_GROUPS)
    seed_session(admins_world.world.client, "alice")
    browser = admins_world.world.client.get(browser_path)

    assert reply.is_error is False
    assert ALICE in reply.text
    for members_content in (BOB, TokenWorld.BOB, BOBS_LYRICS):
        assert members_content not in reply.text
    assert browser.status_code == 200
    assert BOB in browser.text


def test_an_admins_agent_reads_none_of_a_members_covers_in_a_played_playlist_of_the_admin(
    admins_world: McpWorld,
) -> None:
    _the_admin_fills_own_containers_with_the_members_content(admins_world)
    with admins_world.world.factory() as session:
        record_playlist_listen(
            session, session.get(Playlist, f"playlist-{ALICE}"),
            song=session.get(Song, f"song-{ALICE}"),
        )
        session.commit()

    reply = admins_world.call("get_library_listen", groups=_ADMIN_GROUPS)
    seed_session(admins_world.world.client, "alice")
    browser = admins_world.world.client.get("/api/library/listen")

    assert reply.is_error is False
    assert f"album-{ALICE}" in reply.text
    for members_content in (BOB, TokenWorld.BOB):
        assert members_content not in reply.text
    assert browser.status_code == 200
    mosaic = next(i for i in browser.json()["items"] if i["type"] == "playlist")["album_covers"]
    assert any(BOB in cover["card"] for cover in mosaic)


@pytest.mark.parametrize(
    "job_type", [JobType.LOAD_MODEL_ON_WORKER, JobType.DOWNLOAD_MODEL_ON_WORKER],
)
def test_an_admins_agent_is_refused_the_admins_own_model_jobs_on_a_worker(
    admins_world: McpWorld, job_type: JobType,
) -> None:
    with admins_world.world.factory() as session:
        session.add(Job(id="model-job", type=job_type, status="queued",
                        user_id=TokenWorld.ALICE))
        session.commit()

    job = admins_world.call("get_job", {"job_id": "model-job"}, groups=_ADMIN_GROUPS)
    cancel = admins_world.call("cancel_job", {"job_id": "model-job"}, groups=_ADMIN_GROUPS)
    seed_session(admins_world.world.client, "alice")
    browser = admins_world.world.client.get("/api/jobs/model-job")

    assert (job.is_error, cancel.is_error) == (True, True)
    assert ("model-job", "queued") in admins_world.rows_of(Job, "id", "status")
    assert browser.status_code == 200


def test_an_admins_agent_is_refused_another_persons_job_and_is_a_user_in_the_account(
    admins_world: McpWorld,
) -> None:
    job = admins_world.call("get_job", {"job_id": "job-bobs"}, groups=_ADMIN_GROUPS)
    cancel = admins_world.call("cancel_job", {"job_id": "job-bobs"}, groups=_ADMIN_GROUPS)
    account = admins_world.call("get_account", groups=_ADMIN_GROUPS)

    assert (job.is_error, cancel.is_error) == (True, True)
    assert ("job-bobs", "queued") in admins_world.rows_of(Job, "id", "status")
    assert (account.is_error, account.json()["role"]) == (False, "user")


_NEW_TOOLS_ON_A_RESOURCE = [
    t for t in WRITES_ON_ONE_RESOURCE if t.name in {
        "update_album", "update_playlist", "move_playlist_entry", "remove_playlist_entry",
        "update_preset", "rename_song", "move_song", "update_lora_sample", "write_song_memory",
        "write_album_memory", "unshare_album", "unshare_song", "unshare_take",
        "unshare_playlist", "delete_album", "delete_song", "update_song", "pick_take",
        "unpick_take", "unkeep_take", "unkeep_reference",
    }
]


@pytest.mark.parametrize("tool", _NEW_TOOLS_ON_A_RESOURCE, ids=lambda t: t.name)
def test_an_admins_agent_is_refused_the_new_write_tools_on_another_persons_resource(
    admins_world: McpWorld, tool: Tool,
) -> None:
    before = admins_world.snapshot()

    reply = admins_world.call(tool.name, tool.arguments_for(BOB), groups=_ADMIN_GROUPS)

    assert reply.is_error
    assert admins_world.snapshot() == before


def test_the_reference_counts_of_an_admins_agent_leave_out_uses_in_another_persons_songs(
    admins_world: McpWorld,
) -> None:
    _the_admin_fills_own_containers_with_the_members_content(admins_world)

    reply = admins_world.call("list_references", groups=_ADMIN_GROUPS)
    seed_session(admins_world.world.client, "alice")
    browser = admins_world.world.client.get("/api/references")

    own = next(r for r in reply.json()["references"] if r["id"] == f"reference-{ALICE}")
    seen = next(r for r in browser.json()["references"] if r["id"] == f"reference-{ALICE}")
    assert (own["used_by_versions"], seen["used_by_versions"]) == (1, 2)


# -- cookie sessions and CSRF ---------------------------------------------------------------


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=_IDS)
def test_a_cookie_session_with_csrf_succeeds_on_each_tool_route(
    household: McpWorld, tool: Tool,
) -> None:
    seed_session(household.world.client, "alice")

    with worker_ready():
        reply = _browser(household, tool, ALICE, SAME_ORIGIN)

    assert reply.status_code == 200


@pytest.mark.parametrize("tool", [t for t in ALL_TOOLS if t.method != "GET"],
                         ids=lambda t: t.name)
def test_a_cookie_write_without_csrf_is_refused_on_each_tool_route_and_writes_nothing(
    household: McpWorld, tool: Tool,
) -> None:
    seed_session(household.world.client, "alice")
    before = household.snapshot()

    with worker_ready() as pool:
        reply = _browser(household, tool, ALICE, _FORGED)

    assert reply.status_code == 403
    assert household.snapshot() == before
    pool.enqueue_job.assert_not_called()


# -- containers the person already shared ---------------------------------------------------


def _share(world: McpWorld, path: str) -> str:
    seed_session(world.world.client, "alice")
    reply = world.world.client.post(path, headers=SAME_ORIGIN)
    assert reply.status_code == 200
    return reply.json()["share_slug"]


@pytest.mark.parametrize(("tool", "arguments"), [
    ("add_take_to_playlist", {"playlist_id": "playlist-alices", "generation_id": "take-alices"}),
    ("add_song_to_playlist", {"playlist_id": "playlist-alices", "song_id": "song-alices"}),
    ("add_album_to_playlist", {"playlist_id": "playlist-alices", "album_id": "album-alices"}),
], ids=["take", "song", "album"])
def test_a_playlist_entry_added_by_a_tool_shows_on_the_shared_playlist_under_the_same_slug(
    household: McpWorld, tool: str, arguments: dict,
) -> None:
    slug = _share(household, "/api/playlists/playlist-alices/share")
    public = household.world.client
    assert public.get(f"/shared/playlist/{slug}").json()["entries"] == []

    reply = household.call(tool, arguments)

    entries = public.get(f"/shared/playlist/{slug}").json()["entries"]
    assert reply.is_error is False
    assert [entry["generation_id"] for entry in entries] == ["take-alices"]
    assert household.call("get_playlist", {"playlist_id": "playlist-alices"}).json()[
        "share_slug"
    ] == slug


def test_a_playlist_entry_removed_by_a_tool_leaves_the_shared_playlist_under_the_same_slug(
    household: McpWorld,
) -> None:
    slug = _share(household, "/api/playlists/playlist-filled-alices/share")
    public = household.world.client
    assert len(public.get(f"/shared/playlist/{slug}").json()["entries"]) == 2

    reply = household.call("remove_playlist_entry", {
        "playlist_id": "playlist-filled-alices", "entry_id": "entry-alices-extra"})

    assert reply.is_error is False
    assert len(public.get(f"/shared/playlist/{slug}").json()["entries"]) == 1
    assert household.call("get_playlist", {"playlist_id": "playlist-filled-alices"}).json()[
        "share_slug"
    ] == slug


def test_an_unarchived_take_shows_on_the_shared_album_under_the_same_slug(
    household: McpWorld,
) -> None:
    slug = _share(household, "/api/albums/album-alices/share")
    with household.world.factory() as session:
        session.get(Generation, "take-alices").is_archived = True
        session.commit()
    public = household.world.client
    assert public.get(f"/shared/{slug}").json()["songs"][0]["generation_id"] is None

    reply = household.call("unarchive_take", {"gen_id": "take-alices"})

    songs = public.get(f"/shared/{slug}").json()["songs"]
    assert reply.is_error is False
    assert [song["generation_id"] for song in songs] == ["take-alices"]
    assert household.call("get_album", {"album_id": "album-alices"}).json()["share_slug"] == slug


def test_a_repaint_on_a_shared_song_queues_its_job_and_keeps_the_slug_and_the_public_view(
    household: McpWorld,
) -> None:
    slug = _share(household, "/api/songs/song-alices/share")
    public = household.world.client
    shown = public.get(f"/shared/song/{slug}").json()

    with worker_ready():
        reply = household.call("repaint_take", repaint_arguments(ALICE, ALICE))

    assert reply.is_error is False
    assert ("generate", "song-alices") in household.rows_of(Job, "type", "song_id")
    assert public.get(f"/shared/song/{slug}").json() == shown
    assert household.call("get_song", {"song_id": "song-alices"}).json()["share_slug"] == slug

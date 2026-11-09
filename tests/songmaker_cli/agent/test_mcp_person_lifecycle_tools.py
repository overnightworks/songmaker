"""The tools of a person's own agent that end a share, trash, save and judge takes.

Each case drives the real app in-process through ``/mcp`` with a person's token and, where
the browser's answer is the contract, through the browser's route with a cookie session. Both
people's content comes from ``McpWorld.seed_household``.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from support.mcp_tool_table import ALICE
from support.mcp_world import SAME_ORIGIN, McpWorld
from support.token_world import TokenWorld
from support.web_app import seed_session

from songmaker_cli.db.models import Album, Generation, Playlist, ReferenceRecording, Song, Version
from songmaker_cli.db.queries.albums import enable_album_sharing
from songmaker_cli.db.queries.generations import enable_generation_sharing
from songmaker_cli.db.queries.playlists import enable_playlist_sharing
from songmaker_cli.db.queries.songs import enable_song_sharing
from songmaker_cli.db.soft_delete import include_deleted

_VERSION_COLUMNS = (
    "song_id", "version_number", "lyrics", "prompt", "bpm", "key_scale", "reference_recording_id",
)

# (tool, arguments, enable the share, public path of a slug, model, column the content is read by)
_SHARED_RESOURCES = [
    pytest.param("unshare_album", {"album_id": "album-alices"}, enable_album_sharing,
                 "/shared/{slug}", Album, "title", id="album"),
    pytest.param("unshare_song", {"song_id": "song-alices"}, enable_song_sharing,
                 "/shared/song/{slug}", Song, "title", id="song"),
    pytest.param("unshare_take", {"gen_id": "take-alices"}, enable_generation_sharing,
                 "/shared/gen/{slug}", Generation, "mp3_path", id="take"),
    pytest.param("unshare_playlist", {"playlist_id": "playlist-alices"}, enable_playlist_sharing,
                 "/shared/playlist/{slug}", Playlist, "title", id="playlist"),
]


@pytest.mark.parametrize(
    ("tool", "arguments", "enable_sharing", "public_path", "model", "column"), _SHARED_RESOURCES,
)
def test_an_unshare_tool_ends_the_share_and_leaves_the_content_as_it_was(
    household: McpWorld, tool: str, arguments: dict, enable_sharing, public_path: str,
    model: type, column: str,
) -> None:
    (resource_id,) = arguments.values()
    with household.world.factory() as session:
        slug = enable_sharing(session, resource_id).share_slug
        session.commit()
    visitor = household.world.client
    assert visitor.get(public_path.format(slug=slug)).status_code == 200
    content = household.rows_of(model, "id", column)

    reply = household.call(tool, arguments)

    never_shared = visitor.get(public_path.format(slug="never-shared"))
    ended = visitor.get(public_path.format(slug=slug))
    assert reply.is_error is False
    assert (ended.status_code, ended.json()) == (never_shared.status_code, never_shared.json())
    assert household.rows_of(model, "id", column) == content


def _deleted_at(world: McpWorld, model: type, resource_id: str) -> datetime | None:
    with world.world.factory() as session, include_deleted(session):
        return session.get(model, resource_id).deleted_at


@pytest.mark.parametrize(
    ("deleting", "restoring", "model", "key", "resource_id"),
    [
        pytest.param("delete_album", "restore_album", Album, "album_id", "album-alices",
                     id="album"),
        pytest.param("delete_song", "restore_song", Song, "song_id", "song-alices", id="song"),
    ],
)
def test_a_deleted_album_or_song_is_in_the_trash_and_its_restore_tool_brings_it_back(
    household: McpWorld, deleting: str, restoring: str, model: type, key: str, resource_id: str,
) -> None:
    deleted = household.call(deleting, {key: resource_id})
    in_trash = _deleted_at(household, model, resource_id)
    restored = household.call(restoring, {key: resource_id})

    assert (deleted.is_error, restored.is_error) == (False, False)
    assert in_trash is not None
    assert _deleted_at(household, model, resource_id) is None


def _versions_of(world: McpWorld, song_id: str) -> list[tuple]:
    return sorted(row for row in world.rows_of(Version, *_VERSION_COLUMNS) if row[0] == song_id)


def _give_the_songs_version_its_settings(world: McpWorld, name: str) -> None:
    with world.world.factory() as session:
        version = session.get(Version, f"version-{name}")
        version.bpm, version.key_scale = 120, "C major"
        version.reference_recording_id = f"reference-{name}"
        session.commit()


def test_a_save_of_the_lyrics_alone_keeps_the_other_fields_and_the_reference_link(
    household: McpWorld,
) -> None:
    _give_the_songs_version_its_settings(household, ALICE)

    reply = household.call("update_song", {"song_id": "song-alices", "lyrics": "A new verse"})

    assert reply.is_error is False
    assert _versions_of(household, "song-alices") == [
        ("song-alices", 1, "la", "pop", 120, "C major", "reference-alices"),
        ("song-alices", 2, "A new verse", "pop", 120, "C major", "reference-alices"),
    ]
    unused = dict(household.rows_of(ReferenceRecording, "id", "unused_since"))
    assert unused["reference-alices"] is None


def test_a_save_that_changes_a_song_with_a_take_makes_a_new_version_as_the_browser_does(
    household: McpWorld,
) -> None:
    household.call("update_song", {"song_id": "song-alices", "lyrics": "A new verse"})
    seed_session(household.world.client, "bob")
    browser = household.world.client.put(
        "/api/songs/song-bobs", json={"lyrics": "A new verse"}, headers=SAME_ORIGIN)

    assert browser.status_code == 200
    assert len(_versions_of(household, "song-alices")) == 2
    assert len(_versions_of(household, "song-bobs")) == 2


def test_a_save_of_a_song_without_a_take_rewrites_its_latest_version(household: McpWorld) -> None:
    song_id = household.seed_song_without_lyrics(TokenWorld.ALICE)

    reply = household.call("update_song", {"song_id": song_id, "lyrics": "First verse"})

    assert reply.is_error is False
    assert [row[1:3] for row in _versions_of(household, song_id)] == [(1, "First verse")]


def _archive_the_take(world: McpWorld, name: str) -> None:
    with world.world.factory() as session:
        session.get(Generation, f"take-{name}").is_archived = True
        session.commit()


def _browser_answer(world: McpWorld, path: str):
    seed_session(world.world.client, "alice")
    return world.world.client.post(path, headers=SAME_ORIGIN)


def test_picking_a_take_lifts_the_pick_of_the_songs_previous_take(household: McpWorld) -> None:
    with household.world.factory() as session:
        session.add(Generation(id="take-alices-2", song_id="song-alices",
                               version_id="version-alices", generation_number=2, seed=2,
                               mp3_path="alices/second.mp3"))
        session.commit()

    reply = household.call("pick_take", {"gen_id": "take-alices-2"})

    assert reply.is_error is False
    assert dict(household.rows_of(Generation, "id", "is_picked")) == {
        "take-alices": False, "take-alices-2": True, "take-bobs": True}


def test_picking_an_archived_take_is_refused_as_the_browser_refuses_it(
    household: McpWorld,
) -> None:
    _archive_the_take(household, ALICE)
    picks = household.rows_of(Generation, "id", "is_picked")

    reply = household.call("pick_take", {"gen_id": "take-alices"})
    browser = _browser_answer(household, "/api/generations/take-alices/pick")

    assert browser.status_code == 409
    assert reply.is_error
    assert browser.json()["detail"] in reply.text
    assert household.rows_of(Generation, "id", "is_picked") == picks


@pytest.mark.parametrize(
    ("tool", "column", "path"),
    [
        pytest.param("unpick_take", "is_picked", "/api/generations/take-alices/unpick",
                     id="unpick"),
        pytest.param("unkeep_take", "is_kept", "/api/generations/take-alices/unkeep",
                     id="unkeep"),
    ],
)
def test_unpicking_or_unkeeping_an_archived_take_answers_as_the_browser_does(
    household: McpWorld, tool: str, column: str, path: str,
) -> None:
    _archive_the_take(household, ALICE)
    with household.world.factory() as session:
        session.get(Generation, "take-alices").is_kept = True
        session.commit()

    reply = household.call(tool, {"gen_id": "take-alices"})
    browser = _browser_answer(household, path)

    assert (reply.is_error, browser.status_code) == (False, 200)
    assert reply.json() == browser.json()
    assert dict(household.rows_of(Generation, "id", column))["take-alices"] is False


def test_unkeeping_a_reference_clears_the_callers_keep_and_not_another_persons(
    household: McpWorld,
) -> None:
    with household.world.factory() as session:
        session.get(ReferenceRecording, "reference-alices").is_kept = True
        session.get(ReferenceRecording, "reference-bobs").is_kept = True
        session.commit()

    reply = household.call("unkeep_reference", {"reference_id": "reference-alices"})

    assert reply.is_error is False
    kept = dict(household.rows_of(ReferenceRecording, "id", "is_kept"))
    assert (kept["reference-alices"], kept["reference-bobs"]) == (False, True)

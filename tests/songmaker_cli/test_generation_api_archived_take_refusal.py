"""Keep, pick, share and playlist add refuse an archived take; Restore first."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from support.web_app import make_test_app, seed_session, seed_user

from songmaker_cli.db.models import (
    Album,
    AuditLog,
    Generation,
    Playlist,
    PlaylistEntry,
    Song,
    Version,
)

RESTORE_FIRST = {"detail": "Restore this take first."}
OWNER = "owner"
STRANGER = "stranger"
ARCHIVED_PICK = "g-archived-pick"
ARCHIVED_SIBLING = "g-archived"
LIVE_PICK = "g-live-pick"
ONLY_ARCHIVED = "g-only"


def _archive_world_take(gen_id: str, song_id: str, number: int, **flags: bool) -> Generation:
    return Generation(
        id=gen_id, song_id=song_id, version_id=f"v-{song_id}", generation_number=number,
        mp3_path=f"{OWNER}/{gen_id}.mp3", **flags,
    )


def _seed_archive_world(session: Session) -> None:
    owner = seed_user(session, OWNER)
    stranger = seed_user(session, STRANGER)
    session.add_all([
        Album(id="a-mixed", title="Mixed", artist="X", created_by=owner.id),
        Album(id="a-archived", title="Archived only", artist="X", created_by=owner.id),
    ])
    session.flush()
    session.add_all(
        Song(id=song_id, slug=song_id, title=song_id, album_id=album_id, track_number=number)
        for song_id, album_id, number in (
            ("s-mixed", "a-mixed", 1),
            ("s-archived-pick", "a-mixed", 2),
            ("s-archived", "a-archived", 1),
        )
    )
    session.flush()
    session.add_all([
        Version(id=f"v-{song}", song_id=song, version_number=1, lyrics="l", prompt="p")
        for song in ("s-mixed", "s-archived-pick", "s-archived")
    ])
    session.flush()
    session.add_all([
        _archive_world_take(LIVE_PICK, "s-mixed", 1, is_picked=True),
        _archive_world_take(ARCHIVED_SIBLING, "s-mixed", 2, is_archived=True),
        _archive_world_take(ARCHIVED_PICK, "s-archived-pick", 1, is_picked=True, is_archived=True),
        _archive_world_take(ONLY_ARCHIVED, "s-archived", 1, is_archived=True),
    ])
    session.add_all([
        Playlist(id="pl-owner", title="Mine", slug="mine", created_by=owner.id),
        Playlist(id="pl-stranger", title="Theirs", slug="theirs", created_by=stranger.id),
    ])


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    web, _ = make_test_app(tmp_path, seed_db=_seed_archive_world)
    seed_session(web, OWNER)
    return web


def _stored_take(client: TestClient, gen_id: str) -> Generation:
    with client.app.state.ctx.db() as session:
        gen = session.get(Generation, gen_id)
        session.expunge(gen)
        return gen


def _stored_entry_count(client: TestClient) -> int:
    with client.app.state.ctx.db() as session:
        return session.query(PlaylistEntry).count()


def _generation_audit_count(client: TestClient) -> int:
    with client.app.state.ctx.db() as session:
        return session.query(AuditLog).filter_by(resource_type="generation").count()


def _request_mark(client: TestClient, route: str, gen_id: str):
    if route == "playlist":
        return client.post(
            "/api/playlists/pl-owner/entries/generation", json={"generation_id": gen_id},
        )
    return client.post(f"/api/generations/{gen_id}/{route}")


MARKING_ROUTES = ["keep", "pick", "share", "playlist"]


@pytest.mark.parametrize("route", MARKING_ROUTES)
def test_marking_an_archived_take_answers_409_and_leaves_it_unmarked(
    client: TestClient, route: str,
) -> None:
    response = _request_mark(client, route, ARCHIVED_SIBLING)

    assert response.status_code == 409
    assert response.json() == RESTORE_FIRST
    gen = _stored_take(client, ARCHIVED_SIBLING)
    assert (gen.is_kept, gen.is_picked, gen.is_shared, gen.share_slug) == (
        False, False, False, None,
    )
    assert _stored_entry_count(client) == 0
    assert _generation_audit_count(client) == 0


def test_picking_an_archived_take_leaves_the_sibling_pick_in_place(
    client: TestClient,
) -> None:
    assert _request_mark(client, "pick", ARCHIVED_SIBLING).status_code == 409

    assert _stored_take(client, LIVE_PICK).is_picked is True


@pytest.mark.parametrize("route", MARKING_ROUTES)
def test_a_restored_take_can_be_marked(client: TestClient, route: str) -> None:
    assert client.post(f"/api/generations/{ARCHIVED_SIBLING}/unarchive").status_code == 200

    assert _request_mark(client, route, ARCHIVED_SIBLING).status_code == 200

    gen = _stored_take(client, ARCHIVED_SIBLING)
    assert gen.is_archived is False
    assert {
        "keep": gen.is_kept, "pick": gen.is_picked,
        "share": gen.is_shared, "playlist": gen.is_kept,
    }[route] is True


@pytest.mark.parametrize("route", MARKING_ROUTES)
@pytest.mark.parametrize("who", ["a foreign take", "a missing take"])
def test_marking_a_foreign_or_missing_take_answers_404(
    tmp_path: Path, route: str, who: str,
) -> None:
    web, _ = make_test_app(tmp_path, seed_db=_seed_archive_world)
    seed_session(web, STRANGER)
    gen_id = ARCHIVED_SIBLING if who == "a foreign take" else "g-missing"

    if route == "playlist":
        response = web.post(
            "/api/playlists/pl-stranger/entries/generation", json={"generation_id": gen_id},
        )
    else:
        response = web.post(f"/api/generations/{gen_id}/{route}")

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("route", "flag"), [("unkeep", "is_kept"), ("unpick", "is_picked")],
)
def test_unmarking_an_archived_take_is_still_allowed(
    client: TestClient, route: str, flag: str,
) -> None:
    with client.app.state.ctx.db() as session:
        setattr(session.get(Generation, ARCHIVED_PICK), flag, True)
        session.commit()

    assert client.post(f"/api/generations/{ARCHIVED_PICK}/{route}").status_code == 200

    assert getattr(_stored_take(client, ARCHIVED_PICK), flag) is False


def test_sharing_a_song_whose_pick_is_archived_shares_the_song_and_does_not_keep_it(
    client: TestClient,
) -> None:
    response = client.post("/api/songs/s-archived-pick/share")

    assert response.status_code == 200
    with client.app.state.ctx.db() as session:
        assert session.get(Song, "s-archived-pick").is_shared is True
    assert _stored_take(client, ARCHIVED_PICK).is_kept is False


def test_adding_a_song_with_only_archived_takes_answers_400(client: TestClient) -> None:
    response = client.post("/api/playlists/pl-owner/entries/song", json={"song_id": "s-archived"})

    assert response.status_code == 400
    assert response.json() == {"detail": "Song has no playable take"}


def test_adding_an_album_with_only_archived_takes_skips_the_song(client: TestClient) -> None:
    response = client.post("/api/playlists/pl-owner/entries/album", json={"album_id": "a-archived"})

    assert response.status_code == 200
    body = response.json()
    assert body["added_count"] == 0
    assert [(s["song_id"], s["reason"]) for s in body["skipped"]] == [
        ("s-archived", "no_playable_take"),
    ]

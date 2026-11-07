"""Who can reach what through a public share, and what a share presents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.web_app import make_test_app, seed_session, web_client

from songmaker_cli.db.models import Album, Generation, Playlist, PlaylistEntry, Song, User, Version


@dataclass(frozen=True)
class ShareKind:
    """One kind of shareable resource: its owner routes and its public page."""

    name: str
    owner_path: str
    owner_path_template: str
    page_path: str


_KINDS = [
    ShareKind("album", "/api/albums/a1", "/api/albums/{album_id}", "/shared/{slug}"),
    ShareKind("song", "/api/songs/s1", "/api/songs/{song_id}", "/shared/song/{slug}"),
    ShareKind("take", "/api/generations/g1", "/api/generations/{gen_id}", "/shared/gen/{slug}"),
    ShareKind(
        "playlist", "/api/playlists/pl1", "/api/playlists/{playlist_id}", "/shared/playlist/{slug}",
    ),
]
_KIND_IDS = [kind.name for kind in _KINDS]


def _seed_library_of_one_owner(session) -> None:
    """Album a1 with songs s1 (takes g1 picked, g2 newer) and s2 (take g3); playlist pl1."""
    session.add(User(id="u-owner", username="owner", role="user"))
    session.add(User(id="u-stranger", username="stranger", role="user"))
    session.flush()
    session.add(Album(id="a1", title="Album", artist="Artist", created_by="u-owner"))
    session.add(Playlist(id="pl1", title="Playlist", created_by="u-owner"))
    for song_number, song_id in enumerate(("s1", "s2"), start=1):
        session.add(Song(
            id=song_id, title=f"Song {song_id}", album_id="a1", track_number=song_number,
            slug=f"song-{song_id}",
        ))
        session.add(Version(id=f"v-{song_id}", song_id=song_id, version_number=1, lyrics="la"))
    for take_id, song_id, number, picked in (
        ("g1", "s1", 1, True), ("g2", "s1", 2, False), ("g3", "s2", 1, True),
    ):
        session.add(Generation(
            id=take_id, song_id=song_id, version_id=f"v-{song_id}", generation_number=number,
            mp3_path=f"owner/{take_id}.mp3", seed=1, is_picked=picked,
        ))
    session.flush()
    session.add(PlaylistEntry(id="e1", playlist_id="pl1", generation_id="g2", position=0))
    session.add(PlaylistEntry(id="e2", playlist_id="pl1", generation_id="g3", position=1))


@pytest.fixture
def library_app(tmp_path: Path) -> TestClient:
    client, _ = make_test_app(tmp_path, seed_db=_seed_library_of_one_owner)
    seed_session(client, "owner")
    return client


def _stranger_of(client: TestClient) -> TestClient:
    stranger = web_client(client.app, cookies={})
    seed_session(stranger, "stranger")
    return stranger


def _listener_of(client: TestClient) -> TestClient:
    return web_client(client.app, cookies={})


def _enable(client: TestClient, kind: ShareKind) -> str:
    response = client.post(f"{kind.owner_path}/share")
    assert response.status_code == 200
    return response.json()["share_slug"]


@pytest.mark.parametrize("kind", _KINDS, ids=_KIND_IDS)
def test_the_public_page_of_an_ended_share_answers_404(
    library_app: TestClient, kind: ShareKind,
) -> None:
    """Spec: REQ-SHARE-04 -- an ended share's page answers 404 for every kind of share."""
    listener = _listener_of(library_app)
    page_path = kind.page_path.format(slug=_enable(library_app, kind))
    assert listener.get(page_path).status_code == 200

    assert library_app.delete(f"{kind.owner_path}/share").status_code == 200

    assert listener.get(page_path).status_code == 404


@pytest.mark.parametrize("kind", _KINDS, ids=_KIND_IDS)
def test_sharing_again_after_the_end_gives_a_new_link_and_the_old_one_stays_dead(
    library_app: TestClient, kind: ShareKind,
) -> None:
    """Spec: REQ-SHARE-05 -- re-enabling gives a new slug whose page opens while the old slug's
    page stays 404, for every kind of share."""
    listener = _listener_of(library_app)
    old_slug = _enable(library_app, kind)
    assert library_app.delete(f"{kind.owner_path}/share").status_code == 200

    new_slug = _enable(library_app, kind)

    assert new_slug != old_slug
    assert listener.get(kind.page_path.format(slug=new_slug)).status_code == 200
    assert listener.get(kind.page_path.format(slug=old_slug)).status_code == 404


@pytest.mark.parametrize("kind", _KINDS, ids=_KIND_IDS)
def test_another_musician_cannot_end_a_share_and_it_stays_public(
    library_app: TestClient, kind: ShareKind,
) -> None:
    """Spec: REQ-SHARE-06 -- ending a share is authorized on the resource itself: another
    musician's request answers 404 and the link keeps working."""
    page_path = kind.page_path.format(slug=_enable(library_app, kind))

    attempt = _stranger_of(library_app).delete(f"{kind.owner_path}/share")

    assert attempt.status_code == 404
    assert _listener_of(library_app).get(page_path).status_code == 200


def test_ending_a_share_is_offered_only_on_the_four_resources(
    library_app: TestClient,
) -> None:
    """Spec: REQ-SHARE-06 -- the API offers no generic unshare action: every operation that
    ends a share is addressed to an album, song, take or playlist."""
    paths = library_app.app.openapi()["paths"]

    unshare_paths = {
        path for path, operations in paths.items()
        if "delete" in operations and ("share" in path or "shared" in path)
    }

    assert unshare_paths == {f"{kind.owner_path_template}/share" for kind in _KINDS}


def test_a_listener_of_a_share_cannot_edit_generate_pick_or_keep(
    library_app: TestClient,
) -> None:
    """Spec: REQ-SHARE-03 -- with every share link open, an anonymous write to edit, generate,
    pick or keep is refused and changes nothing."""
    for kind in _KINDS:
        _enable(library_app, kind)
    listener = _listener_of(library_app)
    with library_app.app.state.ctx.db() as session:
        kept_before = session.get(Generation, "g2").is_kept

    attempts = [
        listener.put("/api/albums/a1", json={"title": "Hijacked"}),
        listener.put("/api/songs/s1", json={"title": "Hijacked"}),
        listener.put("/api/playlists/pl1", json={"title": "Hijacked"}),
        listener.post("/api/songs/s1/generate", json={}),
        listener.post("/api/generations/g2/pick"),
        listener.post("/api/generations/g2/keep"),
    ]

    assert [attempt.status_code for attempt in attempts] == [401] * len(attempts)
    with library_app.app.state.ctx.db() as session:
        assert session.get(Album, "a1").title == "Album"
        assert session.get(Song, "s1").title == "Song s1"
        assert session.get(Playlist, "pl1").title == "Playlist"
        assert session.get(Generation, "g1").is_picked is True
        assert session.get(Generation, "g2").is_picked is False
        assert session.get(Generation, "g2").is_kept is kept_before


@pytest.mark.parametrize("kind", _KINDS, ids=_KIND_IDS)
def test_a_stranger_reaches_a_private_resource_only_through_its_active_share(
    library_app: TestClient, kind: ShareKind,
) -> None:
    """Spec: REQ-SHARE-25 -- another non-admin musician is refused the private resource, gets
    its public page only while the share is active, and is refused again once it ends."""
    stranger = _stranger_of(library_app)
    assert stranger.get(kind.owner_path).status_code == 404

    page_path = kind.page_path.format(slug=_enable(library_app, kind))
    assert stranger.get(page_path).status_code == 200
    assert stranger.get(kind.owner_path).status_code == 404

    assert library_app.delete(f"{kind.owner_path}/share").status_code == 200
    assert stranger.get(page_path).status_code == 404
    assert stranger.get(kind.owner_path).status_code == 404


def test_album_and_song_shares_present_the_pick_and_not_the_newest_take(
    library_app: TestClient,
) -> None:
    """Spec: REQ-SHARE-21 -- a song with an unarchived Pick presents that Pick even when a
    newer take exists, in an album share and in a song share."""
    album_slug = _enable(library_app, _KINDS[0])
    song_slug = _enable(library_app, _KINDS[1])
    listener = _listener_of(library_app)

    album = listener.get(f"/shared/{album_slug}").json()
    song = listener.get(f"/shared/song/{song_slug}").json()

    presented_in_album = {entry["id"]: entry["generation_id"] for entry in album["songs"]}
    assert presented_in_album["s1"] == "g1"
    assert song["generation_id"] == "g1"


def test_a_playlist_share_presents_the_listed_take_and_drops_an_entry_whose_song_is_gone(
    library_app: TestClient,
) -> None:
    """Spec: REQ-SHARE-23 -- each entry presents its own take, not the song's Pick, and an entry
    whose song was deleted is left out instead of being replaced by another take."""
    slug = _enable(library_app, _KINDS[3])
    listener = _listener_of(library_app)
    before = listener.get(f"/shared/playlist/{slug}").json()
    assert [entry["generation_id"] for entry in before["entries"]] == ["g2", "g3"]

    assert library_app.delete("/api/songs/s2").status_code == 200

    after = listener.get(f"/shared/playlist/{slug}").json()
    assert [entry["generation_id"] for entry in after["entries"]] == ["g2"]


def test_a_take_share_presents_the_shared_take_and_not_the_songs_pick(
    library_app: TestClient,
) -> None:
    """Spec: REQ-SHARE-22 -- sharing a take that is not its song's Pick presents that take."""
    slug = library_app.post("/api/generations/g2/share").json()["share_slug"]

    presented = _listener_of(library_app).get(f"/shared/gen/{slug}").json()

    assert presented["generation_id"] == "g2"

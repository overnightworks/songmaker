"""Personal library index — search, browse filters, ownership, keyset pagination."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import make_authenticated_user, make_router_app, make_router_ctx
from fastapi.testclient import TestClient
from slugify import slugify
from sqlalchemy import event

from songmaker_cli.constants import (
    LIBRARY_CURSOR_INVALID,
    LIBRARY_CURSOR_MISMATCH,
    LIBRARY_ITEM_ALBUM,
    LIBRARY_ITEM_SONG,
    LIBRARY_QUERY_REQUIRED,
    LIBRARY_SORT_NEWEST,
    LIBRARY_SORT_OLDEST,
    LIBRARY_SORT_TITLE,
    PAGE_MAX_LIMIT,
    JobStatus,
    JobType,
)
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import (
    Album,
    ChatMessage,
    Conversation,
    Generation,
    Job,
    Playlist,
    PlaylistEntry,
    Song,
    User,
    UserSongWork,
    Version,
)
from songmaker_cli.db.queries import SongWork, update_job_status
from songmaker_cli.library_api import CONTINUE_MAX_OFFSET

USER_A = "user-a"
USER_B = "user-b"
ADMIN_ID = "user-admin"


def _ts(offset_seconds: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)


def _add_album(
    session, *, album_id: str, title: str, owner: str, created_at: datetime,
    is_archived: bool = False,
) -> Album:
    album = Album(
        id=album_id, title=title, artist="Artist",
        created_by=owner, created_at=created_at, is_archived=is_archived,
    )
    session.add(album)
    return album


def _add_song(
    session, *, song_id: str, title: str, album_id: str, created_at: datetime,
    track_number: int = 1, updated_at: datetime | None = None,
    last_played_at: datetime | None = None,
) -> Song:
    song = Song(
        id=song_id, title=title, album_id=album_id,
        track_number=track_number, created_at=created_at,
        updated_at=updated_at or created_at, last_played_at=last_played_at,
        slug=slugify(title),
    )
    session.add(song)
    session.add(Version(
        song_id=song_id, version_number=1, lyrics="lyrics", prompt="prompt",
    ))
    return song


def _count_queries(engine) -> tuple[list[str], Callable]:
    queries: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany) -> None:
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    return queries, _record


def _library_env(tmp_path: Path) -> tuple[object, object]:
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id=USER_A, username="alice", password_hash="unused", role="user",
        ))
        session.add(User(
            id=USER_B, username="bob", password_hash="unused", role="user",
        ))
        session.add(User(
            id=ADMIN_ID, username="admin", password_hash="unused", role="admin",
        ))
        session.flush()
        _seed_library(session)
        session.commit()

    ctx = make_router_ctx(tmp_path, db=factory)
    return factory, ctx


def _client_for(ctx: object, user_id: str, role: str = "user") -> TestClient:
    app = make_router_app(
        ctx, user=make_authenticated_user(user_id, role=role, username=f"test-{user_id}")
    )
    return TestClient(app)


def _make_client(
    tmp_path: Path, user_id: str, role: str = "user",
) -> tuple[TestClient, object]:
    factory, ctx = _library_env(tmp_path)
    return _client_for(ctx, user_id, role), factory


def _seed_library(session) -> None:
    _add_album(
        session, album_id="nachtstrom", title="Nachtstrom",
        owner=USER_A, created_at=_ts(100),
    )
    _add_song(
        session, song_id="song-tide", title="Tide",
        album_id="nachtstrom", created_at=_ts(110),
    )
    _add_song(
        session, song_id="song-nacht", title="Nachtstrom Remix",
        album_id="nachtstrom", created_at=_ts(120),
    )
    _add_album(
        session, album_id="alice-own", title="Alice Own",
        owner=USER_A, created_at=_ts(50),
    )
    _add_song(
        session, song_id="song-alice", title="Solo",
        album_id="alice-own", created_at=_ts(60),
    )
    _add_album(
        session, album_id="bob-secret", title="Nachtstrom",
        owner=USER_B, created_at=_ts(200),
    )
    _add_song(
        session, song_id="song-bob", title="Nachtstrom Remix",
        album_id="bob-secret", created_at=_ts(210),
    )
    _add_album(
        session, album_id="admin-own", title="Admin Own",
        owner=ADMIN_ID, created_at=_ts(10),
    )
    _add_album(
        session, album_id="percent", title="100% Live",
        owner=USER_A, created_at=_ts(5),
    )


@pytest.fixture
def library_ctx(tmp_path: Path) -> tuple[object, object]:
    return _library_env(tmp_path)


@pytest.fixture
def alice(library_ctx: tuple[object, object]) -> TestClient:
    _factory, ctx = library_ctx
    return _client_for(ctx, USER_A)


@pytest.fixture
def bob(library_ctx: tuple[object, object]) -> TestClient:
    _factory, ctx = library_ctx
    return _client_for(ctx, USER_B)


@pytest.fixture
def admin(library_ctx: tuple[object, object]) -> TestClient:
    _factory, ctx = library_ctx
    return _client_for(ctx, ADMIN_ID, role="admin")


def _collect_search(client: TestClient, q: str, sort: str, limit: int) -> list[dict]:
    items: list[dict] = []
    cursor = None
    seen_cursors: set[str] = set()
    while True:
        params: dict[str, str | int] = {"q": q, "sort": sort, "limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        resp = client.get("/api/library/search", params=params)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["has_more"] == (data["next_cursor"] is not None)
        page_ids = [(item["type"], _hit_id(item)) for item in data["items"]]
        items.extend(data["items"])
        if not data["has_more"]:
            break
        cursor = data["next_cursor"]
        assert cursor not in seen_cursors
        seen_cursors.add(cursor)
        assert page_ids, "has_more with empty page"
    return items


def _hit_id(item: dict) -> str:
    if item["type"] == LIBRARY_ITEM_ALBUM:
        return item["album"]["id"]
    return item["song"]["id"]


def _later(offset_seconds: int) -> datetime:
    """A moment after everything ``_seed_library`` dates, so a place under test leads."""
    return _ts(10_000 + offset_seconds)


def _add_take(
    session, *, generation_id: str, song_id: str, created_at: datetime,
    generation_number: int = 1,
) -> Generation:
    take = Generation(
        id=generation_id, song_id=song_id, generation_number=generation_number,
        mp3_path=f"takes/{generation_id}.mp3", created_at=created_at,
    )
    session.add(take)
    return take


def _add_cowriter_message(
    session, *, song_id: str, author: str, created_at: datetime,
) -> None:
    conversation = Conversation(user_id=author)
    session.add(conversation)
    session.flush()
    session.add(ChatMessage(
        conversation_id=conversation.id, song_id=song_id, role="user",
        content="Tighten the chorus", created_at=created_at,
    ))


def _add_own_work(
    session, *, user_id: str, song_id: str, work: SongWork, at: datetime,
) -> None:
    session.add(UserSongWork(user_id=user_id, song_id=song_id, **{work.value: at}))


def _run_generate_job(
    session, *, author: str, song_id: str, started_at: datetime, ended_at: datetime,
    status: JobStatus = JobStatus.COMPLETED,
) -> None:
    """A generate job that ran from ``started_at`` and ended in ``status`` at ``ended_at``.

    The real status transition decides which of the job's timestamps it
    stamps; that stamp is then moved from the wall clock back to ``ended_at``.
    """
    job = Job(
        type=JobType.GENERATE, status=JobStatus.RUNNING, user_id=author, song_id=song_id,
        started_at=started_at, heartbeat_at=started_at,
    )
    session.add(job)
    session.flush()
    assert update_job_status(session, job.id, status)
    for stamp in ("heartbeat_at", "completed_at"):
        stamped_at = getattr(job, stamp)
        if stamped_at is not None and stamped_at > ended_at:
            setattr(job, stamp, ended_at)


def _add_playlist(
    session, *, playlist_id: str, owner: str, created_at: datetime,
    updated_at: datetime | None = None, last_played_at: datetime | None = None,
    last_played_song_id: str | None = None, cover_key: str | None = None,
) -> Playlist:
    playlist = Playlist(
        id=playlist_id, title=playlist_id.title(), slug=playlist_id, created_by=owner,
        created_at=created_at, updated_at=updated_at or created_at,
        last_played_at=last_played_at, last_played_song_id=last_played_song_id,
        cover_key=cover_key,
    )
    session.add(playlist)
    return playlist


def _add_entry(
    session, *, playlist_id: str, generation_id: str, added_at: datetime, position: int,
) -> None:
    session.add(PlaylistEntry(
        playlist_id=playlist_id, generation_id=generation_id,
        position=position, added_at=added_at,
    ))


def _continue_items(client: TestClient, **params: int) -> list[dict]:
    resp = client.get("/api/library/continue", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def _album_with_song(session, **song_times: datetime) -> None:
    _add_album(
        session, album_id="place-album", title="Place Album", owner=USER_A,
        created_at=_later(0),
    )
    _add_song(
        session, song_id="song-a", title="Song A", album_id="place-album",
        created_at=_later(0), updated_at=song_times.get("updated_at", _later(10)),
        last_played_at=song_times.get("last_played_at"),
    )


def _seed_album_edited_only(session) -> None:
    _album_with_song(session, updated_at=_later(30))


def _seed_album_new_take_only(session) -> None:
    _album_with_song(session)
    _add_take(session, generation_id="take-a", song_id="song-a", created_at=_later(40))


def _seed_album_cowriter_message_only(session) -> None:
    _album_with_song(session)
    _add_cowriter_message(session, song_id="song-a", author=USER_A, created_at=_later(50))


def _seed_album_listened(session) -> None:
    _album_with_song(session, last_played_at=_later(60))


def _seed_album_naming_its_newest_song(session) -> None:
    _album_with_song(session, updated_at=_later(70))
    _add_song(
        session, song_id="song-b", title="Song B", album_id="place-album",
        created_at=_later(0), updated_at=_later(10), track_number=2,
    )
    _add_take(session, generation_id="take-b", song_id="song-b", created_at=_later(80))


def _seed_album_with_an_admin_cowriter_turn(session) -> None:
    _album_with_song(session)
    _add_cowriter_message(session, song_id="song-a", author=ADMIN_ID, created_at=_later(90))


def _seed_empty_album(session) -> None:
    _add_album(
        session, album_id="place-album", title="Place Album", owner=USER_A,
        created_at=_later(20),
    )


def _seed_album_whose_song_is_deleted(session) -> None:
    _album_with_song(session, updated_at=_later(95))
    session.flush()
    session.get(Song, "song-a").deleted_at = _later(96)


def _playlist_sources(session) -> None:
    """Two owned songs with one take each, all dated before the playlist."""
    _add_album(
        session, album_id="source", title="Source", owner=USER_A, created_at=_later(0),
    )
    for song_id in ("song-a", "song-b"):
        _add_song(
            session, song_id=song_id, title=song_id.replace("-", " ").title(),
            album_id="source", created_at=_later(0),
        )
        _add_take(
            session, generation_id=f"take-{song_id}", song_id=song_id, created_at=_later(0),
        )
    session.flush()


def _seed_playlist(
    session, *, entries: list[tuple[str, int]], deleted_song: str | None = None,
    **playlist_times,
) -> None:
    _playlist_sources(session)
    _add_playlist(
        session, playlist_id="place-playlist", owner=USER_A, created_at=_later(1),
        **playlist_times,
    )
    for position, (song_id, added_offset) in enumerate(entries):
        _add_entry(
            session, playlist_id="place-playlist", generation_id=f"take-{song_id}",
            added_at=_later(added_offset), position=position,
        )
    if deleted_song is not None:
        session.get(Song, deleted_song).deleted_at = _later(2)


def _seed_playlist_listened_with_its_song(session) -> None:
    _seed_playlist(
        session, entries=[("song-a", 2), ("song-b", 3)],
        last_played_at=_later(40), last_played_song_id="song-a",
    )


def _seed_playlist_listened_after_its_song_left(session) -> None:
    _seed_playlist(
        session, entries=[("song-b", 3)],
        last_played_at=_later(40), last_played_song_id="song-a",
    )


def _seed_playlist_listened_to_a_deleted_song(session) -> None:
    _seed_playlist(
        session, entries=[("song-b", 3), ("song-a", 5)], deleted_song="song-a",
        last_played_at=_later(40), last_played_song_id="song-a",
    )


def _seed_playlist_whose_newest_entry_is_dead(session) -> None:
    _seed_playlist(session, entries=[("song-b", 3), ("song-a", 50)], deleted_song="song-a")


def _seed_playlist_whose_every_song_is_dead(session) -> None:
    _seed_playlist(session, entries=[("song-a", 50)], deleted_song="song-a")


def _seed_playlist_edited_only(session) -> None:
    _seed_playlist(session, entries=[("song-a", 2), ("song-b", 3)], updated_at=_later(60))


def _seed_empty_playlist(session) -> None:
    _add_playlist(session, playlist_id="place-playlist", owner=USER_A, created_at=_later(7))


@pytest.mark.parametrize(
    ("seed", "place", "activity_offset", "song_id"),
    [
        (_seed_album_edited_only, ("album", "place-album"), 30, "song-a"),
        (_seed_album_new_take_only, ("album", "place-album"), 40, "song-a"),
        (_seed_album_cowriter_message_only, ("album", "place-album"), 50, "song-a"),
        (_seed_album_listened, ("album", "place-album"), 60, "song-a"),
        (_seed_album_naming_its_newest_song, ("album", "place-album"), 80, "song-b"),
        (_seed_album_with_an_admin_cowriter_turn, ("album", "place-album"), 10, "song-a"),
        (_seed_empty_album, ("album", "place-album"), 20, None),
        (_seed_album_whose_song_is_deleted, ("album", "place-album"), 0, None),
        (_seed_playlist_listened_with_its_song, ("playlist", "place-playlist"), 40, "song-a"),
        (_seed_playlist_listened_after_its_song_left, ("playlist", "place-playlist"), 40, "song-b"),
        (_seed_playlist_listened_to_a_deleted_song, ("playlist", "place-playlist"), 40, "song-b"),
        (_seed_playlist_whose_newest_entry_is_dead, ("playlist", "place-playlist"), 3, "song-b"),
        (_seed_playlist_whose_every_song_is_dead, ("playlist", "place-playlist"), 1, None),
        (_seed_playlist_edited_only, ("playlist", "place-playlist"), 60, "song-b"),
        (_seed_empty_playlist, ("playlist", "place-playlist"), 7, None),
    ],
    ids=[
        "album-edited-only",
        "album-new-take-only",
        "album-cowriter-message-only",
        "album-listened",
        "album-names-its-newest-song",
        "album-admin-cowriter-turn-counts-nothing",
        "empty-album",
        "album-whose-only-song-is-deleted",
        "playlist-listened-with-its-song",
        "playlist-listened-after-its-song-left",
        "playlist-listened-to-a-deleted-song",
        "playlist-whose-newest-entry-is-dead",
        "playlist-whose-every-song-is-dead",
        "playlist-edited-only",
        "empty-playlist",
    ],
)
def test_continue_dates_a_place_by_its_newest_activity_and_names_its_song(
    tmp_path: Path, seed: Callable, place: tuple[str, str], activity_offset: int,
    song_id: str | None,
) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        seed(session)
        session.commit()

    items = _continue_items(client)

    tile = next(item for item in items if (item["type"], item["id"]) == place)
    assert items[0] is tile
    assert tile["activity_at"] == _later(activity_offset).isoformat()
    assert tile["song_id"] == song_id
    assert (tile["song_title"] is None) == (song_id is None)


FOREIGN_ALBUM = "foreign-album"


def _foreign_album_its_owner_works_in(session) -> None:
    """USER_B's album, created and worked in by USER_B after anything the admin does."""
    _add_album(
        session, album_id=FOREIGN_ALBUM, title="Vernissage", owner=USER_B,
        created_at=_later(500),
    )
    for track, song_id in enumerate(("foreign-a", "foreign-b"), start=1):
        _add_song(
            session, song_id=song_id, title=song_id.replace("-", " ").title(),
            album_id=FOREIGN_ALBUM, created_at=_later(500), updated_at=_later(510),
            last_played_at=_later(520), track_number=track,
        )
        _add_take(session, generation_id=f"take-{song_id}", song_id=song_id, created_at=_later(530))
        _add_cowriter_message(session, song_id=song_id, author=USER_B, created_at=_later(540))
        _run_generate_job(
            session, author=USER_B, song_id=song_id, started_at=_later(525),
            ended_at=_later(550),
        )
    session.flush()


def _seed_foreign_album_the_admin_edited(session) -> None:
    _foreign_album_its_owner_works_in(session)
    _add_own_work(
        session, user_id=ADMIN_ID, song_id="foreign-a", work=SongWork.EDITED, at=_later(30),
    )


def _seed_foreign_album_the_admin_listened_to(session) -> None:
    _foreign_album_its_owner_works_in(session)
    _add_own_work(
        session, user_id=ADMIN_ID, song_id="foreign-a", work=SongWork.PLAYED, at=_later(35),
    )


def _foreign_album_with_an_admin_generate_job(
    session, *, status: JobStatus, saved_a_take: bool,
) -> None:
    _foreign_album_its_owner_works_in(session)
    if saved_a_take:
        _add_take(
            session, generation_id="take-admin", song_id="foreign-a", created_at=_later(40),
            generation_number=2,
        )
    _run_generate_job(
        session, author=ADMIN_ID, song_id="foreign-a", started_at=_later(38),
        ended_at=_later(42), status=status,
    )


def _seed_foreign_album_the_admin_made_a_take_in(session) -> None:
    _foreign_album_with_an_admin_generate_job(
        session, status=JobStatus.COMPLETED, saved_a_take=True,
    )


def _seed_foreign_album_the_admins_partial_batch_made_a_take_in(session) -> None:
    _foreign_album_with_an_admin_generate_job(
        session, status=JobStatus.PARTIAL, saved_a_take=True,
    )


def _seed_foreign_album_the_admins_cancelled_batch_made_a_take_in(session) -> None:
    _foreign_album_with_an_admin_generate_job(
        session, status=JobStatus.CANCELLED, saved_a_take=True,
    )


def _seed_foreign_album_the_admin_wrote_with_the_co_writer_in(session) -> None:
    _foreign_album_its_owner_works_in(session)
    _add_cowriter_message(session, song_id="foreign-a", author=ADMIN_ID, created_at=_later(45))


def _seed_foreign_album_naming_the_admins_newest_song(session) -> None:
    _seed_foreign_album_the_admin_edited(session)
    _add_own_work(
        session, user_id=ADMIN_ID, song_id="foreign-b", work=SongWork.PLAYED, at=_later(60),
    )


def _seed_foreign_album_worked_in_by_its_owner_only(session) -> None:
    _foreign_album_its_owner_works_in(session)


def _seed_foreign_album_whose_admin_song_is_deleted(session) -> None:
    _seed_foreign_album_the_admin_edited(session)
    session.get(Song, "foreign-a").deleted_at = _later(31)


def _seed_foreign_album_with_a_failed_admin_take(session) -> None:
    _foreign_album_with_an_admin_generate_job(
        session, status=JobStatus.FAILED, saved_a_take=False,
    )


def _seed_foreign_album_with_an_admin_batch_cancelled_before_any_take(session) -> None:
    _foreign_album_with_an_admin_generate_job(
        session, status=JobStatus.CANCELLED, saved_a_take=False,
    )


def _seed_archived_foreign_album_the_admin_edited(session) -> None:
    _seed_foreign_album_the_admin_edited(session)
    session.get(Album, FOREIGN_ALBUM).is_archived = True


@pytest.mark.parametrize(
    ("seed", "expected"),
    [
        (_seed_foreign_album_the_admin_edited, [(30, "foreign-a")]),
        (_seed_foreign_album_the_admin_listened_to, [(35, "foreign-a")]),
        (_seed_foreign_album_the_admin_made_a_take_in, [(40, "foreign-a")]),
        (_seed_foreign_album_the_admins_partial_batch_made_a_take_in, [(40, "foreign-a")]),
        (_seed_foreign_album_the_admins_cancelled_batch_made_a_take_in, [(40, "foreign-a")]),
        (_seed_foreign_album_the_admin_wrote_with_the_co_writer_in, [(45, "foreign-a")]),
        (_seed_foreign_album_naming_the_admins_newest_song, [(60, "foreign-b")]),
        (_seed_foreign_album_worked_in_by_its_owner_only, []),
        (_seed_foreign_album_whose_admin_song_is_deleted, []),
        (_seed_foreign_album_with_a_failed_admin_take, []),
        (_seed_foreign_album_with_an_admin_batch_cancelled_before_any_take, []),
        (_seed_archived_foreign_album_the_admin_edited, []),
    ],
    ids=[
        "admin-edit",
        "admin-listen",
        "admin-take",
        "admin-partial-batch-take",
        "admin-cancelled-batch-take",
        "admin-co-writer-message",
        "names-the-admins-newest-song",
        "owner-work-only-is-left-out",
        "admin-work-on-a-deleted-song-is-left-out",
        "failed-admin-take-is-left-out",
        "admin-batch-cancelled-before-any-take-is-left-out",
        "archived-album-is-left-out",
    ],
)
def test_an_admins_continue_ranks_a_foreign_album_by_the_admins_own_work_alone(
    tmp_path: Path, seed: Callable, expected: list[tuple[int, str]],
) -> None:
    client, factory = _make_client(tmp_path, ADMIN_ID, role="admin")
    with factory() as session:
        seed(session)
        session.commit()

    items = _continue_items(client, limit=PAGE_MAX_LIMIT)

    foreign = [
        (item["id"], item["activity_at"], item["song_id"])
        for item in items if item["id"] != "admin-own"
    ]
    assert foreign == [
        (FOREIGN_ALBUM, _later(offset).isoformat(), song_id) for offset, song_id in expected
    ]
    assert items[-1]["id"] == "admin-own"


def test_an_admins_edit_moves_both_continues_while_the_owners_edit_leaves_the_admins_alone(
    library_ctx: tuple[object, object],
) -> None:
    factory, ctx = library_ctx
    with factory() as session:
        _add_album(
            session, album_id="bob-other", title="Bob Other", owner=USER_B, created_at=_later(0),
        )
        _add_song(
            session, song_id="song-bob-other", title="Other", album_id="bob-other",
            created_at=_later(0),
        )
        session.commit()
    admin = _client_for(ctx, ADMIN_ID, role="admin")
    bob = _client_for(ctx, USER_B)
    assert _continue_items(bob)[0]["id"] == "bob-other"
    assert [item["id"] for item in _continue_items(admin)] == ["admin-own"]

    assert admin.put("/api/songs/song-bob", json={"lyrics": "felix was here"}).status_code == 200

    assert _continue_items(admin)[0]["id"] == "bob-secret"
    assert _continue_items(bob)[0]["id"] == "bob-secret"

    admin_continue = admin.get("/api/library/continue").content
    for song_id in ("song-bob", "song-bob-other"):
        assert bob.put(f"/api/songs/{song_id}", json={"lyrics": "leonardo"}).status_code == 200

    assert admin.get("/api/library/continue").content == admin_continue


def test_a_musicians_continue_ignores_their_own_work_on_albums_they_cannot_open(
    library_ctx: tuple[object, object],
) -> None:
    factory, ctx = library_ctx
    alice = _client_for(ctx, USER_A)
    window = {"limit": PAGE_MAX_LIMIT}
    before = alice.get("/api/library/continue", params=window).content

    with factory() as session:
        _add_own_work(
            session, user_id=USER_A, song_id="song-bob", work=SongWork.EDITED, at=_later(10),
        )
        _add_take(session, generation_id="take-alice", song_id="song-bob", created_at=_later(20))
        _run_generate_job(
            session, author=USER_A, song_id="song-bob", started_at=_later(19),
            ended_at=_later(21),
        )
        _add_cowriter_message(session, song_id="song-bob", author=USER_A, created_at=_later(30))
        session.commit()

    assert alice.get("/api/library/continue", params=window).content == before


def test_continue_shows_six_places_once_each_newest_first_ties_by_type_then_id(
    tmp_path: Path,
) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        for album_id, offset in [
            ("album-b", 100), ("album-a", 100), ("album-c", 90),
            ("album-d", 80), ("album-e", 70), ("album-f", 60),
        ]:
            _add_album(
                session, album_id=album_id, title=album_id, owner=USER_A,
                created_at=_later(0),
            )
            for track in (1, 2):
                _add_song(
                    session, song_id=f"{album_id}-{track}", title=f"{album_id} {track}",
                    album_id=album_id, created_at=_later(0), updated_at=_later(offset),
                    track_number=track,
                )
        _add_playlist(session, playlist_id="playlist-a", owner=USER_A, created_at=_later(100))
        _add_album(
            session, album_id="archived", title="Archived", owner=USER_A,
            created_at=_later(0), is_archived=True,
        )
        _add_song(
            session, song_id="archived-song", title="Archived Song", album_id="archived",
            created_at=_later(0), updated_at=_later(500),
        )
        _add_album(
            session, album_id="foreign", title="Foreign", owner=USER_B, created_at=_later(300),
        )
        _add_playlist(session, playlist_id="foreign-playlist", owner=USER_B, created_at=_later(300))
        session.commit()

    items = _continue_items(client)

    assert [(item["type"], item["id"]) for item in items] == [
        ("album", "album-a"),
        ("album", "album-b"),
        ("playlist", "playlist-a"),
        ("album", "album-c"),
        ("album", "album-d"),
        ("album", "album-e"),
    ]
    assert [item["song_id"] for item in items[:2]] == ["album-a-1", "album-b-1"]


def test_continue_tiles_carry_the_cover_the_place_page_shows(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="covered", title="Covered", owner=USER_A, created_at=_later(0),
        ).cover_key = "album-key"
        _add_song(
            session, song_id="covered-song", title="Covered Song", album_id="covered",
            created_at=_later(0), updated_at=_later(20),
        )
        _add_take(
            session, generation_id="covered-take", song_id="covered-song", created_at=_later(0),
        )
        _add_playlist(session, playlist_id="mosaic", owner=USER_A, created_at=_later(30))
        _add_playlist(
            session, playlist_id="uploaded", owner=USER_A, created_at=_later(10),
            cover_key="playlist-key",
        )
        session.flush()
        _add_entry(
            session, playlist_id="mosaic", generation_id="covered-take",
            added_at=_later(1), position=0,
        )
        session.commit()

    items = {item["id"]: item for item in _continue_items(client)}

    assert items["covered"]["cover"]["card"] == (
        "/api/albums/covered/cover?variant=card&v=album-key"
    )
    assert items["covered"]["album_covers"] == []
    assert items["covered"]["song_title"] == "Covered Song"
    assert items["mosaic"]["cover"] is None
    assert items["mosaic"]["album_covers"] == [items["covered"]["cover"]]
    assert items["mosaic"]["song_title"] == "Covered Song"
    assert items["uploaded"]["cover"]["card"] == (
        "/api/playlists/uploaded/cover?variant=card&v=playlist-key"
    )


@pytest.mark.parametrize(
    ("viewer_id", "role", "statements"),
    [(USER_A, "user", 3), (ADMIN_ID, "admin", 4)],
    ids=["musician", "admin-reading-foreign-albums-too"],
)
def test_continue_reads_every_place_in_a_fixed_number_of_statements(
    tmp_path: Path, viewer_id: str, role: str, statements: int,
) -> None:
    client, factory = _make_client(tmp_path, viewer_id, role)
    with factory() as session:
        for index in range(8):
            album_id = f"busy-{index}"
            _add_album(
                session, album_id=album_id, title=album_id, owner=USER_A, created_at=_later(0),
            )
            _add_song(
                session, song_id=f"{album_id}-song", title=f"{album_id} song",
                album_id=album_id, created_at=_later(0), updated_at=_later(index),
            )
            _add_take(
                session, generation_id=f"{album_id}-take", song_id=f"{album_id}-song",
                created_at=_later(index),
            )
            _add_cowriter_message(
                session, song_id=f"{album_id}-song", author=USER_A, created_at=_later(index),
            )
            _add_own_work(
                session, user_id=ADMIN_ID, song_id=f"{album_id}-song", work=SongWork.EDITED,
                at=_later(index),
            )
            _add_playlist(
                session, playlist_id=f"list-{index}", owner=viewer_id, created_at=_later(index),
            )
            session.flush()
            _add_entry(
                session, playlist_id=f"list-{index}", generation_id=f"{album_id}-take",
                added_at=_later(index), position=0,
            )
        session.commit()
        engine = session.get_bind()

    queries, handle = _count_queries(engine)
    try:
        resp = client.get("/api/library/continue")
    finally:
        event.remove(engine, "before_cursor_execute", handle)

    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 6
    assert len(queries) == statements, f"expected {statements} statements, got {queries}"


def _add_album_the_viewer_owns(session, *, viewer_id: str, index: int) -> None:
    _add_album(
        session, album_id=f"album-{index}", title=f"Album {index}", owner=viewer_id,
        created_at=_later(index),
    )


def _add_foreign_album_the_viewer_edited(session, *, viewer_id: str, index: int) -> None:
    _add_album(
        session, album_id=f"album-{index}", title=f"Album {index}", owner=USER_B,
        created_at=_later(100),
    )
    _add_song(
        session, song_id=f"song-{index}", title=f"Song {index}", album_id=f"album-{index}",
        created_at=_later(100), updated_at=_later(100),
    )
    session.flush()
    _add_own_work(
        session, user_id=viewer_id, song_id=f"song-{index}", work=SongWork.EDITED,
        at=_later(index),
    )


@pytest.mark.parametrize(
    ("viewer_id", "role", "odd_album"),
    [
        (USER_A, "user", _add_album_the_viewer_owns),
        (ADMIN_ID, "admin", _add_foreign_album_the_viewer_edited),
    ],
    ids=["musician", "admin-with-foreign-albums-between-its-own"],
)
@pytest.mark.parametrize(
    ("window", "expected_indexes"),
    [
        ({"limit": 8}, [7, 6, 5, 4, 3, 2, 1, 0]),
        ({"offset": 0, "limit": 3}, [7, 6, 5]),
        ({"offset": 5, "limit": 3}, [2, 1, 0]),
    ],
)
def test_continue_returns_the_window_of_places_the_caller_asks_for(
    tmp_path: Path, viewer_id: str, role: str, odd_album: Callable,
    window: dict[str, int], expected_indexes: list[int],
) -> None:
    client, factory = _make_client(tmp_path, viewer_id, role)
    with factory() as session:
        for index in range(8):
            add_album = odd_album if index % 2 else _add_album_the_viewer_owns
            add_album(session, viewer_id=viewer_id, index=index)
        session.commit()

    items = _continue_items(client, **window)

    assert [item["id"] for item in items] == [f"album-{index}" for index in expected_indexes]


@pytest.mark.parametrize(
    "window",
    [
        {"limit": 0},
        {"limit": PAGE_MAX_LIMIT + 1},
        {"offset": -1},
        {"offset": CONTINUE_MAX_OFFSET + 1},
    ],
)
def test_continue_refuses_a_window_outside_its_bound(
    alice: TestClient, window: dict[str, int],
) -> None:
    assert alice.get("/api/library/continue", params=window).status_code == 422


def test_search_requires_query(alice: TestClient) -> None:
    assert alice.get("/api/library/search").status_code == 422
    assert alice.get("/api/library/search", params={"q": ""}).status_code == 422
    resp = alice.get("/api/library/search", params={"q": "   "})
    assert resp.status_code == 422
    assert resp.json()["detail"] == LIBRARY_QUERY_REQUIRED


def test_search_album_title_nachtstrom(alice: TestClient) -> None:
    resp = alice.get("/api/library/search", params={"q": "nachtstrom"})
    assert resp.status_code == 200
    data = resp.json()
    types_and_ids = [(item["type"], _hit_id(item)) for item in data["items"]]
    assert (LIBRARY_ITEM_ALBUM, "nachtstrom") in types_and_ids
    album_hit = next(
        item for item in data["items"]
        if item["type"] == LIBRARY_ITEM_ALBUM and item["album"]["id"] == "nachtstrom"
    )
    assert album_hit["album"]["title"] == "Nachtstrom"


def test_search_song_title_includes_album_context(alice: TestClient) -> None:
    resp = alice.get("/api/library/search", params={"q": "remix"})
    assert resp.status_code == 200
    songs = [item for item in resp.json()["items"] if item["type"] == LIBRARY_ITEM_SONG]
    assert len(songs) == 1
    hit = songs[0]
    assert hit["song"]["id"] == "song-nacht"
    assert hit["album_id"] == "nachtstrom"
    assert hit["album_title"] == "Nachtstrom"
    assert hit["song"]["album_id"] == "nachtstrom"
    assert hit["song"]["album_title"] == "Nachtstrom"


def test_search_is_case_insensitive(alice: TestClient) -> None:
    upper = alice.get("/api/library/search", params={"q": "NACHTSTROM"}).json()
    lower = alice.get("/api/library/search", params={"q": "nachtstrom"}).json()
    assert [_hit_id(i) for i in upper["items"]] == [_hit_id(i) for i in lower["items"]]


def test_user_b_never_sees_user_a_titles(alice: TestClient, bob: TestClient) -> None:
    alice_hits = {
        (item["type"], _hit_id(item))
        for item in alice.get("/api/library/search", params={"q": "nachtstrom"}).json()["items"]
    }
    bob_hits = {
        (item["type"], _hit_id(item))
        for item in bob.get("/api/library/search", params={"q": "nachtstrom"}).json()["items"]
    }
    assert (LIBRARY_ITEM_ALBUM, "nachtstrom") in alice_hits
    assert (LIBRARY_ITEM_SONG, "song-nacht") in alice_hits
    assert (LIBRARY_ITEM_ALBUM, "bob-secret") not in alice_hits
    assert (LIBRARY_ITEM_SONG, "song-bob") not in alice_hits
    assert (LIBRARY_ITEM_ALBUM, "bob-secret") in bob_hits
    assert (LIBRARY_ITEM_SONG, "song-bob") in bob_hits
    assert (LIBRARY_ITEM_ALBUM, "nachtstrom") not in bob_hits
    assert (LIBRARY_ITEM_SONG, "song-nacht") not in bob_hits

    alice_albums = {a["id"] for a in alice.get("/api/albums").json()["items"]}
    bob_albums = {a["id"] for a in bob.get("/api/albums").json()["items"]}
    assert "nachtstrom" in alice_albums
    assert "bob-secret" not in alice_albums
    assert "bob-secret" in bob_albums
    assert "nachtstrom" not in bob_albums

    alice_songs = {s["id"] for s in alice.get("/api/songs").json()["items"]}
    bob_songs = {s["id"] for s in bob.get("/api/songs").json()["items"]}
    assert "song-nacht" in alice_songs
    assert "song-bob" not in alice_songs
    assert "song-bob" in bob_songs
    assert "song-nacht" not in bob_songs


def test_admin_search_finds_every_album_and_song_the_admin_can_open(admin: TestClient) -> None:
    albums = {a["id"] for a in admin.get("/api/albums").json()["items"]}
    hits = {
        (item["type"], _hit_id(item))
        for item in admin.get("/api/library/search", params={"q": "nachtstrom"}).json()["items"]
    }
    assert {"nachtstrom", "bob-secret"} <= albums
    assert hits == {
        (LIBRARY_ITEM_ALBUM, "nachtstrom"),
        (LIBRARY_ITEM_SONG, "song-nacht"),
        (LIBRARY_ITEM_ALBUM, "bob-secret"),
        (LIBRARY_ITEM_SONG, "song-bob"),
    }


def test_search_keyset_pages_without_dupes_or_gaps(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        for i in range(8):
            _add_album(
                session,
                album_id=f"page-a{i:02d}",
                title=f"Catalog {i:02d}",
                owner=USER_A,
                created_at=_ts(1000 + i),
            )
            _add_song(
                session,
                song_id=f"page-s{i:02d}",
                title=f"Catalog Song {i:02d}",
                album_id=f"page-a{i:02d}",
                created_at=_ts(2000 + i),
            )
        session.commit()

    items = _collect_search(client, q="Catalog", sort=LIBRARY_SORT_NEWEST, limit=3)
    keys = [(item["type"], _hit_id(item)) for item in items]
    assert len(keys) == 16
    assert len(set(keys)) == 16
    expected_songs = [(LIBRARY_ITEM_SONG, f"page-s{i:02d}") for i in range(7, -1, -1)]
    expected_albums = [(LIBRARY_ITEM_ALBUM, f"page-a{i:02d}") for i in range(7, -1, -1)]
    assert keys == expected_songs + expected_albums


def test_search_title_sort_album_before_song_then_id(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="z-album", title="Same Title",
            owner=USER_A, created_at=_ts(1),
        )
        _add_song(
            session, song_id="a-song", title="Same Title",
            album_id="z-album", created_at=_ts(1),
        )
        session.commit()
    resp = client.get(
        "/api/library/search",
        params={"q": "Same Title", "sort": LIBRARY_SORT_TITLE},
    )
    keys = [(i["type"], _hit_id(i)) for i in resp.json()["items"]]
    assert keys[0] == (LIBRARY_ITEM_ALBUM, "z-album")
    assert keys[1] == (LIBRARY_ITEM_SONG, "a-song")


def test_insert_after_first_page_does_not_appear_on_second(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        for i in range(4):
            _add_album(
                session,
                album_id=f"ks-a{i}",
                title=f"Keyset {i}",
                owner=USER_A,
                created_at=_ts(3000 + i),
            )
        session.commit()

    first = client.get(
        "/api/library/search",
        params={"q": "Keyset", "sort": LIBRARY_SORT_NEWEST, "limit": 2},
    ).json()
    assert first["has_more"] is True
    cursor = first["next_cursor"]
    first_ids = [_hit_id(i) for i in first["items"]]
    assert first_ids == ["ks-a3", "ks-a2"]

    with factory() as session:
        _add_album(
            session, album_id="ks-new", title="Keyset newest",
            owner=USER_A, created_at=_ts(4000),
        )
        session.commit()

    second = client.get(
        "/api/library/search",
        params={"q": "Keyset", "sort": LIBRARY_SORT_NEWEST, "limit": 2, "cursor": cursor},
    ).json()
    second_ids = [_hit_id(i) for i in second["items"]]
    assert "ks-new" not in second_ids
    assert "ks-a3" not in second_ids
    assert "ks-a2" not in second_ids
    assert second_ids == ["ks-a1", "ks-a0"]


def test_cursor_mismatch_and_tampering_are_rejected(alice: TestClient) -> None:
    first = alice.get(
        "/api/library/search",
        params={"q": "nachtstrom", "sort": LIBRARY_SORT_NEWEST, "limit": 1},
    ).json()
    cursor = first["next_cursor"]
    assert cursor

    mismatch = alice.get(
        "/api/library/search",
        params={"q": "tide", "sort": LIBRARY_SORT_NEWEST, "cursor": cursor},
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["detail"] == LIBRARY_CURSOR_MISMATCH

    sort_mismatch = alice.get(
        "/api/library/search",
        params={"q": "nachtstrom", "sort": LIBRARY_SORT_TITLE, "cursor": cursor},
    )
    assert sort_mismatch.status_code == 422
    assert sort_mismatch.json()["detail"] == LIBRARY_CURSOR_MISMATCH

    tampered = alice.get(
        "/api/library/search",
        params={"q": "nachtstrom", "cursor": cursor[:-1] + ("0" if cursor[-1] != "0" else "1")},
    )
    assert tampered.status_code == 422
    assert tampered.json()["detail"] == LIBRARY_CURSOR_INVALID

    garbage = alice.get(
        "/api/library/search",
        params={"q": "nachtstrom", "cursor": "not-a-cursor"},
    )
    assert garbage.status_code == 422
    assert garbage.json()["detail"] == LIBRARY_CURSOR_INVALID


def test_like_metacharacters_are_literal(alice: TestClient) -> None:
    resp = alice.get("/api/library/search", params={"q": "100%"})
    ids = [_hit_id(i) for i in resp.json()["items"]]
    assert ids == ["percent"]
    wildcard = alice.get("/api/library/search", params={"q": "100_"})
    assert wildcard.json()["items"] == []


def test_list_albums_q_and_sort(alice: TestClient) -> None:
    resp = alice.get(
        "/api/albums",
        params={"q": "nacht", "sort": LIBRARY_SORT_TITLE, "limit": 50},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_more"] is False
    assert data["total"] == 1
    assert data["items"][0]["id"] == "nachtstrom"

    empty = alice.get("/api/albums", params={"q": "   "})
    assert empty.status_code == 422
    assert empty.json()["detail"] == LIBRARY_QUERY_REQUIRED


def test_list_songs_q_and_sort(alice: TestClient) -> None:
    resp = alice.get(
        "/api/songs",
        params={"q": "remix", "sort": LIBRARY_SORT_NEWEST},
    )
    data = resp.json()
    assert data["total"] == 1
    assert data["has_more"] is False
    assert data["items"][0]["id"] == "song-nacht"
    assert data["items"][0]["album_title"] == "Nachtstrom"


def test_list_songs_without_album_id_excludes_archived_album_songs(tmp_path: Path) -> None:
    """GET /api/songs browse (no album_id) must hide songs of archived albums --
    both from items and from total/has_more, since count_songs and list_songs
    can drift independently if only one is filtered (#223 review finding)."""
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="visibility-live", title="Visibility Live",
            owner=USER_A, created_at=_ts(1),
        )
        _add_song(
            session, song_id="visibility-live-song", title="Visibility Case Song",
            album_id="visibility-live", created_at=_ts(2),
        )
        _add_album(
            session, album_id="visibility-archived", title="Visibility Archived",
            owner=USER_A, created_at=_ts(3), is_archived=True,
        )
        _add_song(
            session, song_id="visibility-archived-song", title="Visibility Case Song",
            album_id="visibility-archived", created_at=_ts(4),
        )
        session.commit()

    browse = client.get("/api/songs", params={"q": "Visibility Case Song"})
    data = browse.json()
    assert [s["id"] for s in data["items"]] == ["visibility-live-song"]
    assert data["total"] == 1
    assert data["has_more"] is False


def test_list_songs_with_album_id_shows_songs_of_an_archived_album(tmp_path: Path) -> None:
    """Direct-by-ID access (album_id set) must keep working for an archived
    album's songs -- AlbumDetailView depends on this (#223 review finding)."""
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="direct-archived", title="Direct Archived",
            owner=USER_A, created_at=_ts(1), is_archived=True,
        )
        _add_song(
            session, song_id="direct-archived-song", title="Direct Archived Song",
            album_id="direct-archived", created_at=_ts(2),
        )
        session.commit()

    scoped = client.get("/api/songs", params={"album_id": "direct-archived"})
    data = scoped.json()
    assert [s["id"] for s in data["items"]] == ["direct-archived-song"]
    assert data["total"] == 1


def test_list_albums_offset_pagination_stable_title_sort(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        for i in range(5):
            _add_album(
                session,
                album_id=f"alpha-{i}",
                title=f"Alpha {i}",
                owner=USER_A,
                created_at=_ts(i),
            )
        session.commit()

    first = client.get(
        "/api/albums",
        params={"q": "Alpha", "sort": LIBRARY_SORT_TITLE, "offset": 0, "limit": 2},
    ).json()
    second = client.get(
        "/api/albums",
        params={"q": "Alpha", "sort": LIBRARY_SORT_TITLE, "offset": 2, "limit": 2},
    ).json()
    third = client.get(
        "/api/albums",
        params={"q": "Alpha", "sort": LIBRARY_SORT_TITLE, "offset": 4, "limit": 2},
    ).json()
    ids = [a["id"] for a in first["items"] + second["items"] + third["items"]]
    assert ids == ["alpha-0", "alpha-1", "alpha-2", "alpha-3", "alpha-4"]
    assert first["has_more"] is True
    assert second["has_more"] is True
    assert third["has_more"] is False
    assert first["total"] == 5


def test_invalid_sort_is_rejected(alice: TestClient) -> None:
    assert alice.get("/api/albums", params={"sort": "popular"}).status_code == 422
    assert alice.get("/api/songs", params={"sort": "popular"}).status_code == 422
    assert alice.get(
        "/api/library/search", params={"q": "nacht", "sort": "popular"},
    ).status_code == 422


def test_oldest_sort_is_created_at_ascending(alice: TestClient) -> None:
    resp = alice.get(
        "/api/library/search",
        params={"q": "alice", "sort": LIBRARY_SORT_OLDEST},
    )
    ids = [_hit_id(i) for i in resp.json()["items"]]
    assert ids[0] == "alice-own"


def test_search_album_hit_includes_picked_count(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="picks-album", title="Picks Album",
            owner=USER_A, created_at=_ts(1),
        )
        _add_song(
            session, song_id="picks-picked", title="Picked Song",
            album_id="picks-album", created_at=_ts(2),
        )
        session.add(Generation(
            id="g-picked", song_id="picks-picked", generation_number=1,
            mp3_path=f"{USER_A}/g-picked.mp3", seed=1, is_picked=True,
        ))
        _add_song(
            session, song_id="picks-unpicked", title="Unpicked Song",
            album_id="picks-album", created_at=_ts(3),
        )
        session.commit()

    resp = client.get("/api/library/search", params={"q": "Picks Album"})
    assert resp.status_code == 200
    album_hit = next(
        item for item in resp.json()["items"]
        if item["type"] == LIBRARY_ITEM_ALBUM and item["album"]["id"] == "picks-album"
    )
    assert album_hit["album"]["picked_count"] == 1


def test_search_album_hit_excludes_archived_pick(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="archived-picks-album", title="Archived Picks Album",
            owner=USER_A, created_at=_ts(1),
        )
        _add_song(
            session, song_id="ap-song", title="Archived Pick Song",
            album_id="archived-picks-album", created_at=_ts(2),
        )
        session.add(Generation(
            id="g-archived-pick", song_id="ap-song", generation_number=1,
            mp3_path=f"{USER_A}/g-archived-pick.mp3", seed=1,
            is_picked=True, is_archived=True,
        ))
        session.commit()

    resp = client.get("/api/library/search", params={"q": "Archived Picks Album"})
    assert resp.status_code == 200
    album_hit = next(
        item for item in resp.json()["items"]
        if item["type"] == LIBRARY_ITEM_ALBUM and item["album"]["id"] == "archived-picks-album"
    )
    assert album_hit["album"]["picked_count"] == 0


def test_list_albums_excludes_archived_by_default(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="arch-hidden", title="Archived Album",
            owner=USER_A, created_at=_ts(1), is_archived=True,
        )
        session.commit()

    resp = client.get("/api/albums")
    ids = [a["id"] for a in resp.json()["items"]]
    assert "arch-hidden" not in ids


def test_list_albums_archived_filter_shows_only_archived(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="arch-visible", title="Archived Visible",
            owner=USER_A, created_at=_ts(1), is_archived=True,
        )
        session.commit()

    resp = client.get("/api/albums", params={"archived": "true"})
    ids = [a["id"] for a in resp.json()["items"]]
    assert ids == ["arch-visible"]
    assert "nachtstrom" not in ids


def test_search_excludes_archived_album(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="arch-search", title="Archived Search Album",
            owner=USER_A, created_at=_ts(1), is_archived=True,
        )
        session.commit()

    resp = client.get("/api/library/search", params={"q": "Archived Search Album"})
    assert resp.json()["items"] == []


def test_search_excludes_songs_of_archived_album(tmp_path: Path) -> None:
    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="arch-song-parent", title="Archived Song Parent",
            owner=USER_A, created_at=_ts(1), is_archived=True,
        )
        _add_song(
            session, song_id="arch-song", title="Archived Child Song",
            album_id="arch-song-parent", created_at=_ts(2),
        )
        session.commit()

    resp = client.get("/api/library/search", params={"q": "Archived Child Song"})
    assert resp.json()["items"] == []


def test_pool_queue_excludes_generations_from_archived_albums(
    tmp_path: Path, monkeypatch,
) -> None:
    import songmaker_cli.queue_streams as queue_streams

    monkeypatch.setattr(queue_streams, "probe_audio_duration", lambda _path: 10.0)

    client, factory = _make_client(tmp_path, USER_A)
    with factory() as session:
        _add_album(
            session, album_id="pool-live", title="Pool Live",
            owner=USER_A, created_at=_ts(1),
        )
        _add_song(
            session, song_id="pool-live-song", title="Live Song",
            album_id="pool-live", created_at=_ts(2),
        )
        session.add(Generation(
            id="g-pool-live", song_id="pool-live-song", generation_number=1,
            mp3_path=f"{USER_A}/g-pool-live.mp3", seed=1,
        ))
        _add_album(
            session, album_id="pool-archived", title="Pool Archived",
            owner=USER_A, created_at=_ts(3), is_archived=True,
        )
        _add_song(
            session, song_id="pool-archived-song", title="Archived Song",
            album_id="pool-archived", created_at=_ts(4),
        )
        session.add(Generation(
            id="g-pool-archived", song_id="pool-archived-song", generation_number=1,
            mp3_path=f"{USER_A}/g-pool-archived.mp3", seed=2,
        ))
        session.commit()

    audio_dir = tmp_path / "audio" / USER_A
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "g-pool-live.mp3").write_bytes(b"source")

    resp = client.get("/api/library/pool-queue", params={"pool": "all"})
    assert resp.status_code == 200
    take_ids = [t["generation_id"] for t in resp.json()["takes"]]
    assert take_ids == ["g-pool-live"]

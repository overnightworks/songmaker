"""A reference left without links by a detaching request is stamped unused after its commit."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from support.failing_reference_stamp import install_failing_stamp
from support.reference_rows import a_reference
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.db.models import Album, Generation, ReferenceRecording, Song, User, Version
from songmaker_cli.db.queries.reference_recordings import linked_reference_ids, mark_newly_unused
from songmaker_cli.reference_audio import commit_unused_stamps
from songmaker_cli.timestamps import utcnow

OWNER = "owner"
EARLIER = utcnow() - timedelta(days=3)


def _take_row(take_id: str, number: int, reference_id: str | None) -> Generation:
    return Generation(
        id=take_id, song_id="song", version_id="version", generation_number=number,
        mp3_path=f"{OWNER}/{take_id}.mp3", reference_recording_id=reference_id,
    )


def _seed_stamp_world(
    session, takes: dict[str, str | None], version_reference: str | None,
) -> None:
    session.add(User(id=OWNER, username=OWNER))
    session.flush()
    session.add(Album(id="album", title="A", artist="A", created_by=OWNER))
    session.flush()
    session.add(Song(id="song", title="S", album_id="album", track_number=1, slug="s"))
    for name in ("r1", "r2"):
        a_reference(session, OWNER, name=f"{name}.wav", reference_id=name)
    session.flush()
    session.add(Version(
        id="version", song_id="song", version_number=1, lyrics="la", prompt="p",
        reference_recording_id=version_reference,
    ))
    session.flush()
    session.add_all(
        _take_row(name, number, ref) for number, (name, ref) in enumerate(takes.items(), 1)
    )


def _world(
    tmp_path: Path,
    pg_factory,
    takes: dict[str, str | None],
    version_reference: str | None = None,
):
    ctx = make_router_ctx(
        tmp_path,
        db=pg_factory,
        seed_db=lambda s: _seed_stamp_world(s, takes, version_reference),
    )
    (tmp_path / "audio" / OWNER).mkdir(parents=True, exist_ok=True)
    for name in takes:
        (tmp_path / "audio" / OWNER / f"{name}.mp3").write_bytes(b"ID3")
    app = make_router_app(ctx, user=make_authenticated_user(OWNER, username=OWNER))
    return web_client(app), ctx


def _delete_through_route(client: TestClient, route: str, take_ids: list[str]):
    if route == "single":
        return client.delete(f"/api/generations/{take_ids[0]}")
    return client.post("/api/generations/bulk-delete", json={"generation_ids": take_ids})


def _add_linked_song(ctx, song_id: str, album_id: str, *, links: dict[str, str]) -> None:
    """A further song, in a new album when asked, whose version and takes link the references.

    ``links`` maps an id to the reference it links; ids starting with ``take`` are takes.
    """
    with ctx.db() as session:
        if session.get(Album, album_id) is None:
            session.add(Album(id=album_id, title=album_id, artist="A", created_by=OWNER))
            session.flush()
        session.add(
            Song(id=song_id, title=song_id, album_id=album_id, track_number=1, slug=song_id),
        )
        session.flush()
        for number, (row_id, reference) in enumerate(links.items(), 1):
            if row_id.startswith("take"):
                session.add(Generation(
                    id=row_id, song_id=song_id, version_id=f"{song_id}-v1",
                    generation_number=number, mp3_path=f"{OWNER}/{row_id}.mp3",
                    reference_recording_id=reference,
                ))
            else:
                session.add(Version(
                    id=row_id, song_id=song_id, version_number=number, lyrics="la", prompt="p",
                    reference_recording_id=reference,
                ))
            session.flush()
        session.commit()


def _stamps(ctx) -> dict[str, datetime | None]:
    with ctx.db() as session:
        return {row.id: row.unused_since for row in session.query(ReferenceRecording)}


ROUTES = ["single", "bulk"]


@pytest.mark.parametrize("route", ROUTES)
def test_deleting_the_only_take_that_links_a_reference_stamps_it(tmp_path, route, pg_factory):
    client, ctx = _world(tmp_path, pg_factory, {"ta": "r1", "tb": None})
    assert _delete_through_route(client, route, ["ta"]).status_code == 200
    stamps = _stamps(ctx)
    assert stamps["r1"] is not None
    assert stamps["r2"] is None


@pytest.mark.parametrize(
    ("takes", "stamped"),
    [
        ({"ta": "r1", "tb": "r1"}, {"r1"}),
        ({"ta": "r1", "tb": "r2"}, {"r1", "r2"}),
    ],
)
def test_a_bulk_delete_stamps_each_reference_its_takes_shared(tmp_path, takes, stamped, pg_factory):
    client, ctx = _world(tmp_path, pg_factory, takes)
    assert _delete_through_route(client, "bulk", ["ta", "tb"]).status_code == 200
    assert {ref for ref, stamp in _stamps(ctx).items() if stamp is not None} == stamped


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("link", ["version", "other_take"])
def test_a_reference_another_version_or_take_still_links_keeps_no_stamp(
    tmp_path, route, link, pg_factory,
):
    takes = {"ta": "r1", "tb": "r1"} if link == "other_take" else {"ta": "r1"}
    client, ctx = _world(tmp_path, pg_factory, takes, "r1" if link == "version" else None)
    assert _delete_through_route(client, route, ["ta"]).status_code == 200
    assert _stamps(ctx)["r1"] is None


@pytest.mark.parametrize("route", ROUTES)
def test_a_failing_stamp_leaves_the_answer_and_the_unlink_and_logs_one_counts_only_error(
    tmp_path, pg_factory, caplog, request, route,
):
    client, ctx = _world(tmp_path, pg_factory, {"ta": "r1"})
    install_failing_stamp(pg_factory, request)
    with caplog.at_level(logging.ERROR):
        response = _delete_through_route(client, route, ["ta"])
    assert response.status_code == 200
    assert not (tmp_path / "audio" / OWNER / "ta.mp3").exists()
    assert _stamps(ctx)["r1"] is None
    [record] = [r for r in caplog.records if r.levelno == logging.ERROR]
    message = record.getMessage()
    assert "IntegrityError" in message
    assert "secret" not in message
    assert "ta.mp3" not in message
    assert record.exc_info is None


def _owner_ctx(tmp_path, pg_factory, *, kept=False, stamp=None):
    def seed(session):
        session.add(User(id=OWNER, username=OWNER))
        session.flush()
        a_reference(
            session, OWNER, name="r1.wav", reference_id="r1", is_kept=kept, unused_since=stamp,
        )
    return make_router_ctx(tmp_path, db=pg_factory, seed_db=seed)


@pytest.mark.parametrize(
    ("kept", "stamp", "expected"),
    [(True, None, 0), (False, EARLIER, 0), (False, None, 1)],
    ids=["kept_gets_none", "stamped_keeps_its_stamp", "unstamped_unkept_is_stamped"],
)
def test_the_stamp_skips_kept_rows_and_never_overwrites(
    tmp_path, kept, stamp, expected, pg_factory,
):
    ctx = _owner_ctx(tmp_path, pg_factory, kept=kept, stamp=stamp)
    before = _stamps(ctx)["r1"]
    with ctx.db() as session:
        assert mark_newly_unused(session, {"r1"}) == expected
        session.commit()
    after = _stamps(ctx)["r1"]
    assert (after is not None) == (kept is False)
    if before is not None:
        assert after == before


def test_unknown_ids_and_an_empty_set_stamp_nothing(tmp_path, pg_factory):
    ctx = _owner_ctx(tmp_path, pg_factory)
    with ctx.db() as session:
        assert mark_newly_unused(session, {"missing"}) == 0
        assert mark_newly_unused(session, set()) == 0
    assert _stamps(ctx)["r1"] is None


def test_an_empty_candidate_set_sends_no_statement(tmp_path, pg_factory):
    ctx = _owner_ctx(tmp_path, pg_factory)
    statements: list[str] = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    with ctx.db() as session:
        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            commit_unused_stamps(session, set())
            mark_newly_unused(session, set())
        finally:
            event.remove(engine, "before_cursor_execute", record)
    assert statements == []


@dataclass(frozen=True)
class SongRequest:
    takes: dict[str, str | None]
    version_reference: str | None
    send: Callable[[TestClient], object]
    stamped: set[str]
    removed_file: str | None
    answered_reference: str | None = None


def _put_song(**body):
    return lambda client: client.put("/api/songs/song", json=body)


def _delete_version(*, with_takes: bool):
    return lambda client: client.delete(
        f"/api/versions/version?delete_generations={str(with_takes).lower()}",
    )


SONG_REQUESTS = {
    "in_place_edit": SongRequest(
        {}, "r1", _put_song(reference_recording_id="r2"), {"r1"}, None, "r2",
    ),
    "version_delete_with_takes": SongRequest(
        {"ta": "r1"}, "r2", _delete_version(with_takes=True), {"r1", "r2"}, "ta.mp3",
    ),
    "version_delete_without_takes": SongRequest(
        {}, "r1", _delete_version(with_takes=False), {"r1"}, None,
    ),
}
REQUEST_IDS = list(SONG_REQUESTS)


def _stamped_ids(ctx) -> set[str]:
    return {reference for reference, stamp in _stamps(ctx).items() if stamp is not None}


@pytest.mark.parametrize("request_id", REQUEST_IDS)
def test_a_request_that_leaves_a_reference_without_links_stamps_it_after_its_commit(
    tmp_path, request_id, pg_factory,
):
    scenario = SONG_REQUESTS[request_id]
    client, ctx = _world(tmp_path, pg_factory, scenario.takes, scenario.version_reference)
    assert scenario.send(client).status_code == 200
    assert _stamped_ids(ctx) == scenario.stamped


def test_saving_the_changed_reference_as_a_new_version_stamps_nothing(tmp_path, pg_factory):
    client, ctx = _world(tmp_path, pg_factory, {}, "r1")
    response = _put_song(reference_recording_id="r2", new_version=True)(client)
    assert response.status_code == 200
    assert _stamped_ids(ctx) == set()


def test_an_in_place_edit_keeps_the_stamp_off_a_reference_a_take_of_the_same_song_links(
    tmp_path, pg_factory,
):
    client, ctx = _world(tmp_path, pg_factory, {"ta": "r1"}, "r1")
    assert _put_song(reference_recording_id="r2")(client).status_code == 200
    assert _stamped_ids(ctx) == set()


def test_an_edit_that_leaves_the_reference_unset_stamps_nothing(tmp_path, pg_factory):
    client, ctx = _world(tmp_path, pg_factory, {}, "r1")
    assert _put_song(lyrics="new words")(client).status_code == 200
    assert _stamped_ids(ctx) == set()


def test_deleting_a_version_without_its_takes_stamps_its_own_reference_only_if_no_take_links_it(
    tmp_path, pg_factory,
):
    client, ctx = _world(tmp_path, pg_factory, {"ta": "r1"}, "r1")
    assert _delete_version(with_takes=False)(client).status_code == 200
    assert _stamped_ids(ctx) == set()


@pytest.mark.parametrize("request_id", REQUEST_IDS)
def test_a_reference_another_song_still_links_keeps_no_stamp_on_every_request(
    tmp_path, request_id, pg_factory,
):
    scenario = SONG_REQUESTS[request_id]
    client, ctx = _world(tmp_path, pg_factory, scenario.takes, scenario.version_reference)
    _add_linked_song(
        ctx, "keeper", "keeper-album",
        links={f"keeper-{ref}": ref for ref in sorted(scenario.stamped)},
    )
    assert scenario.send(client).status_code == 200
    assert _stamped_ids(ctx) == set()


@pytest.mark.parametrize("request_id", REQUEST_IDS)
def test_a_failing_stamp_keeps_the_answer_and_the_unlink_and_logs_a_counts_only_error_per_request(
    tmp_path, pg_factory, caplog, request, request_id,
):
    scenario = SONG_REQUESTS[request_id]
    client, ctx = _world(tmp_path, pg_factory, scenario.takes, scenario.version_reference)
    install_failing_stamp(pg_factory, request)
    with caplog.at_level(logging.ERROR):
        response = scenario.send(client)
    assert response.status_code == 200
    if scenario.answered_reference:
        assert response.json()["reference"]["id"] == scenario.answered_reference
    if scenario.removed_file:
        assert not (tmp_path / "audio" / OWNER / scenario.removed_file).exists()
    assert _stamped_ids(ctx) == set()
    [record] = [r for r in caplog.records if r.levelno == logging.ERROR]
    message = record.getMessage()
    assert "IntegrityError" in message
    assert "secret" not in message
    assert record.exc_info is None


def test_linked_reference_ids_unions_versions_and_takes_of_the_given_songs_only(
    tmp_path, pg_factory,
):
    _, ctx = _world(tmp_path, pg_factory, {"ta": "r1", "tb": None})
    _add_linked_song(ctx, "other", "album2", links={"other-v1": "r2"})
    with ctx.db() as session:
        session.get(Generation, "ta").is_archived = True
        assert linked_reference_ids(session, ["song"]) == {"r1"}
        assert linked_reference_ids(session, ["other"]) == {"r2"}
        assert linked_reference_ids(session, ["song", "other"]) == {"r1", "r2"}


def test_linked_reference_ids_answers_an_empty_input_without_a_statement(tmp_path, pg_factory):
    ctx = _owner_ctx(tmp_path, pg_factory)
    statements: list[str] = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    with ctx.db() as session:
        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            assert linked_reference_ids(session, []) == set()
        finally:
            event.remove(engine, "before_cursor_execute", record)
    assert statements == []

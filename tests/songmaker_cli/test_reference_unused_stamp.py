"""A reference left without links by a take delete is stamped unused after the commit."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.constants import REFERENCE_AUDIO_DIR
from songmaker_cli.db.models import Album, Generation, ReferenceRecording, Song, User, Version
from songmaker_cli.db.queries.reference_recordings import mark_newly_unused
from songmaker_cli.reference_audio import commit_unused_stamps
from songmaker_cli.timestamps import utcnow

OWNER = "owner"
EARLIER = utcnow() - timedelta(days=3)


def _reference_row(reference_id: str, *, is_kept: bool = False, stamp: datetime | None = None):
    return ReferenceRecording(
        id=reference_id, user_id=OWNER,
        storage_path=f"{OWNER}/{REFERENCE_AUDIO_DIR}/{reference_id}.wav",
        original_filename=f"{reference_id}.wav", size_bytes=4, is_kept=is_kept, unused_since=stamp,
    )


def _take_row(take_id: str, number: int, reference_id: str | None) -> Generation:
    return Generation(
        id=take_id, song_id="song", version_id="version", generation_number=number,
        mp3_path=f"{OWNER}/{take_id}.mp3", reference_recording_id=reference_id,
    )


FAIL_STAMP_TRIGGER = (
    "CREATE TRIGGER fail_stamp BEFORE UPDATE OF unused_since ON reference_recordings "
    "BEGIN SELECT RAISE(ABORT, 'secret.wav'); END"
)


def _seed_stamp_world(
    session, takes: dict[str, str | None], version_reference: str | None, *, failing_stamp=False,
) -> None:
    session.add(User(id=OWNER, username=OWNER))
    session.flush()
    session.add(Album(id="album", title="A", artist="A", created_by=OWNER))
    session.flush()
    session.add(Song(id="song", title="S", album_id="album", track_number=1, slug="s"))
    session.add_all([_reference_row("r1"), _reference_row("r2")])
    session.flush()
    session.add(Version(
        id="version", song_id="song", version_number=1, lyrics="la", prompt="p",
        reference_recording_id=version_reference,
    ))
    session.flush()
    session.add_all(
        _take_row(name, number, ref) for number, (name, ref) in enumerate(takes.items(), 1)
    )
    if failing_stamp:
        session.execute(text(FAIL_STAMP_TRIGGER))


def _world(
    tmp_path: Path,
    takes: dict[str, str | None],
    version_reference: str | None = None,
    *,
    failing_stamp: bool = False,
):
    ctx = make_router_ctx(
        tmp_path,
        seed_db=lambda s: _seed_stamp_world(
            s, takes, version_reference, failing_stamp=failing_stamp,
        ),
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


def _stamps(ctx) -> dict[str, datetime | None]:
    with ctx.db() as session:
        return {row.id: row.unused_since for row in session.query(ReferenceRecording)}


ROUTES = ["single", "bulk"]


@pytest.mark.parametrize("route", ROUTES)
def test_deleting_the_only_take_that_links_a_reference_stamps_it(tmp_path, route):
    client, ctx = _world(tmp_path, {"ta": "r1", "tb": None})
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
def test_a_bulk_delete_stamps_each_reference_its_takes_shared(tmp_path, takes, stamped):
    client, ctx = _world(tmp_path, takes)
    assert _delete_through_route(client, "bulk", ["ta", "tb"]).status_code == 200
    assert {ref for ref, stamp in _stamps(ctx).items() if stamp is not None} == stamped


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("link", ["version", "other_take"])
def test_a_reference_another_version_or_take_still_links_keeps_no_stamp(tmp_path, route, link):
    takes = {"ta": "r1", "tb": "r1"} if link == "other_take" else {"ta": "r1"}
    client, ctx = _world(tmp_path, takes, "r1" if link == "version" else None)
    assert _delete_through_route(client, route, ["ta"]).status_code == 200
    assert _stamps(ctx)["r1"] is None


@pytest.mark.parametrize("route", ROUTES)
def test_a_failing_stamp_leaves_the_answer_and_the_unlink_and_logs_one_counts_only_error(
    tmp_path, caplog, route,
):
    client, ctx = _world(tmp_path, {"ta": "r1"}, failing_stamp=True)
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


def _owner_ctx(tmp_path, *, kept=False, stamp=None):
    def seed(session):
        session.add(User(id=OWNER, username=OWNER))
        session.flush()
        session.add(_reference_row("r1", is_kept=kept, stamp=stamp))
    return make_router_ctx(tmp_path, seed_db=seed)


@pytest.mark.parametrize(
    ("kept", "stamp", "expected"),
    [(True, None, 0), (False, EARLIER, 0), (False, None, 1)],
    ids=["kept_gets_none", "stamped_keeps_its_stamp", "unstamped_unkept_is_stamped"],
)
def test_the_stamp_skips_kept_rows_and_never_overwrites(tmp_path, kept, stamp, expected):
    ctx = _owner_ctx(tmp_path, kept=kept, stamp=stamp)
    before = _stamps(ctx)["r1"]
    with ctx.db() as session:
        assert mark_newly_unused(session, {"r1"}) == expected
        session.commit()
    after = _stamps(ctx)["r1"]
    assert (after is not None) == (kept is False)
    if before is not None:
        assert after == before


def test_unknown_ids_and_an_empty_set_stamp_nothing(tmp_path):
    ctx = _owner_ctx(tmp_path)
    with ctx.db() as session:
        assert mark_newly_unused(session, {"missing"}) == 0
        assert mark_newly_unused(session, set()) == 0
    assert _stamps(ctx)["r1"] is None


def test_an_empty_candidate_set_sends_no_statement(tmp_path):
    ctx = _owner_ctx(tmp_path)
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

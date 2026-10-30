"""Automatic retention, a keep, a pick and the manual delete order themselves on the take's row."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from httpx import Response
from postgres_lock_harness import CommitPause, race, wrote_to_tables
from support.web_app import make_test_app, seed_session, seed_user

from songmaker_cli.db.models import Album, Generation, Song, Version

ADMIN = "admin-1"
RETENTION_RUN = "/api/admin/generation-retention/run"
LONG_AGO = timedelta(days=90)
ARCHIVED_LONG_AGO = timedelta(days=60)
NOT_FOUND = {"detail": "Not Found"}


def _take(name: str, number: int, *, archived: bool, old: bool) -> Generation:
    now = datetime.now(timezone.utc)
    return Generation(
        id=name, song_id="song-1", version_id="version-1", generation_number=number,
        mp3_path=f"album-1/{name}.mp3",
        is_archived=archived, archived_at=now - ARCHIVED_LONG_AGO if archived else None,
        created_at=now - LONG_AGO if old else now,
    )


class _World:
    """The real routes on PostgreSQL: an admin who owns one song with only the named takes."""

    def __init__(self, pg_factory, tmp_path: Path, takes: dict[str, dict[str, bool]]) -> None:
        self.pg_factory = pg_factory
        self.audio_dir = tmp_path / "audio"
        self.files = {name: self.audio_dir / "album-1" / f"{name}.mp3" for name in takes}

        def seed(session) -> None:
            seed_user(session, "admin", "admin", user_id=ADMIN)
            session.flush()
            session.add(Album(id="album-1", title="A", artist="A", created_by=ADMIN))
            session.add(Song(id="song-1", title="S", album_id="album-1", track_number=1))
            session.add(Version(id="version-1", song_id="song-1", version_number=1,
                                lyrics="", prompt=""))
            session.flush()
            session.add_all(
                _take(name, number, **flags)
                for number, (name, flags) in enumerate(takes.items(), start=1)
            )

        self.client, _ = make_test_app(tmp_path, factory=pg_factory, seed_db=seed)
        seed_session(self.client, "admin")
        for path in self.files.values():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"mp3")

    def retention(self) -> Callable[[], Response]:
        return lambda: self.client.post(RETENTION_RUN)

    def mark(self, route: str, take: str) -> Callable[[], Response]:
        return lambda: self.client.post(f"/api/generations/{take}/{route}")

    def delete(self, take: str) -> Callable[[], Response]:
        return lambda: self.client.delete(f"/api/generations/{take}")

    def state(self, take: str) -> dict[str, Any] | None:
        with self.pg_factory() as session:
            gen = session.get(Generation, take)
            if gen is None:
                return None
            return {"archived": gen.is_archived, "kept": gen.is_kept, "picked": gen.is_picked}


def _holding_a_generation_write() -> CommitPause:
    return CommitPause(lambda session: wrote_to_tables(session, "generations"))


@pytest.mark.parametrize("route", ["keep", "pick"])
def test_stage_one_leaves_a_take_that_a_keep_or_pick_commits_first(
    pg_factory, tmp_path, route,
) -> None:
    world = _World(pg_factory, tmp_path, {"x": {"archived": False, "old": True}})
    answers = race(
        pg_factory, world.mark(route, "x"), world.retention(), _holding_a_generation_write(),
    )
    assert answers["first"].status_code == 200
    assert answers["second"].status_code == 200
    assert answers["second"].json()["archived_ids"] == []
    assert world.state("x") == {
        "archived": False, "kept": route == "keep", "picked": route == "pick",
    }


@pytest.mark.parametrize("route", ["keep", "pick"])
def test_stage_two_leaves_an_archived_take_that_a_keep_or_pick_commits_first(
    pg_factory, tmp_path, route,
) -> None:
    world = _World(pg_factory, tmp_path, {"x": {"archived": True, "old": True}})
    answers = race(
        pg_factory, world.mark(route, "x"), world.retention(), _holding_a_generation_write(),
    )
    assert answers["first"].status_code == 200
    assert answers["second"].status_code == 200
    assert answers["second"].json()["deleted_ids"] == []
    assert world.state("x") is not None
    assert world.files["x"].exists()


def test_a_pick_of_a_sibling_waits_for_the_archive_of_another_take_and_both_finish(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path, {
        "a": {"archived": False, "old": True}, "b": {"archived": False, "old": False},
    })
    answers = race(
        pg_factory, world.retention(), world.mark("pick", "b"), _holding_a_generation_write(),
    )
    assert answers["first"].json()["archived_ids"] == ["a"]
    assert answers["second"].status_code == 200
    assert world.state("a") == {"archived": True, "kept": False, "picked": False}
    assert world.state("b") == {"archived": False, "kept": False, "picked": True}


def test_a_manual_delete_waits_for_the_final_deletion_of_the_take_and_answers_not_found(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path, {"x": {"archived": True, "old": True}})
    answers = race(
        pg_factory, world.retention(), world.delete("x"), _holding_a_generation_write(),
    )
    assert answers["first"].json()["deleted_ids"] == ["x"]
    assert answers["second"].status_code == 404
    assert answers["second"].json() == NOT_FOUND
    assert world.state("x") is None
    assert not world.files["x"].exists()


def test_the_final_deletion_waits_for_a_manual_delete_of_the_take_and_leaves_it_out_of_its_report(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path, {"x": {"archived": True, "old": True}})
    answers = race(
        pg_factory, world.delete("x"), world.retention(), _holding_a_generation_write(),
    )
    assert answers["first"].status_code == 200
    assert answers["second"].status_code == 200
    assert answers["second"].json()["deleted_ids"] == []
    assert world.state("x") is None

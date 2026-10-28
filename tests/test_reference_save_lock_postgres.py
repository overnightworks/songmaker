"""An explicit version save naming a reference validates and commits under the owner lock."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import make_test_app, seed_session
from httpx import Response
from postgres_lock_harness import (
    WAIT_SECONDS,
    CommitPause,
    in_thread,
    race,
    stop_workers,
)

from songmaker_cli.constants import REFERENCE_AUDIO_DIR
from songmaker_cli.db.models import Album, Song, User, Version
from songmaker_cli.db.queries.songs import create_song
from songmaker_cli.reference_audio import _lock_reference_owner

OWNER = "u1"
REFERENCE = f"{OWNER}/{REFERENCE_AUDIO_DIR}/F.wav"
NOT_FOUND = {"detail": "Not Found"}


def _seed(session) -> None:
    session.add(User(id=OWNER, username="owner"))
    session.flush()
    session.add(Album(id="album-a", title="A", artist="A", created_by=OWNER))
    session.flush()
    create_song(session, "Existing", "album-a", "existing", created_by=OWNER)


def _attached_references(session) -> list[str]:
    """What a sweep holding the owner lock reads as attached."""
    return sorted(
        version.generation_params["reference_audio_path"]
        for version in session.query(Version)
        if (version.generation_params or {}).get("reference_audio_path")
    )


class _World:
    """The real routes on PostgreSQL, a seeded owner with one song and one reference file."""

    def __init__(self, pg_factory, tmp_path: Path) -> None:
        self.pg_factory = pg_factory
        self.client, _ = make_test_app(tmp_path, factory=pg_factory, seed_db=_seed)
        seed_session(self.client, "owner")
        self.reference_file = tmp_path / "audio" / REFERENCE
        self.reference_file.parent.mkdir(parents=True)
        self.reference_file.write_bytes(b"RIFF")
        with pg_factory() as session:
            self.song_id = session.query(Song).filter_by(slug="existing").one().id

    def save(self, route: str, reference: str | None) -> Response:
        params = {"reference_audio_path": reference} if reference else {}
        if route == "create":
            return self.client.post("/api/songs", json={
                "title": "Fresh", "album_id": "album-a", "generation_params": params,
            })
        return self.client.put(f"/api/songs/{self.song_id}", json={"generation_params": params})

    def attached(self) -> list[str]:
        with self.pg_factory() as session:
            return _attached_references(session)

    def titles(self) -> list[str]:
        with self.pg_factory() as session:
            return sorted(title for (title,) in session.query(Song.title))

    def holder(
        self, pause: CommitPause | None, *, delete_reference: bool,
    ) -> Callable[[], list[str]]:
        """A sweep stand-in: takes the owner lock, reads the attached set, may delete, commits."""
        def run() -> list[str]:
            with self.pg_factory() as session:
                _lock_reference_owner(session, OWNER)
                attached = _attached_references(session)
                if delete_reference:
                    self.reference_file.unlink()
                if pause is not None:
                    pause.hold(session)
                session.commit()
                return attached

        return run


@pytest.mark.parametrize("route", ["create", "update"])
def test_a_save_waits_for_the_owner_lock_and_then_finds_the_deleted_reference_gone(
    pg_factory, tmp_path, route,
) -> None:
    world = _World(pg_factory, tmp_path)
    holder_pause = CommitPause(lambda _session: False)
    answers = race(
        pg_factory,
        world.holder(holder_pause, delete_reference=True),
        lambda: world.save(route, REFERENCE),
        holder_pause,
    )
    assert answers["first"] == []
    assert answers["second"].status_code == 404
    assert answers["second"].json() == NOT_FOUND
    assert world.attached() == []
    assert world.titles() == ["Existing"]


@pytest.mark.parametrize("route", ["create", "update"])
def test_a_sweep_waits_for_a_save_that_names_the_reference_and_then_sees_it_attached(
    pg_factory, tmp_path, route,
) -> None:
    world = _World(pg_factory, tmp_path)
    answers = race(
        pg_factory,
        lambda: world.save(route, REFERENCE),
        world.holder(None, delete_reference=False),
    )
    assert answers["first"].status_code == 200
    assert answers["second"] == [REFERENCE]
    assert world.attached() == [REFERENCE]


@pytest.mark.parametrize("route", ["create", "update"])
def test_a_save_that_names_no_reference_does_not_wait_for_the_owner_lock(
    pg_factory, tmp_path, route,
) -> None:
    world = _World(pg_factory, tmp_path)
    answers: dict = {}
    holder_pause = CommitPause()
    holder = in_thread(answers, "holder", world.holder(holder_pause, delete_reference=False))
    save = in_thread(answers, "save", lambda: world.save(route, None))
    try:
        holder.start()
        assert holder_pause.reached.wait(WAIT_SECONDS), "The holder never paused"
        save.start()
        save.join(WAIT_SECONDS)
        assert "save" in answers, "The save waited for the owner lock"
    finally:
        holder_pause.release.set()
        stuck = stop_workers(pg_factory, (holder, save), (holder_pause.backend_pid,))
    assert not stuck
    assert answers["save"].status_code == 200

"""The expired purge locks its songs and takes, and leaves a song with a running job for later."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from support.postgres_lock_harness import StatementPause, race
from support.web_app import make_test_app, seed_session, seed_user

from acestep_engine.models import AceStepConfig
from songmaker_cli import cleanup
from songmaker_cli.cleanup import run_cleanup_expired
from songmaker_cli.constants import JobStatus, JobType
from songmaker_cli.db.models import (
    Album,
    Generation,
    Job,
    Rating,
    Score,
    Song,
    Version,
)
from songmaker_cli.jobs import _persist_generation_row
from songmaker_cli.jobs.generation import GenerationContext
from songmaker_cli.parser import AlbumMeta, SongMeta

OWNER = "owner-1"
RETENTION_RUN = "/api/admin/generation-retention/run"
TRASHED_LONG_AGO = timedelta(days=400)
ARCHIVED_LONG_AGO = timedelta(days=400)
OLD_TAKE = "old-take"


def _statement_locking(table: str, clause: str) -> Callable[[str], bool]:
    return lambda sql: f"FROM {table}" in sql and clause in sql and "NO KEY" not in sql


def _held_after_song_lock() -> StatementPause:
    return StatementPause(_statement_locking("songs", "FOR UPDATE"))


def _held_after_take_lock() -> StatementPause:
    return StatementPause(_statement_locking("generations", "FOR UPDATE"))


def _held_after_persist_song_lock() -> StatementPause:
    return StatementPause(lambda sql: "FROM songs" in sql and "FOR NO KEY UPDATE" in sql)


class _World:
    """Songs in the trash on PostgreSQL, each with the named jobs, and the files they own."""

    def __init__(
        self,
        pg_factory,
        tmp_path: Path,
        *,
        songs: tuple[str, ...] = ("song-1",),
        song_albums: dict[str, str] | None = None,
        trashed_albums: tuple[str, ...] = (),
        scored_take: bool = True,
        jobs: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self.pg_factory = pg_factory
        self.audio_dir = tmp_path / "audio"
        self.unlinked: list[str] = []
        trashed = datetime.now(timezone.utc) - TRASHED_LONG_AGO

        def seed(session) -> None:
            seed_user(session, "admin", "admin", user_id=OWNER)
            session.flush()
            album_of = {song_id: (song_albums or {}).get(song_id, "album-1") for song_id in songs}
            for album_id in sorted({*album_of.values(), *trashed_albums}):
                session.add(Album(
                    id=album_id, title=album_id, artist="A", created_by=OWNER,
                    deleted_at=trashed if album_id in trashed_albums else None,
                ))
            session.flush()
            for number, song_id in enumerate(songs, start=1):
                session.add(Song(
                    id=song_id, title=song_id, album_id=album_of[song_id], slug=song_id,
                    track_number=number, deleted_at=trashed,
                ))
                session.flush()
                session.add(Version(
                    id=f"version-{song_id}", song_id=song_id, version_number=1,
                    lyrics="", prompt="",
                ))
            session.flush()
            if scored_take:
                self._add_old_take(session, songs[0])
            for job_id, columns in (jobs or {}).items():
                session.add(Job(id=job_id, user_id=OWNER, **columns))

        self.client, _ = make_test_app(tmp_path, factory=pg_factory, seed_db=seed)
        seed_session(self.client, "admin")
        self.write_files(OLD_TAKE)

    @staticmethod
    def _add_old_take(session, song_id: str) -> None:
        session.add(Generation(
            id=OLD_TAKE, song_id=song_id, version_id=f"version-{song_id}", generation_number=1,
            mp3_path=f"{OWNER}/{OLD_TAKE}.mp3", wav_path=f"{OWNER}/{OLD_TAKE}.wav",
            is_archived=True, archived_at=datetime.now(timezone.utc) - ARCHIVED_LONG_AGO,
        ))
        session.flush()
        session.add(Score(generation_id=OLD_TAKE, scorer="s", value={"v": 1}))
        session.add(Rating(generation_id=OLD_TAKE, rating=4.0))

    def write_files(self, take: str) -> None:
        for suffix in (".mp3", ".wav"):
            path = self.audio_dir / OWNER / f"{take}{suffix}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"audio")

    def record_unlinks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real = cleanup.cleanup_generation_files

        def record(audio_dir, paths) -> None:
            self.unlinked.extend(paths)
            real(audio_dir, paths)

        monkeypatch.setattr(cleanup, "cleanup_generation_files", record)

    def purge(self) -> Callable[[], tuple[int, int]]:
        return lambda: run_cleanup_expired(self.pg_factory, self.audio_dir)

    def retention(self):
        return lambda: self.client.post(RETENTION_RUN)

    def persist(self, take: str, job_id: str, song_id: str = "song-1"):
        self.write_files(take)
        context = GenerationContext(
            song_id=song_id, version_id=f"version-{song_id}",
            meta=SongMeta(title="S", lyrics="la", prompt="p"),
            album_meta=AlbumMeta(title="A", artist="A"),
            ace_config=AceStepConfig(prompt="p", lyrics="la", audio_duration=0),
            audio_dir=self.audio_dir, user_id=OWNER, reference_recording_id=None,
            model_name="turbo",
        )
        return lambda: _persist_generation_row(
            db_factory=self.pg_factory, ctx=context, generation_id=take, seed=1,
            cot_caption="", cot_lyrics="", delivered_batch_size=None, job_id=job_id,
        )

    def finish_job(self, job_id: str) -> None:
        with self.pg_factory() as session:
            session.get(Job, job_id).status = JobStatus.COMPLETED
            session.commit()

    def song_ids(self) -> list[str]:
        with self.pg_factory() as session:
            return sorted(
                song_id for (song_id,) in session.query(Song.id).execution_options(
                    include_deleted=True,
                )
            )

    def take_ids(self) -> list[str]:
        with self.pg_factory() as session:
            return sorted(take_id for (take_id,) in session.query(Generation.id))

    def album_ids(self) -> list[str]:
        with self.pg_factory() as session:
            return sorted(
                album_id for (album_id,) in session.query(Album.id).execution_options(
                    include_deleted=True,
                )
            )

    def trash_album(self, album_id: str) -> None:
        with self.pg_factory() as session:
            session.query(Album).filter_by(id=album_id).one().deleted_at = (
                datetime.now(timezone.utc) - TRASHED_LONG_AGO
            )
            session.commit()

    def files_left(self, take: str) -> list[str]:
        return sorted(
            path.name for path in (self.audio_dir / OWNER).glob(f"{take}.*")
        )


def _running_generation(song_id: str = "song-1") -> dict[str, str]:
    return {"type": JobType.GENERATE, "status": JobStatus.RUNNING, "song_id": song_id}


def _queued_generation(song_id: str = "song-1") -> dict[str, str]:
    return {"type": JobType.GENERATE, "status": JobStatus.QUEUED, "song_id": song_id}


def _owned_paths(take: str) -> list[str]:
    return [f"{OWNER}/{take}.mp3", f"{OWNER}/{take}.wav"]


def test_a_purge_waits_for_retentions_delete_of_a_scored_take_and_unlinks_it_once(
    pg_factory, tmp_path, monkeypatch,
) -> None:
    world = _World(pg_factory, tmp_path)
    world.record_unlinks(monkeypatch)

    answers = race(pg_factory, world.retention(), world.purge(), _held_after_take_lock())

    assert answers["first"].json()["deleted_ids"] == [OLD_TAKE]
    assert answers["second"] == (0, 1)
    assert world.song_ids() == []
    assert world.unlinked == _owned_paths(OLD_TAKE)
    assert world.files_left(OLD_TAKE) == []


def test_retention_waits_for_a_purge_that_holds_its_take_and_leaves_the_unlink_to_the_purge(
    pg_factory, tmp_path, monkeypatch,
) -> None:
    world = _World(pg_factory, tmp_path)
    world.record_unlinks(monkeypatch)

    answers = race(pg_factory, world.purge(), world.retention(), _held_after_take_lock())

    assert answers["first"] == (0, 1)
    assert answers["second"].json()["deleted_ids"] == []
    assert world.unlinked == _owned_paths(OLD_TAKE)


def test_a_purge_defers_a_song_whose_persist_holds_its_job_and_saves_the_take(
    pg_factory, tmp_path, monkeypatch,
) -> None:
    world = _World(pg_factory, tmp_path, jobs={"job-new": _running_generation()})
    world.record_unlinks(monkeypatch)

    answers = race(
        pg_factory, world.persist("new-take", "job-new"), world.purge(),
        _held_after_persist_song_lock(),
    )

    assert answers["first"] is not None
    assert answers["second"] == (0, 0)
    assert world.take_ids() == sorted([OLD_TAKE, answers["first"]])
    assert world.unlinked == []

    world.finish_job("job-new")
    assert world.purge()() == (0, 1)
    assert world.song_ids() == []
    assert sorted(world.unlinked) == sorted(_owned_paths(OLD_TAKE) + _owned_paths("new-take"))


def test_a_persist_waits_for_a_purge_that_holds_the_song_and_saves_its_take(
    pg_factory, tmp_path, monkeypatch,
) -> None:
    world = _World(pg_factory, tmp_path, jobs={"job-new": _queued_generation()})
    world.record_unlinks(monkeypatch)

    answers = race(
        pg_factory, world.purge(), world.persist("new-take", "job-new"),
        _held_after_song_lock(),
    )

    assert answers["first"] == (0, 0)
    assert answers["second"] is not None
    assert world.take_ids() == sorted([OLD_TAKE, answers["second"]])
    assert world.unlinked == []


def test_a_song_without_takes_and_with_only_finished_jobs_is_deleted_without_paths(
    pg_factory, tmp_path, monkeypatch,
) -> None:
    finished = {"type": JobType.GENERATE, "status": JobStatus.COMPLETED, "song_id": "song-1"}
    world = _World(pg_factory, tmp_path, scored_take=False, jobs={"job-done": finished})
    world.record_unlinks(monkeypatch)

    assert world.purge()() == (0, 1)

    assert world.song_ids() == []
    assert world.unlinked == []


@pytest.mark.parametrize(
    "active_job",
    [
        pytest.param(
            {"type": JobType.COVER, "status": JobStatus.RUNNING, "album_id": "album-1"},
            id="album-cover-job",
        ),
        pytest.param(_running_generation("song-2"), id="running-generation-on-a-song"),
    ],
)
def test_an_album_purge_is_deferred_whole_while_the_album_or_one_of_its_songs_has_a_running_job(
    pg_factory, tmp_path, monkeypatch, active_job,
) -> None:
    world = _World(
        pg_factory, tmp_path, songs=("song-1", "song-2"), trashed_albums=("album-1",),
        jobs={"job-active": active_job},
    )
    world.record_unlinks(monkeypatch)

    assert world.purge()() == (0, 0)

    assert world.song_ids() == ["song-1", "song-2"]
    assert world.take_ids() == [OLD_TAKE]
    assert world.unlinked == []
    world.finish_job("job-active")
    assert world.purge()() == (1, 0)
    assert world.song_ids() == []
    assert world.unlinked == _owned_paths(OLD_TAKE)


def test_an_album_purge_is_deferred_whole_when_a_persist_on_one_song_holds_it_first(
    pg_factory, tmp_path, monkeypatch,
) -> None:
    world = _World(
        pg_factory, tmp_path, songs=("song-1", "song-2"), trashed_albums=("album-1",),
        jobs={"job-new": _running_generation("song-2")},
    )
    world.record_unlinks(monkeypatch)

    answers = race(
        pg_factory, world.persist("new-take", "job-new", "song-2"), world.purge(),
        _held_after_persist_song_lock(),
    )

    assert answers["second"] == (0, 0)
    assert world.song_ids() == ["song-1", "song-2"]
    assert world.take_ids() == sorted([OLD_TAKE, answers["first"]])
    assert world.unlinked == []


def test_two_purges_whose_candidates_differ_lock_their_songs_in_one_order(
    pg_factory, tmp_path, monkeypatch,
) -> None:
    world = _World(
        pg_factory, tmp_path, songs=("song-a", "song-b"), scored_take=False,
        song_albums={"song-a": "album-a", "song-b": "album-b"}, trashed_albums=("album-b",),
        jobs={
            "job-a": _running_generation("song-a"), "job-b": _running_generation("song-b"),
        },
    )
    world.record_unlinks(monkeypatch)

    def purge_after_album_a_expires() -> tuple[int, int]:
        world.trash_album("album-a")
        return world.purge()()

    answers = race(pg_factory, world.purge(), purge_after_album_a_expires, _held_after_song_lock())

    assert answers == {"first": (0, 0), "second": (0, 0)}
    assert world.song_ids() == ["song-a", "song-b"]


def test_a_second_purge_finds_nothing_and_unlinks_no_file_twice(
    pg_factory, tmp_path, monkeypatch,
) -> None:
    world = _World(pg_factory, tmp_path)
    world.record_unlinks(monkeypatch)

    assert world.purge()() == (0, 1)
    assert world.purge()() == (0, 0)

    assert world.unlinked == _owned_paths(OLD_TAKE)


@pytest.mark.parametrize(
    ("trashed_albums", "purged_counts"),
    [
        pytest.param(("album-1",), [(0, 0), (1, 0)], id="album"),
        pytest.param((), [(0, 0), (0, 1)], id="orphan-song"),
    ],
)
def test_two_purges_of_the_same_candidates_both_finish(
    pg_factory, tmp_path, monkeypatch, trashed_albums, purged_counts,
) -> None:
    world = _World(pg_factory, tmp_path, trashed_albums=trashed_albums)
    world.record_unlinks(monkeypatch)

    answers = race(pg_factory, world.purge(), world.purge(), _held_after_song_lock())

    assert sorted(answers.values()) == purged_counts
    assert world.song_ids() == []
    assert world.unlinked == _owned_paths(OLD_TAKE)
    assert world.files_left(OLD_TAKE) == []


def test_two_purges_of_the_same_empty_album_both_finish(
    pg_factory, tmp_path, monkeypatch,
) -> None:
    world = _World(pg_factory, tmp_path, songs=(), trashed_albums=("album-1",), scored_take=False)
    world.record_unlinks(monkeypatch)

    answers = race(pg_factory, world.purge(), world.purge(), _held_after_song_lock())

    assert sorted(answers.values()) == [(0, 0), (1, 0)]
    assert world.album_ids() == []

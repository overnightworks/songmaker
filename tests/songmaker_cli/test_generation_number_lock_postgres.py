"""A take's persist numbers it under its song's lock, against other persists and song saves."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from support.postgres_lock_harness import CommitPause, StatementPause, race, wrote_to_tables

from acestep_engine.models import AceStepConfig
from songmaker_cli.constants import REFERENCE_AUDIO_DIR
from songmaker_cli.db.models import (
    Album,
    Generation,
    Job,
    ReferenceRecording,
    Song,
    User,
    Version,
)
from songmaker_cli.db.queries.songs import update_song
from songmaker_cli.jobs import _persist_generation_row
from songmaker_cli.jobs.generation import GenerationContext
from songmaker_cli.parser import AlbumMeta, SongMeta

OWNER = "u1"
SONG_ID = "song-a"
REFERENCE_ID = "reference-1"
EDITED = "edited"
TAKES = ("take-a", "take-b")


def _song_row_lock_statement(sql: str) -> bool:
    return "FROM songs" in sql and sql.rstrip().endswith("FOR UPDATE")


class _World:
    """One song with a reference-linked version and two running jobs, on PostgreSQL."""

    def __init__(self, pg_factory, tmp_path: Path, *, trashed: bool = False) -> None:
        self.pg_factory = pg_factory
        self.audio_dir = tmp_path / "audio"
        (self.audio_dir / OWNER).mkdir(parents=True)
        with pg_factory() as session:
            session.add(User(id=OWNER, username="owner"))
            session.flush()
            session.add(Album(id="album-a", title="A", artist="A", created_by=OWNER))
            session.flush()
            session.add(Song(
                id=SONG_ID, title="S", album_id="album-a", track_number=1,
                deleted_at=datetime.now(timezone.utc) if trashed else None,
            ))
            session.flush()
            session.add_all([
                ReferenceRecording(
                    id=REFERENCE_ID, user_id=OWNER,
                    storage_path=f"{OWNER}/{REFERENCE_AUDIO_DIR}/F.wav",
                    original_filename="F.wav", size_bytes=4,
                ),
                Job(id="job-take-a", type="generate", status="running", user_id=OWNER),
                Job(id="job-take-b", type="generate", status="running", user_id=OWNER),
            ])
            session.flush()
            session.add(Version(
                id="version-a", song_id=SONG_ID, version_number=1, lyrics="la", prompt="p",
                reference_recording_id=REFERENCE_ID,
            ))
            session.commit()

    def persist(
        self, take: str, *, song_id: str = SONG_ID, reference_id: str | None = REFERENCE_ID,
    ):
        """The take's real persistence; its audio files exist before it runs."""
        for suffix in (".mp3", ".wav"):
            (self.audio_dir / OWNER / f"{take}{suffix}").write_bytes(b"audio")
        context = GenerationContext(
            song_id=song_id, version_id="version-a",
            meta=SongMeta(title="S", lyrics="la", prompt="p"),
            album_meta=AlbumMeta(title="A", artist="A"),
            ace_config=AceStepConfig(prompt="p", lyrics="la", audio_duration=0),
            audio_dir=self.audio_dir, user_id=OWNER, reference_recording_id=reference_id,
            model_name="turbo",
        )
        return lambda: _persist_generation_row(
            db_factory=self.pg_factory, ctx=context, generation_id=take, seed=1,
            cot_caption="", cot_lyrics="", delivered_batch_size=None, job_id=f"job-{take}",
        )

    def save(self):
        """The real save path writing the next version of the song."""
        def run() -> None:
            with self.pg_factory() as session:
                update_song(session, SONG_ID, lyrics=EDITED, force_new_version=True)
                session.commit()

        return run

    def take_numbers(self) -> list[int]:
        with self.pg_factory() as session:
            return sorted(row.generation_number for row in session.query(Generation))

    def version_lyrics(self) -> list[str]:
        with self.pg_factory() as session:
            return [version.lyrics for version in session.query(Version).order_by(
                Version.version_number)]

    def mp3_exists(self, take: str) -> bool:
        return (self.audio_dir / OWNER / f"{take}.mp3").exists()


def _held_at_take_insert() -> CommitPause:
    return CommitPause(lambda session: wrote_to_tables(session, "generations"))


def test_two_persists_of_one_song_are_saved_as_numbers_n_and_n_plus_1(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)

    answers = race(
        pg_factory,
        world.persist(TAKES[0], reference_id=None),
        world.persist(TAKES[1], reference_id=None),
        _held_at_take_insert(),
    )

    assert answers["first"] is not None
    assert answers["second"] is not None
    assert world.take_numbers() == [1, 2]
    assert all(world.mp3_exists(take) for take in TAKES)


def test_a_save_and_a_persist_of_the_same_song_are_both_saved_when_the_persist_goes_first(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)

    answers = race(pg_factory, world.persist(TAKES[0]), world.save(), _held_at_take_insert())

    assert answers["first"] is not None
    assert world.take_numbers() == [1]
    assert world.version_lyrics() == ["la", EDITED]


def test_a_save_and_a_persist_of_the_same_song_are_both_saved_when_the_save_goes_first(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)

    answers = race(pg_factory, world.save(), world.persist(TAKES[0]))

    assert answers["second"] is not None
    assert world.take_numbers() == [1]
    assert world.version_lyrics() == ["la", EDITED]


def test_a_persist_that_took_the_reference_is_saved_when_a_save_holds_the_song_and_needs_it(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)
    save_holds_song = StatementPause(_song_row_lock_statement)

    answers = race(pg_factory, world.save(), world.persist(TAKES[0]), save_holds_song)

    assert answers["second"] is not None
    assert world.take_numbers() == [1]
    assert world.version_lyrics() == ["la", EDITED]
    assert world.mp3_exists(TAKES[0])


def test_a_take_is_saved_on_a_song_that_was_moved_to_the_trash(pg_factory, tmp_path) -> None:
    world = _World(pg_factory, tmp_path, trashed=True)

    persisted_id = world.persist(TAKES[0])()

    assert persisted_id is not None
    assert world.take_numbers() == [1]
    assert world.mp3_exists(TAKES[0])


def test_a_persist_for_a_song_that_is_gone_fails_and_removes_its_files(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path)

    with pytest.raises(IntegrityError):
        world.persist(TAKES[0], song_id="song-gone")()

    assert world.take_numbers() == []
    assert not world.mp3_exists(TAKES[0])

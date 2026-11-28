"""The daily voice purge removes voices deleted past the final-deletion window with their files."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from support.worker_settings import worker_settings

import songmaker_cli.music_worker as music_worker_module
from songmaker_cli.audio_paths import USER_LORAS_DIRNAME
from songmaker_cli.constants import LoraStatus
from songmaker_cli.cron_schedule import Cron
from songmaker_cli.db.models import User, UserLora, UserLoraSample
from songmaker_cli.music_worker import MusicWorker
from songmaker_cli.settings import get_settings

NOW = datetime(2026, 11, 28, 3, 0, tzinfo=UTC)
OWNER = "owner-1"
OWNERS_OWN_DIRECTORY = "."


@dataclass(frozen=True)
class _Voice:
    id: str
    days_since_deleted: int | None
    status: LoraStatus = LoraStatus.READY


def _window() -> int:
    return get_settings().final_deletion_days


def _voices() -> list[_Voice]:
    return [
        _Voice("gone-long-ago", _window() + 1),
        _Voice("exactly-at-the-cutoff", _window()),
        _Voice("deleted-recently", _window() - 1),
        _Voice("never-deleted", None),
        _Voice("still-training", _window() + 1, LoraStatus.TRAINING),
        _Voice("stuck-directory", _window() + 1),
        _Voice("outside-directory", _window() + 1),
        _Voice(OWNERS_OWN_DIRECTORY, _window() + 1),
    ]


class _World:
    """Voices on PostgreSQL, each with samples and a directory of audio files."""

    def __init__(self, pg_factory, audio_dir: Path, outside: Path) -> None:
        self.pg_factory = pg_factory
        self.audio_dir = audio_dir
        self.outside = outside
        with pg_factory() as session:
            session.add(User(id=OWNER, username=OWNER))
            session.flush()
            for voice in _voices():
                self._plant(session, voice)
            session.commit()

    def directory(self, voice_id: str) -> Path:
        return self.audio_dir / USER_LORAS_DIRNAME / OWNER / voice_id

    def _plant(self, session, voice: _Voice) -> None:
        session.add(UserLora(
            id=voice.id, user_id=OWNER, name=voice.id, slug=voice.id, status=voice.status,
            deleted_at=(
                None if voice.days_since_deleted is None
                else NOW - timedelta(days=voice.days_since_deleted)
            ),
        ))
        session.flush()
        session.add(UserLoraSample(
            id=f"s-{voice.id}", user_lora_id=voice.id,
            audio_path=f"{USER_LORAS_DIRNAME}/{OWNER}/{voice.id}/samples/take.wav",
        ))
        if voice.id == OWNERS_OWN_DIRECTORY:
            return
        linked_to = self.outside if voice.id == "outside-directory" else None
        target = linked_to or self.directory(voice.id)
        (target / "samples").mkdir(parents=True)
        (target / "samples" / "take.wav").write_bytes(b"audio")
        if linked_to:
            self.directory(voice.id).parent.mkdir(parents=True, exist_ok=True)
            self.directory(voice.id).symlink_to(target, target_is_directory=True)

    def voices_left(self) -> set[str]:
        with self.pg_factory() as session:
            return {lora.id for lora in session.query(UserLora)}

    def sample_voices_left(self) -> set[str]:
        with self.pg_factory() as session:
            return {sample.user_lora_id for sample in session.query(UserLoraSample)}

    def directories_left(self) -> set[str]:
        owner_root = self.audio_dir / USER_LORAS_DIRNAME / OWNER
        return {path.name for path in owner_root.iterdir()}

    def add_expired_voice(self, owner_id: str, voice_id: str) -> None:
        with self.pg_factory() as session:
            if session.get(User, owner_id) is None:
                session.add(User(id=owner_id, username=uuid.uuid4().hex))
                session.flush()
            session.add(UserLora(
                id=voice_id, user_id=owner_id, name="hostile", slug="hostile",
                status=LoraStatus.READY, deleted_at=NOW - timedelta(days=_window() + 1),
            ))
            session.commit()

    def run_the_daily_purge(self, monkeypatch: pytest.MonkeyPatch) -> int:
        monkeypatch.setattr(music_worker_module, "utcnow", lambda: NOW)
        settings = worker_settings().model_copy(update={"audio_dir": str(self.audio_dir)})
        worker = MusicWorker(settings)
        worker.get_db_factory = MagicMock(return_value=self.pg_factory)
        return asyncio.run(worker.cron_bodies()[Cron.VOICE_PURGE]())


@pytest.fixture
def world(pg_factory, tmp_path: Path) -> _World:
    return _World(pg_factory, tmp_path / "audio", tmp_path / "outside" / "kept")


@pytest.fixture
def stuck_directory(world: _World):
    """Makes one voice's samples unremovable; the fixture's value lifts that."""
    samples = world.directory("stuck-directory") / "samples"
    samples.chmod(0o500)
    try:
        yield lambda: samples.chmod(0o700)
    finally:
        if samples.exists():
            samples.chmod(0o700)


ROOT_IGNORES_PERMISSIONS = "root removes files from a read-only directory"

KEPT = {
    "exactly-at-the-cutoff", "deleted-recently", "never-deleted", "still-training",
    "stuck-directory", "outside-directory", OWNERS_OWN_DIRECTORY,
}
KEPT_DIRECTORIES = KEPT - {OWNERS_OWN_DIRECTORY}


@pytest.mark.skipif(os.geteuid() == 0, reason=ROOT_IGNORES_PERMISSIONS)
def test_the_daily_purge_removes_voices_deleted_before_the_window_with_samples_and_directory(
    world: _World, stuck_directory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    purged = world.run_the_daily_purge(monkeypatch)

    assert purged == 1
    assert world.voices_left() == KEPT
    assert world.sample_voices_left() == KEPT
    assert world.directories_left() == KEPT_DIRECTORIES


def test_a_directory_outside_the_owners_voices_is_left_with_its_rows(
    world: _World, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world.run_the_daily_purge(monkeypatch)

    assert (world.outside / "samples" / "take.wav").read_bytes() == b"audio"
    assert "outside-directory" in world.voices_left()


def test_a_voice_that_names_its_owners_own_directory_leaves_every_voice_of_the_owner(
    world: _World, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world.run_the_daily_purge(monkeypatch)

    assert (world.directory("never-deleted") / "samples" / "take.wav").read_bytes() == b"audio"
    assert OWNERS_OWN_DIRECTORY in world.voices_left()


def test_a_voice_whose_id_reaches_into_another_voices_directory_leaves_that_voice(
    world: _World, monkeypatch: pytest.MonkeyPatch,
) -> None:
    nested_id = "never-deleted/samples"
    with world.pg_factory() as session:
        session.add(UserLora(
            id=nested_id, user_id=OWNER, name=nested_id, slug="nested", status=LoraStatus.READY,
            deleted_at=NOW - timedelta(days=_window() + 1),
        ))
        session.commit()

    world.run_the_daily_purge(monkeypatch)

    assert (world.directory("never-deleted") / "samples" / "take.wav").read_bytes() == b"audio"
    assert nested_id in world.voices_left()


def test_a_voice_of_a_linked_owner_directory_leaves_the_directory_it_links_to_with_its_rows(
    world: _World, monkeypatch: pytest.MonkeyPatch,
) -> None:
    linked_owner, voice_id = "owner-2", "linked-owner-voice"
    elsewhere = world.audio_dir / "elsewhere"
    (elsewhere / voice_id / "samples").mkdir(parents=True)
    (elsewhere / voice_id / "samples" / "take.wav").write_bytes(b"audio")
    (world.audio_dir / USER_LORAS_DIRNAME / linked_owner).symlink_to(
        elsewhere, target_is_directory=True,
    )
    with world.pg_factory() as session:
        session.add(User(id=linked_owner, username=linked_owner))
        session.flush()
        session.add(UserLora(
            id=voice_id, user_id=linked_owner, name=voice_id, slug=voice_id,
            status=LoraStatus.READY, deleted_at=NOW - timedelta(days=_window() + 1),
        ))
        session.commit()

    world.run_the_daily_purge(monkeypatch)

    assert (elsewhere / voice_id / "samples" / "take.wav").read_bytes() == b"audio"
    assert voice_id in world.voices_left()


@pytest.fixture
def away():
    """A short absolute directory in the system temp directory: users.id holds 36 characters."""
    directory = Path(tempfile.mkdtemp())
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _hostile_absolute_owner(world: _World, away: Path) -> tuple[str, str, Path]:
    return str(away), "x", away / "x"


def _owner_dot_naming_another_owners_directory(world: _World, away: Path) -> tuple[str, str, Path]:
    return ".", OWNER, world.directory("never-deleted")


def _voice_id_dot_slash_naming_a_live_voice(world: _World, away: Path) -> tuple[str, str, Path]:
    return OWNER, "./never-deleted", world.directory("never-deleted")


@pytest.mark.parametrize(
    "hostile",
    [
        pytest.param(_hostile_absolute_owner, id="absolute-owner-id"),
        pytest.param(_owner_dot_naming_another_owners_directory, id="dot-owner-id"),
        pytest.param(_voice_id_dot_slash_naming_a_live_voice, id="dot-slash-voice-id"),
    ],
)
def test_a_voice_whose_ids_join_to_a_directory_that_is_not_its_own_leaves_that_directory(
    world: _World, away: Path, monkeypatch: pytest.MonkeyPatch,
    hostile: Callable[[_World, Path], tuple[str, str, Path]],
) -> None:
    owner_id, voice_id, victim = hostile(world, away)
    (victim / "kept.txt").parent.mkdir(parents=True, exist_ok=True)
    (victim / "kept.txt").write_bytes(b"audio")
    world.add_expired_voice(owner_id, voice_id)

    world.run_the_daily_purge(monkeypatch)

    assert (victim / "kept.txt").read_bytes() == b"audio"
    assert voice_id in world.voices_left()


@pytest.mark.parametrize(
    ("owner_id", "voice_id"),
    [
        pytest.param("/", "etc", id="slash-owner-id"),
        pytest.param("//", "etc", id="double-slash-owner-id"),
        pytest.param(OWNER, "/", id="slash-voice-id"),
        pytest.param(OWNER, "//", id="double-slash-voice-id"),
    ],
)
def test_a_voice_whose_id_is_made_of_slashes_is_removed_nowhere_and_keeps_its_rows(
    world: _World, monkeypatch: pytest.MonkeyPatch, owner_id: str, voice_id: str,
) -> None:
    """These ids join to the filesystem root, so a regression must not reach a real removal."""
    removed: list[Path] = []
    monkeypatch.setattr(shutil, "rmtree", lambda path, *args, **kwargs: removed.append(Path(path)))
    world.add_expired_voice(owner_id, voice_id)

    world.run_the_daily_purge(monkeypatch)

    assert [path for path in removed if not path.is_relative_to(world.audio_dir)] == []
    assert voice_id in world.voices_left()


@pytest.mark.skipif(os.geteuid() == 0, reason=ROOT_IGNORES_PERMISSIONS)
def test_a_voice_whose_directory_stays_is_logged_as_a_warning(
    world: _World, stuck_directory, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        world.run_the_daily_purge(monkeypatch)

    assert any(
        record.levelno == logging.WARNING and record.name == "songmaker_cli.cleanup"
        and "stuck-directory" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.skipif(os.geteuid() == 0, reason=ROOT_IGNORES_PERMISSIONS)
def test_the_next_daily_purge_removes_a_voice_whose_directory_could_not_be_removed_before(
    world: _World, stuck_directory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    lift_the_stuck_directory = stuck_directory
    world.run_the_daily_purge(monkeypatch)
    lift_the_stuck_directory()

    purged = world.run_the_daily_purge(monkeypatch)

    assert purged == 1
    assert world.voices_left() == KEPT - {"stuck-directory"}
    assert world.directories_left() == KEPT_DIRECTORIES - {"stuck-directory"}


def test_the_daily_purge_finishes_a_voice_whose_directory_a_crashed_run_already_removed(
    world: _World, monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutil.rmtree(world.directory("gone-long-ago"))

    world.run_the_daily_purge(monkeypatch)

    assert "gone-long-ago" not in world.voices_left()

"""The daily voice purge removes voices deleted past the final-deletion window with their files."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import songmaker_cli.music_worker as music_worker_module
from songmaker_cli.constants import USER_LORAS_DIRNAME, LoraStatus
from songmaker_cli.cron_schedule import Cron
from songmaker_cli.db.models import User, UserLora, UserLoraSample
from songmaker_cli.music_worker import MusicWorker
from songmaker_cli.settings import Settings, get_settings

NOW = datetime(2026, 11, 28, 3, 0, tzinfo=UTC)
OWNER = "owner-1"


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
        target = self.outside if voice.id == "outside-directory" else self.directory(voice.id)
        (target / "samples").mkdir(parents=True)
        (target / "samples" / "take.wav").write_bytes(b"audio")
        if target is self.outside:
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

    def run_the_daily_purge(self, monkeypatch: pytest.MonkeyPatch) -> int:
        monkeypatch.setattr(music_worker_module, "utcnow", lambda: NOW)
        settings = Settings(
            database_url="postgresql://example", redis_url="redis://example",
            session_secret="session-secret", songmaker_internal_token="internal-token",
            audio_dir=str(self.audio_dir),
        )
        worker = MusicWorker(settings)
        worker.get_db_factory = MagicMock(return_value=self.pg_factory)
        return asyncio.run(worker.cron_bodies()[Cron.VOICE_PURGE]())


@pytest.fixture
def world(pg_factory, tmp_path: Path) -> _World:
    return _World(pg_factory, tmp_path / "audio", tmp_path / "outside" / "kept")


@pytest.fixture
def stuck_directory(monkeypatch: pytest.MonkeyPatch, world: _World) -> dict[str, bool]:
    """Fails the removal of one voice's directory while ``fails`` holds."""
    state = {"fails": True}
    stuck = world.directory("stuck-directory").resolve()
    real_rmtree = shutil.rmtree

    def rmtree(path, *args, **kwargs):
        if state["fails"] and Path(path).resolve() == stuck:
            raise PermissionError(path)
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", rmtree)
    return state


KEPT = {
    "exactly-at-the-cutoff", "deleted-recently", "never-deleted", "still-training",
    "stuck-directory", "outside-directory",
}


def test_the_daily_purge_removes_voices_deleted_before_the_window_with_samples_and_directory(
    world: _World, stuck_directory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    purged = world.run_the_daily_purge(monkeypatch)

    assert purged == 1
    assert world.voices_left() == KEPT
    assert world.sample_voices_left() == KEPT
    assert world.directories_left() == KEPT


def test_a_directory_outside_the_owners_voices_is_left_with_its_rows(
    world: _World, stuck_directory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world.run_the_daily_purge(monkeypatch)

    assert (world.outside / "samples" / "take.wav").read_bytes() == b"audio"
    assert "outside-directory" in world.voices_left()


def test_the_next_daily_purge_removes_a_voice_whose_directory_could_not_be_removed_before(
    world: _World, stuck_directory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world.run_the_daily_purge(monkeypatch)
    stuck_directory["fails"] = False

    purged = world.run_the_daily_purge(monkeypatch)

    assert purged == 1
    assert world.voices_left() == KEPT - {"stuck-directory"}
    assert world.directories_left() == KEPT - {"stuck-directory"}


def test_the_daily_purge_finishes_a_voice_whose_directory_a_crashed_run_already_removed(
    world: _World, monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutil.rmtree(world.directory("gone-long-ago"))

    world.run_the_daily_purge(monkeypatch)

    assert "gone-long-ago" not in world.voices_left()

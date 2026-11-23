"""Tests for the music worker."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from functools import partial
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from logline.testing import configured
from support.job_owner import an_owner
from support.redis_clock import Window, until
from support.reference_rows import a_reference

import songmaker_cli.music_worker as mw_mod
from songmaker_cli.api_models import RepaintTaskParams
from songmaker_cli.cleanup import DAILY_CLEANUP_HOUR_UTC
from songmaker_cli.cron_schedule import Cron, CronBody
from songmaker_cli.db.models import Album, Job, ReferenceRecording, User
from songmaker_cli.job_payloads import (
    DownloadModelPayload,
    GeneratePayload,
    LoadModelPayload,
    LoraTrainingPayload,
)
from songmaker_cli.job_queue import ClaimedJob
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.music_worker import MusicWorker
from songmaker_cli.redis_client import create_async_redis
from songmaker_cli.settings import Settings, get_settings

FOREVER_SECONDS = 3600
RUN_WITHIN_SECONDS = 30
RUNS_LONGER_THAN_ZERO_SECONDS = 1


def _run(coro):
    return asyncio.run(coro)


def _mock_ctx():
    return {"redis": AsyncMock()}


def _make_worker(worker: MusicWorker | None = None) -> MusicWorker:
    """A worker with DB / dirs stubbed and the context a started worker's jobs run with."""
    worker = worker or MusicWorker()
    worker.owner = an_owner(worker.owner_id)
    worker._job_context = _mock_ctx()
    worker.audio_dir = MagicMock(return_value="audio")
    worker.data_dir = MagicMock(return_value="data")
    worker.get_db_factory = MagicMock(return_value=MagicMock())
    return worker


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://example",
        redis_url="redis://example",
        session_secret="session-secret",
        songmaker_internal_token="internal-token",
    )


def _claimed(payload, job_id: str = "j1") -> ClaimedJob:
    return ClaimedJob(job_id, JobType(payload.job_type), payload)


A_GENERATE = GeneratePayload(
    song_id="s1", version_id="v1", count=2, user_id="u1", seed=42, target_model="xl-sft",
    task_params=None,
)
A_REPAINT = A_GENERATE.model_copy(update={"task_params": RepaintTaskParams(
    src_wav_path="/x.wav", src_generation_id="g0", repainting_start=0.0, repainting_end=1.0,
    lyrics="la", prompt="rock",
)})
A_LORA_TRAINING = LoraTrainingPayload(lora_id="l1", user_id="u1", target_mode="turbo")
A_MODEL_LOAD = LoadModelPayload(worker_id="gpu", mode="turbo")
A_MODEL_DOWNLOAD = DownloadModelPayload(mode="turbo")
WORK = {
    JobType.GENERATE: "songmaker_cli.music_worker.run_generation_job",
    JobType.LORA_TRAINING: "songmaker_cli.music_worker.run_lora_training_job",
    JobType.LOAD_MODEL_ON_WORKER: "songmaker_cli.music_worker._load_model_on_worker_impl",
    JobType.DOWNLOAD_MODEL_ON_WORKER: "songmaker_cli.music_worker._download_model_on_worker_impl",
}


def _run_claimed(worker: MusicWorker, claimed: ClaimedJob) -> AsyncMock:
    """Run the claimed row; returns the work of its type, which was replaced by a mock."""
    with patch(WORK[claimed.job_type], new_callable=AsyncMock) as work:
        _run(worker.run_claimed(claimed))
    return work


@pytest.mark.parametrize(
    "payload", [A_GENERATE, A_LORA_TRAINING, A_MODEL_LOAD, A_MODEL_DOWNLOAD],
    ids=lambda payload: payload.job_type,
)
def test_a_claimed_row_runs_the_work_of_its_type_for_this_worker(payload) -> None:
    worker = _make_worker()

    work = _run_claimed(worker, _claimed(payload))

    work.assert_awaited_once()
    assert work.await_args.kwargs["owner"] is worker.owner


def test_a_claimed_generation_runs_with_the_arguments_of_its_row() -> None:
    worker = _make_worker()

    work = _run_claimed(worker, _claimed(A_GENERATE))

    assert work.await_args.args == ("j1", "s1", "v1", 2, "u1")
    kwargs = work.await_args.kwargs
    assert (kwargs["seed"], kwargs["target_model"], kwargs["redis"]) == (
        42, "xl-sft", worker._job_context["redis"],
    )


def test_a_claimed_repaint_runs_with_the_task_of_its_row() -> None:
    worker = _make_worker()

    work = _run_claimed(worker, _claimed(A_REPAINT))

    task = work.await_args.kwargs["task_params"]
    assert isinstance(task, RepaintTaskParams)
    assert (task.src_wav_path, task.repainting_end) == ("/x.wav", 1.0)


def test_a_claimed_voice_training_runs_with_its_configuration_and_target_mode() -> None:
    worker = _make_worker()

    work = _run_claimed(worker, _claimed(A_LORA_TRAINING))

    assert work.await_args.args[1:] == ("j1", "l1", "u1")
    assert work.await_args.kwargs["training_config"] == worker._settings.lora_training_config
    assert work.await_args.kwargs["target_mode"] == "turbo"


@pytest.mark.parametrize(
    ("payload", "own_limit", "other_limit"),
    [
        (A_GENERATE, "arq_job_timeout", "lora_training_job_timeout"),
        (A_LORA_TRAINING, "lora_training_job_timeout", "arq_job_timeout"),
    ],
    ids=lambda value: value.job_type if hasattr(value, "job_type") else value,
)
def test_a_job_that_outlasts_its_own_time_limit_is_cut(payload, own_limit, other_limit) -> None:
    limits = {own_limit: 0, other_limit: FOREVER_SECONDS}
    worker = _make_worker(MusicWorker(get_settings().model_copy(update=limits)))

    async def outlasts_a_zero_limit(*_args, **_kwargs) -> None:
        await asyncio.sleep(RUNS_LONGER_THAN_ZERO_SECONDS)

    running = worker.run_claimed(_claimed(payload))
    with patch(WORK[JobType(payload.job_type)], new=outlasts_a_zero_limit), pytest.raises(
        TimeoutError,
    ):
        _run(running)


def test_file_cleanup_cron_audits_orphans_and_expires_files(tmp_path, caplog, pg_factory) -> None:
    factory = pg_factory
    audio_dir = tmp_path / "audio"
    orphan = audio_dir / "u1" / "orphan.mp3"
    orphan.parent.mkdir(parents=True)
    orphan.touch()
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=get_settings().final_deletion_days + 1,
    )
    with factory() as session:
        session.add(User(id="u1", username="u1"))
        session.add(Album(
            id="expired-album", title="Expired", artist="", deleted_at=cutoff,
        ))
        session.commit()

    worker = MusicWorker()
    worker.get_db_factory = MagicMock(return_value=factory)
    worker.audio_dir = MagicMock(return_value=audio_dir)

    with caplog.at_level(logging.WARNING, logger="songmaker_cli.worker_base"):
        _run(worker.cleanup_files_cron())

    with factory() as session:
        expired_album = (
            session.query(Album)
            .execution_options(include_deleted=True)
            .filter_by(id="expired-album")
            .one_or_none()
        )

    assert expired_album is None
    assert any(str(orphan) in message for message in caplog.messages)


def test_stop_disposes_db() -> None:
    worker = MusicWorker()
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)
    worker.get_db_factory = MagicMock(return_value=mock_factory)
    worker._db_engine = MagicMock()

    _run(worker.stop())

    worker._db_engine.dispose.assert_called_once()


def test_file_cleanup_cron_leaves_queued_generate_job_untouched(tmp_path, pg_factory) -> None:
    factory = pg_factory
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    with factory() as session:
        session.add(Job(
            id="generate-queued", type=JobType.GENERATE, status=JobStatus.QUEUED,
            heartbeat_at=datetime.now(timezone.utc) - timedelta(days=1),
        ))
        session.commit()

    worker = MusicWorker()
    worker.get_db_factory = MagicMock(return_value=factory)
    worker.audio_dir = MagicMock(return_value=audio_dir)

    _run(worker.cleanup_files_cron())

    with factory() as session:
        job = session.query(Job).filter_by(id="generate-queued").one()

    assert job.status == JobStatus.QUEUED


def test_reference_remnant_cron_removes_files_without_a_row_and_returns_the_count(
    tmp_path, pg_factory,
) -> None:
    factory = pg_factory
    audio_dir = tmp_path / "audio"
    refs = audio_dir / "u1" / "refs"
    refs.mkdir(parents=True)
    (refs / "one.wav").write_bytes(b"x")
    (refs / "two.wav").write_bytes(b"x")
    with factory() as session:
        session.add(User(id="u1", username="u1"))
        session.commit()
    settings = _settings().model_copy(update={"audio_dir": str(audio_dir)})
    worker = MusicWorker(settings)
    # init_db checks a live PostgreSQL database.
    worker.get_db_factory = MagicMock(return_value=factory)

    removed = _run(worker.reference_remnant_cron())

    assert removed == 2
    assert list(refs.iterdir()) == []


def test_reference_unused_cron_stamps_unused_rows_and_returns_the_changed_count(
    tmp_path, pg_factory,
) -> None:
    factory = pg_factory
    with factory() as session:
        session.add(User(id="u1", username="u1"))
        session.flush()
        a_reference(session, "u1", name="r1.wav", reference_id="r1")
        session.commit()
    worker = MusicWorker(_settings())
    worker.get_db_factory = MagicMock(return_value=factory)

    changed = _run(worker.reference_unused_cron())

    with factory() as session:
        stamp = session.get(ReferenceRecording, "r1").unused_since
    assert changed == 1
    assert stamp is not None


def test_reference_unused_cron_reconciles_before_it_deletes_and_counts_the_deletions(
    tmp_path, monkeypatch,
) -> None:
    from songmaker_cli import reference_audio

    calls: list[str] = []
    received: dict[str, object] = {}
    now = datetime(2026, 3, 4, 5, 6, tzinfo=timezone.utc)

    def reconcile(_factory):
        calls.append("reconcile")
        return reference_audio.ReconciledStamps(stamped=2, cleared=1)

    def delete(_factory, _audio_dir, **arguments):
        calls.append("delete")
        received.update(arguments)
        return reference_audio.AnnouncedDeletionReport(deleted=4, skipped=5, failed=6)

    monkeypatch.setattr(reference_audio, "reconcile_unused_stamps", reconcile)
    monkeypatch.setattr(reference_audio, "delete_announced_references", delete)
    monkeypatch.setattr(mw_mod, "utcnow", lambda: now)
    worker = MusicWorker(_settings().model_copy(
        update={"audio_dir": str(tmp_path), "final_deletion_days": 17},
    ))
    worker.get_db_factory = MagicMock()

    changed = _run(worker.reference_unused_cron())

    assert calls == ["reconcile", "delete"]
    assert received == {"days": 17, "hour": DAILY_CLEANUP_HOUR_UTC, "now": now}
    assert changed == 2 + 1 + 4


def test_the_music_worker_has_a_body_for_every_cron() -> None:
    assert set(MusicWorker().cron_bodies()) == set(Cron)


def test_a_running_music_worker_runs_each_cron_once_and_ends_on_a_stop_signal(
    redis_url, tmp_path, stop_signal_handlers,
) -> None:
    runs: list[str] = []

    class RecordingMusicWorker(MusicWorker):
        def cron_bodies(self) -> dict[Cron, CronBody]:
            async def record(cron: Cron) -> None:
                runs.append(cron.value)

            return {cron: partial(record, cron) for cron in Cron}

    worker = RecordingMusicWorker(
        _settings().model_copy(update={"redis_url": redis_url}),
        readiness_file=tmp_path / "readiness",
    )
    worker.get_db_factory = MagicMock()
    worker.claim_next_job = MagicMock(return_value=None)

    window = Window()

    async def run_until_every_cron_ran_then_stop() -> None:
        redis = create_async_redis(redis_url)
        try:
            async with window.observing(redis):
                running = asyncio.create_task(worker.run())
                async with asyncio.timeout(RUN_WITHIN_SECONDS):
                    await until(lambda: len(runs) >= len(Cron))
                    os.kill(os.getpid(), signal.SIGTERM)
                    await running
        finally:
            await redis.aclose()

    with configured("restored-after-the-test"):
        _run(run_until_every_cron_ran_then_stop())

    once_each = dict.fromkeys(Cron, 1)
    ran = {cron: runs.count(cron.value) for cron in Cron}
    assert window.without_the_runs_its_ticks_explain(ran, once_each) == once_each


def test_the_music_worker_module_imports_no_arq() -> None:
    imported = subprocess.run(
        [sys.executable, "-c",
         "import sys, songmaker_cli.music_worker;"
         " print(sorted(name for name in sys.modules if name.split('.')[0] == 'arq'))"],
        capture_output=True, text=True, check=True,
    )

    assert imported.stdout.strip() == "[]"

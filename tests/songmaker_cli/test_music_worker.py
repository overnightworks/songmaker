"""Tests for the music worker."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from support.reference_rows import a_reference

import songmaker_cli.music_worker as mw_mod
from songmaker_cli.cleanup import DAILY_CLEANUP_HOUR_UTC
from songmaker_cli.constants import AuditAction, LoraStatus
from songmaker_cli.db.models import Album, AuditLog, Job, ReferenceRecording, User, UserLora
from songmaker_cli.job_types import JobFunction, JobStatus, JobType
from songmaker_cli.music_worker import MusicWorker
from songmaker_cli.settings import Settings, get_settings


def _run(coro):
    return asyncio.run(coro)


def _mock_ctx():
    return {"redis": AsyncMock()}


def _make_worker() -> MusicWorker:
    """Fresh worker with DB / dirs / job-validity stubbed."""
    worker = MusicWorker()
    worker.check_job_still_valid = MagicMock(return_value=True)
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


def test_generate_skips_completed_job() -> None:
    worker = _make_worker()
    worker.check_job_still_valid = MagicMock(return_value=False)

    with patch(
        "songmaker_cli.music_worker.run_generation_job", new_callable=AsyncMock,
    ) as mock_run:
        _run(worker.generate(_mock_ctx(), "j1", "s1", "v1", 2, "u1", None, "sft"))

    mock_run.assert_not_called()


def test_generate_runs_queued_job() -> None:
    worker = _make_worker()
    ctx = _mock_ctx()
    with patch(
        "songmaker_cli.music_worker.run_generation_job", new_callable=AsyncMock,
    ) as mock_run:
        _run(worker.generate(ctx, "j1", "s1", "v1", 2, "u1", None, "sft"))

    mock_run.assert_awaited_once()
    kwargs = mock_run.await_args.kwargs
    assert kwargs["redis"] is ctx["redis"]


def test_generate_passes_seed_and_target_model() -> None:
    worker = _make_worker()
    with patch(
        "songmaker_cli.music_worker.run_generation_job", new_callable=AsyncMock,
    ) as mock_run:
        _run(worker.generate(
            _mock_ctx(), "j1", "s1", "v1", 2, "u1", 42, "xl-sft",
        ))

    kwargs = mock_run.await_args.kwargs
    assert kwargs["seed"] == 42
    assert kwargs["target_model"] == "xl-sft"


def test_train_lora_passes_the_explicit_training_configuration_and_target_mode() -> None:
    worker = _make_worker()
    with patch(
        "songmaker_cli.music_worker.run_lora_training_job", new_callable=AsyncMock,
    ) as mock_run:
        _run(worker.train_lora(_mock_ctx(), "j1", "l1", "u1", "turbo"))

    assert mock_run.await_args.kwargs["training_config"] == worker._settings.lora_training_config
    assert mock_run.await_args.kwargs["target_mode"] == "turbo"


def test_lora_training_uses_its_own_timeout() -> None:
    lora_function = next(
        function
        for function in mw_mod.MusicWorkerSettings.functions
        if function.name == JobType.LORA_TRAINING
    )

    assert lora_function.timeout_s == mw_mod._settings.lora_training_job_timeout
    assert mw_mod.MusicWorkerSettings.job_timeout == mw_mod._settings.arq_job_timeout


def test_generate_passes_repaint_params() -> None:
    from songmaker_cli.api_models import RepaintTaskParams

    worker = _make_worker()
    repaint = {
        "src_wav_path": "/x.wav",
        "src_generation_id": "g0",
        "repainting_start": 0.0,
        "repainting_end": 1.0,
        "lyrics": "la",
        "prompt": "rock",
    }
    with patch(
        "songmaker_cli.music_worker.run_generation_job", new_callable=AsyncMock,
    ) as mock_run:
        _run(worker.generate(
            _mock_ctx(), "j1", "s1", "v1", 1, "u1", None, "sft", repaint_params=repaint,
        ))

    kwargs = mock_run.await_args.kwargs
    assert isinstance(kwargs["repaint_params"], RepaintTaskParams)
    assert kwargs["repaint_params"].src_wav_path == "/x.wav"
    assert kwargs["repaint_params"].repainting_end == 1.0


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
        _run(worker.cleanup_files_cron(_mock_ctx()))

    with factory() as session:
        expired_album = (
            session.query(Album)
            .execution_options(include_deleted=True)
            .filter_by(id="expired-album")
            .one_or_none()
        )

    assert expired_album is None
    assert any(str(orphan) in message for message in caplog.messages)


def test_on_startup_calls_recover_on_startup() -> None:
    worker = MusicWorker()
    worker._recover_on_startup = AsyncMock(return_value=0)

    ctx = _mock_ctx()
    with patch("songmaker_cli.logging_config.configure_logging"):
        _run(worker.on_startup(ctx))

    worker._recover_on_startup.assert_called_once_with(ctx)


def test_on_shutdown_disposes_db() -> None:
    worker = MusicWorker()
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)
    worker.get_db_factory = MagicMock(return_value=mock_factory)
    worker._db_engine = MagicMock()

    with patch(
        "songmaker_cli.db.queries.jobs.recover_stale_jobs_by_type", return_value={},
    ):
        _run(worker.on_shutdown(_mock_ctx()))

    worker._db_engine.dispose.assert_called_once()


def test_startup_recovers_music_job_types_and_reconciles_lora_once(tmp_path, pg_factory) -> None:
    factory = pg_factory
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    with factory() as session:
        session.add(User(id="u1", username="u1"))
        session.add_all([
            Job(
                id="cover-1", type=JobType.COVER,
                status=JobStatus.RUNNING,
            ),
            Job(
                id="generate-1", type=JobType.GENERATE,
                status=JobStatus.RUNNING,
            ),
            Job(
                id="lora-job-1", type=JobType.LORA_TRAINING,
                status=JobStatus.RUNNING,
            ),
            Job(
                id="load-model-1", type=JobType.LOAD_MODEL_ON_WORKER,
                status=JobStatus.RUNNING,
            ),
            Job(
                id="download-model-1", type=JobType.DOWNLOAD_MODEL_ON_WORKER,
                status=JobStatus.RUNNING,
            ),
            UserLora(
                id="lora-1", user_id="u1", name="Lora", slug="lora",
                status=LoraStatus.TRAINING, training_job_id="lora-job-1",
            ),
        ])
        session.commit()

    worker = MusicWorker(_settings())
    worker.get_db_factory = MagicMock(return_value=factory)
    worker.audio_dir = MagicMock(return_value=audio_dir)
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)

    with patch("songmaker_cli.logging_config.configure_logging"):
        _run(worker.on_startup({"redis": redis}))

    with factory() as session:
        cover = session.query(Job).filter_by(id="cover-1").one()
        generate = session.query(Job).filter_by(id="generate-1").one()
        lora_job = session.query(Job).filter_by(id="lora-job-1").one()
        load_model = session.query(Job).filter_by(id="load-model-1").one()
        download_model = session.query(Job).filter_by(id="download-model-1").one()
        lora = session.query(UserLora).filter_by(id="lora-1").one()
        audits = session.query(AuditLog).filter_by(
            action=AuditAction.TRAIN_LORA, resource_id="lora-1",
        ).all()

    assert worker.job_types == (
        JobType.GENERATE,
        JobType.LORA_TRAINING,
        JobType.LOAD_MODEL_ON_WORKER,
        JobType.DOWNLOAD_MODEL_ON_WORKER,
    )
    assert cover.status == JobStatus.RUNNING
    for job in (generate, lora_job, load_model, download_model):
        assert job.status == JobStatus.FAILED
        assert job.error_type == "server_restart"
    assert lora.status == LoraStatus.FAILED
    assert len(audits) == 1


def test_queued_music_jobs_survive_worker_restart(tmp_path, pg_factory) -> None:
    factory = pg_factory
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    with factory() as session:
        session.add(User(id="u1", username="u1"))
        session.add_all([
            Job(id="generate-queued", type=JobType.GENERATE, status=JobStatus.QUEUED),
            Job(id="lora-queued", type=JobType.LORA_TRAINING, status=JobStatus.QUEUED),
            Job(
                id="load-model-queued", type=JobType.LOAD_MODEL_ON_WORKER,
                status=JobStatus.QUEUED,
            ),
            Job(
                id="download-model-queued", type=JobType.DOWNLOAD_MODEL_ON_WORKER,
                status=JobStatus.QUEUED,
            ),
            UserLora(
                id="lora-queued", user_id="u1", name="Lora", slug="lora",
                status=LoraStatus.QUEUED, training_job_id="lora-queued",
            ),
        ])
        session.commit()

    worker = MusicWorker()
    worker.get_db_factory = MagicMock(return_value=factory)
    worker.audio_dir = MagicMock(return_value=audio_dir)
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)

    with patch("songmaker_cli.logging_config.configure_logging"):
        _run(worker.on_startup({"redis": redis}))
    _run(worker.on_shutdown({"redis": redis}))

    with factory() as session:
        generate = session.query(Job).filter_by(id="generate-queued").one()
        lora_job = session.query(Job).filter_by(id="lora-queued").one()
        load_model = session.query(Job).filter_by(id="load-model-queued").one()
        download_model = session.query(Job).filter_by(id="download-model-queued").one()
        lora = session.query(UserLora).filter_by(id="lora-queued").one()

    assert generate.status == JobStatus.QUEUED
    assert lora_job.status == JobStatus.QUEUED
    assert load_model.status == JobStatus.QUEUED
    assert download_model.status == JobStatus.QUEUED
    assert lora.status == LoraStatus.QUEUED


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

    _run(worker.cleanup_files_cron(_mock_ctx()))

    with factory() as session:
        job = session.query(Job).filter_by(id="generate-queued").one()

    assert job.status == JobStatus.QUEUED


def test_music_worker_settings_queue_name() -> None:
    from songmaker_cli.constants import ARQ_MUSIC_QUEUE_NAME
    from songmaker_cli.music_worker import MusicWorkerSettings
    assert MusicWorkerSettings.queue_name == ARQ_MUSIC_QUEUE_NAME


def test_music_worker_settings_has_cron() -> None:
    from songmaker_cli.music_worker import MusicWorkerSettings
    names = {job.name for job in MusicWorkerSettings.cron_jobs}
    assert "cron:MusicWorker.cleanup_files_cron" in names
    assert "cron:MusicWorker.generation_retention_cron" in names
    assert "cron:MusicWorker.reference_remnant_cron" in names
    assert "cron:MusicWorker.reference_unused_cron" in names


def test_the_daily_jobs_run_at_the_daily_cleanup_hour() -> None:
    from songmaker_cli.cleanup import DAILY_CLEANUP_HOUR_UTC
    from songmaker_cli.music_worker import MusicWorkerSettings

    daily = {
        job.name: job.hour for job in MusicWorkerSettings.cron_jobs
        if job.name != "cron:MusicWorker.cleanup_files_cron"
    }
    assert daily == {
        "cron:MusicWorker.generation_retention_cron": {DAILY_CLEANUP_HOUR_UTC},
        "cron:MusicWorker.reference_remnant_cron": {DAILY_CLEANUP_HOUR_UTC},
        "cron:MusicWorker.reference_unused_cron": {DAILY_CLEANUP_HOUR_UTC},
    }


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
    # init_db would run the PostgreSQL migrations, which needs a live database.
    worker.get_db_factory = MagicMock(return_value=factory)

    removed = _run(worker.reference_remnant_cron(_mock_ctx()))

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

    changed = _run(worker.reference_unused_cron(_mock_ctx()))

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

    changed = _run(worker.reference_unused_cron(_mock_ctx()))

    assert calls == ["reconcile", "delete"]
    assert received == {"days": 17, "hour": DAILY_CLEANUP_HOUR_UTC, "now": now}
    assert changed == 2 + 1 + 4


def test_music_worker_settings_functions() -> None:
    from songmaker_cli.music_worker import MusicWorkerSettings
    func_names = {f.name for f in MusicWorkerSettings.functions}
    assert JobFunction.GENERATE in func_names
    assert JobFunction.LOAD_MODEL_ON_WORKER in func_names
    assert JobFunction.DOWNLOAD_MODEL_ON_WORKER in func_names
    assert JobFunction.LORA_TRAINING in func_names
    assert len(MusicWorkerSettings.functions) == 4


def test_music_worker_settings_uses_singleton_methods() -> None:
    """The arq Settings shim must expose bound methods of _music_worker."""
    from songmaker_cli.music_worker import MusicWorkerSettings
    for func in MusicWorkerSettings.functions:
        assert func.coroutine.__self__ is mw_mod._music_worker


def test_music_worker_functions_registered_under_job_function_names() -> None:
    """Regression: arq must register class methods under the plain JobFunction
    names, not ``ClassName.method``. Enqueuers send the JobFunction name, and
    arq looks up functions by name — any mismatch silently drops every job.
    """
    from arq.worker import Worker

    from songmaker_cli.music_worker import MusicWorkerSettings

    async def _build_and_inspect() -> set[str]:
        worker = Worker(
            functions=MusicWorkerSettings.functions,
            queue_name=MusicWorkerSettings.queue_name,
            redis_settings=MusicWorkerSettings.redis_settings,
            handle_signals=False,
        )
        return set(worker.functions.keys())

    registered = asyncio.run(_build_and_inspect())
    assert JobFunction.GENERATE in registered
    assert JobFunction.LOAD_MODEL_ON_WORKER in registered
    assert JobFunction.DOWNLOAD_MODEL_ON_WORKER in registered

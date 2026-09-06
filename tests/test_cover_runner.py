"""Dark web-runner coverage for album-cover suggestion jobs."""

from __future__ import annotations

import asyncio
import json
import threading
from io import BytesIO
from pathlib import Path

import pytest
from conftest import override_provider_runtime, use_codex_process_pool
from PIL import Image

import songmaker_cli.cover_runner as cover_runner
from agent_providers.codex import protocol as codex_protocol
from agent_providers.codex.image import CodexImageCliError, CodexImageQuotaError
from agent_providers.codex.pool import CodexProcessPool
from agent_providers.process import CliRunOutcome, CliRunReason
from songmaker_cli.constants import JOB_ERROR_COVER_IMAGE_FAILED, JobStatus, JobType
from songmaker_cli.cowriter.catalog import ProviderRoute
from songmaker_cli.cowriter.dispatch import CoverImageDispatch
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, AlbumCoverSuggestion, Job, Song, User, Version
from songmaker_cli.db.queries import update_job_status
from songmaker_cli.settings import CoverExecutor, Settings


def _settings(executor: CoverExecutor) -> Settings:
    return Settings(
        database_url="postgresql://example",
        redis_url="redis://example",
        session_secret="session-secret",
        songmaker_internal_token="internal-token",
        cover_executor=executor,
    )


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (16, 16), (20, 80, 160)).save(output, format="PNG")
    return output.getvalue()


def _codex_cover_dispatch() -> CoverImageDispatch:
    return CoverImageDispatch(provider="codex", route=ProviderRoute.CLI, model="")


def _cover_job(tmp_path: Path):
    factory = init_test_db(tmp_path / "songmaker.db")
    audio_dir = tmp_path / "audio"
    with factory() as session:
        user = User(id="u1", username="owner", password_hash="hash")
        session.add(user)
        session.flush()
        album = Album(id="album", title="Album", artist="Artist", created_by=user.id)
        song = Song(id="song", album_id=album.id, title="Song", track_number=1)
        version = Version(
            id="version", song_id=song.id, version_number=1, prompt="ambient", lyrics="words",
        )
        job = Job(id="job", type=JobType.COVER, user_id=user.id, album_id=album.id)
        session.add_all([album, song, version, job])
        session.commit()
    return factory, audio_dir, "job"


def test_music_executor_neither_starts_a_cover_run_nor_claims_a_job(tmp_path: Path) -> None:
    factory, audio_dir, job_id = _cover_job(tmp_path)

    claimed = asyncio.run(cover_runner.run_next_cover_job(
        db_factory=factory, audio_dir=audio_dir, settings=_settings(CoverExecutor.MUSIC),
    ))

    with factory() as session:
        assert session.get(Job, job_id).status == JobStatus.QUEUED
    assert claimed is False


def test_cancelled_queued_web_cover_job_is_never_claimed(tmp_path: Path, monkeypatch) -> None:
    factory, audio_dir, job_id = _cover_job(tmp_path)
    with factory() as session:
        assert update_job_status(session, job_id, JobStatus.CANCELLED)
        session.commit()

    def should_not_run(*_args, **_kwargs) -> bytes:
        raise AssertionError("cancelled queued job was started")

    monkeypatch.setattr(cover_runner, "generate_codex_cover_image", should_not_run)

    assert not asyncio.run(cover_runner.run_next_cover_job(
        db_factory=factory, audio_dir=audio_dir, settings=_settings(CoverExecutor.WEB),
    ))

    with factory() as session:
        assert session.get(Job, job_id).status == JobStatus.CANCELLED


def test_web_runner_exclusively_claims_and_publishes_three_suggestions(
    tmp_path: Path, monkeypatch,
) -> None:
    factory, audio_dir, job_id = _cover_job(tmp_path)
    image_started = threading.Event()
    allow_image_return = threading.Event()

    def fake_image_generator(_prompt: str, *, deadline: float, model: str) -> bytes:
        assert deadline > 0
        image_started.set()
        assert allow_image_return.wait(timeout=2)
        return _png_bytes()

    monkeypatch.setattr(cover_runner, "generate_codex_cover_image", fake_image_generator)
    monkeypatch.setattr(
        cover_runner, "cover_image_provider_method", lambda _session: _codex_cover_dispatch(),
    )

    async def run_race() -> tuple[bool, bool]:
        winner = asyncio.create_task(cover_runner.run_next_cover_job(
            db_factory=factory, audio_dir=audio_dir, settings=_settings(CoverExecutor.WEB),
        ))
        assert await asyncio.to_thread(image_started.wait, 1)
        loser = await cover_runner.run_next_cover_job(
            db_factory=factory, audio_dir=audio_dir, settings=_settings(CoverExecutor.WEB),
        )
        allow_image_return.set()
        return await winner, loser

    winner, loser = asyncio.run(run_race())

    with factory() as session:
        job = session.get(Job, job_id)
        suggestions = list(job.album.cover_suggestions)
        assert job.status == JobStatus.COMPLETED
        assert job.progress == 1.0
        assert len(suggestions) == 3
        assert all((audio_dir / item.png_path).is_file() for item in suggestions)
    assert winner is True
    assert loser is False
    assert not list(audio_dir.rglob(".*.staging"))


def test_web_recovery_fails_interrupted_work_cleans_its_group_and_leaves_queue_for_runner(
    tmp_path: Path, monkeypatch,
) -> None:
    factory, audio_dir, running_job_id = _cover_job(tmp_path)
    interrupted_png = audio_dir / "cover-suggestions" / "album" / "interrupted.png"
    interrupted_png.parent.mkdir(parents=True)
    interrupted_png.write_bytes(_png_bytes())
    interrupted_staging_dir = cover_runner._staging_path(
        audio_dir, "album", running_job_id,
    )
    interrupted_staging_dir.mkdir()
    (interrupted_staging_dir / "partial.png").write_bytes(_png_bytes())
    with factory() as session:
        running_job = session.get(Job, running_job_id)
        assert running_job is not None
        assert update_job_status(session, running_job.id, JobStatus.RUNNING)
        session.add(AlbumCoverSuggestion(
            id="interrupted",
            album_id="album",
            job_id=running_job.id,
            png_path="cover-suggestions/album/interrupted.png",
        ))
        session.add(Job(id="queued", type=JobType.COVER, album_id="album", user_id="u1"))
        session.commit()

    assert cover_runner.recover_web_cover_jobs(
        factory, audio_dir, _settings(CoverExecutor.WEB),
    ) == 1

    with factory() as session:
        assert session.get(Job, running_job_id).error_type == "server_restart"
        assert session.get(Job, "queued").status == JobStatus.QUEUED
        assert session.query(AlbumCoverSuggestion).count() == 0
    assert not interrupted_png.exists()
    assert not interrupted_staging_dir.exists()

    def fake_image_generator(*_args, **_kwargs) -> bytes:
        return _png_bytes()

    monkeypatch.setattr(cover_runner, "generate_codex_cover_image", fake_image_generator)
    monkeypatch.setattr(
        cover_runner, "cover_image_provider_method", lambda _session: _codex_cover_dispatch(),
    )
    assert asyncio.run(cover_runner.run_next_cover_job(
        db_factory=factory, audio_dir=audio_dir, settings=_settings(CoverExecutor.WEB),
    ))
    with factory() as session:
        assert session.get(Job, "queued").status == JobStatus.COMPLETED


def test_music_executor_does_not_recover_web_cover_jobs(tmp_path: Path) -> None:
    factory, audio_dir, job_id = _cover_job(tmp_path)
    with factory() as session:
        assert update_job_status(session, job_id, JobStatus.RUNNING)
        session.commit()

    assert cover_runner.recover_web_cover_jobs(
        factory, audio_dir, _settings(CoverExecutor.MUSIC),
    ) == 0
    with factory() as session:
        assert session.get(Job, job_id).status == JobStatus.RUNNING


@pytest.mark.parametrize(
    ("raised", "expected_job_error"),
    (
        (CodexImageCliError(), JOB_ERROR_COVER_IMAGE_FAILED),
        (
            CodexImageQuotaError(
                "You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage "
                "to purchase more credits or try again at Sep 7th, 2026 8:45 PM.",
                retry_at="Sep 7th, 2026 8:45 PM",
            ),
            "Codex usage limit reached, try again after Sep 7th, 2026 8:45 PM.",
        ),
        (
            CodexImageCliError("The requested model is unavailable."),
            "Codex could not draw: The requested model is unavailable.",
        ),
    ),
    ids=("generic-cli-error", "usage-limit", "cli-error-with-message"),
)
def test_web_runner_names_the_cause_in_the_job_error(
    tmp_path: Path,
    monkeypatch,
    raised: Exception,
    expected_job_error: str,
) -> None:
    factory, audio_dir, job_id = _cover_job(tmp_path)
    monkeypatch.setattr(
        cover_runner, "cover_image_provider_method", lambda _session: _codex_cover_dispatch(),
    )

    def fail_image_generator(_prompt: str, *, deadline: float, model: str) -> bytes:
        raise raised

    monkeypatch.setattr(cover_runner, "generate_codex_cover_image", fail_image_generator)

    assert asyncio.run(cover_runner.run_next_cover_job(
        db_factory=factory, audio_dir=audio_dir, settings=_settings(CoverExecutor.WEB),
    ))

    with factory() as session:
        job = session.get(Job, job_id)
        assert job.status == JobStatus.FAILED
        assert job.error == expected_job_error
        assert job.error_type == "cover_suggestion_error"
        assert list(job.album.cover_suggestions) == []


def test_web_runner_reports_the_real_codex_usage_limit_transcript_end_to_end(
    tmp_path: Path, monkeypatch, caplog,
) -> None:
    """Drive the real adapter with a faked CLI process, not a faked image generator."""
    factory, audio_dir, job_id = _cover_job(tmp_path)
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({
        "auth_mode": "chatgpt",
        "last_refresh": "2026-09-05T00:00:00Z",
        "tokens": {
            "id_token": "id-token",
            "access_token": "access-token",
            "account_id": "account-id",
        },
    }))
    override_provider_runtime(codex_cli_auth_file=auth_file)
    process_pool = CodexProcessPool(maximum_processes=8, maximum_image_runs=1)
    transcript = (
        Path(__file__).parent / "fixtures" / "codex-cover-quota-exceeded.jsonl"
    ).read_text()

    def fake_runner(_command, **kwargs) -> CliRunOutcome:
        kwargs["on_spawned"](123)
        kwargs["on_reaped"](123, False)
        return CliRunOutcome(
            started=True,
            spawn_error=None,
            returncode=1,
            stdout=transcript,
            stderr="",
            complete=True,
            became_zombie=False,
            reason=CliRunReason.COMPLETE,
        )

    monkeypatch.setattr(codex_protocol, "run_cli_bounded", fake_runner)
    use_codex_process_pool(monkeypatch, process_pool)
    monkeypatch.setattr(
        cover_runner, "cover_image_provider_method", lambda _session: _codex_cover_dispatch(),
    )
    caplog.set_level("ERROR", logger="songmaker_cli.jobs._runtime")

    assert asyncio.run(cover_runner.run_next_cover_job(
        db_factory=factory, audio_dir=audio_dir, settings=_settings(CoverExecutor.WEB),
    ))

    with factory() as session:
        job = session.get(Job, job_id)
        assert job.status == JobStatus.FAILED
        assert job.error == "Codex usage limit reached, try again after Sep 7th, 2026 8:45 PM."
        assert job.error_type == "cover_suggestion_error"
    assert "You've hit your usage limit" in caplog.text


def _install_abortable_codex_cli(monkeypatch, tmp_path: Path) -> tuple[
    threading.Event,
    threading.Event,
    threading.Event,
    threading.Event,
    CodexProcessPool,
]:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({
        "auth_mode": "chatgpt",
        "last_refresh": "2026-09-05T00:00:00Z",
        "tokens": {
            "id_token": "id-token",
            "access_token": "access-token",
            "account_id": "account-id",
        },
    }))
    spawned = threading.Event()
    abort_requested = threading.Event()
    allow_reap = threading.Event()
    reaped = threading.Event()
    process_pool = CodexProcessPool(maximum_processes=8, maximum_image_runs=1)

    def fake_runner(_command, **kwargs):
        kwargs["on_spawned"](123)
        spawned.set()
        assert kwargs["stdout_line_channel"]._abort_requested.wait(timeout=1)
        abort_requested.set()
        assert allow_reap.wait(timeout=1)
        kwargs["on_reaped"](123, False)
        reaped.set()
        return CliRunOutcome(
            started=True,
            spawn_error=None,
            returncode=-15,
            stdout="",
            stderr="",
            complete=False,
            became_zombie=False,
            reason=CliRunReason.CANCELLED,
        )

    override_provider_runtime(codex_cli_auth_file=auth_file)
    monkeypatch.setattr(codex_protocol, "run_cli_bounded", fake_runner)
    use_codex_process_pool(monkeypatch, process_pool)
    return spawned, abort_requested, allow_reap, reaped, process_pool


def test_web_cancel_reaps_the_codex_process_and_keeps_the_job_cancelled(
    tmp_path: Path, monkeypatch,
) -> None:
    factory, audio_dir, job_id = _cover_job(tmp_path)
    spawned, abort_requested, allow_reap, reaped, process_pool = _install_abortable_codex_cli(
        monkeypatch, tmp_path,
    )
    registry = cover_runner.CoverJobCancellationRegistry()
    monkeypatch.setattr(
        cover_runner, "cover_image_provider_method", lambda _session: _codex_cover_dispatch(),
    )

    async def cancel_running_job() -> bool:
        task = asyncio.create_task(cover_runner.run_next_cover_job(
            db_factory=factory,
            audio_dir=audio_dir,
            settings=_settings(CoverExecutor.WEB),
            cancellation_registry=registry,
        ))
        assert await asyncio.to_thread(spawned.wait, 1)
        with factory() as session:
            assert update_job_status(session, job_id, JobStatus.CANCELLED)
            session.commit()
        assert registry.abort(job_id)
        assert await asyncio.to_thread(abort_requested.wait, 1)
        assert not task.done()
        assert process_pool.reservation_count() == 1
        allow_reap.set()
        return await task

    assert asyncio.run(cancel_running_job())
    assert reaped.is_set()
    assert process_pool.reservation_count() == 0

    with factory() as session:
        job = session.get(Job, job_id)
        assert job.status == JobStatus.CANCELLED
        assert not job.album.cover_suggestions
    assert not list(audio_dir.rglob(".*.staging"))


def test_web_runner_task_cancellation_reaps_the_codex_process(tmp_path: Path, monkeypatch) -> None:
    factory, audio_dir, _job_id = _cover_job(tmp_path)
    spawned, abort_requested, allow_reap, reaped, process_pool = _install_abortable_codex_cli(
        monkeypatch, tmp_path,
    )
    monkeypatch.setattr(
        cover_runner, "cover_image_provider_method", lambda _session: _codex_cover_dispatch(),
    )

    async def cancel_runner_task() -> None:
        task = asyncio.create_task(cover_runner.run_next_cover_job(
            db_factory=factory, audio_dir=audio_dir, settings=_settings(CoverExecutor.WEB),
        ))
        assert await asyncio.to_thread(spawned.wait, 1)
        task.cancel()
        try:
            assert await asyncio.to_thread(abort_requested.wait, 1)
            assert not task.done()
            assert process_pool.reservation_count() == 1
        finally:
            allow_reap.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_runner_task())
    assert reaped.is_set()
    assert process_pool.reservation_count() == 0
    assert not list(audio_dir.rglob(".*.staging"))

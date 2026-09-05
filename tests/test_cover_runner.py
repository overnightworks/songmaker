"""Dark web-runner coverage for album-cover suggestion jobs."""

from __future__ import annotations

import asyncio
import threading
from io import BytesIO
from pathlib import Path

from PIL import Image

import songmaker_cli.cover_runner as cover_runner
from songmaker_cli.constants import JOB_ERROR_COVER_IMAGE_FAILED, JobStatus, JobType
from songmaker_cli.cowriter.catalog import ProviderSetupMethod
from songmaker_cli.cowriter.codex_cli_adapter import CodexImageCliError
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, Job, Song, User, Version
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


def test_web_runner_exclusively_claims_and_publishes_three_suggestions(
    tmp_path: Path, monkeypatch,
) -> None:
    factory, audio_dir, job_id = _cover_job(tmp_path)
    image_started = threading.Event()
    allow_image_return = threading.Event()

    def fake_image_generator(_prompt: str, *, deadline: float) -> bytes:
        assert deadline > 0
        image_started.set()
        assert allow_image_return.wait(timeout=2)
        return _png_bytes()

    monkeypatch.setattr(cover_runner, "generate_codex_cover_image", fake_image_generator)
    monkeypatch.setattr(
        cover_runner, "cover_image_provider_method", lambda: ProviderSetupMethod.CODEX_CLI,
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


def test_web_runner_records_the_shared_cover_error_terminal_state(
    tmp_path: Path, monkeypatch,
) -> None:
    factory, audio_dir, job_id = _cover_job(tmp_path)
    monkeypatch.setattr(
        cover_runner, "cover_image_provider_method", lambda: ProviderSetupMethod.CODEX_CLI,
    )

    def fail_image_generator(_prompt: str, *, deadline: float) -> bytes:
        raise CodexImageCliError()

    monkeypatch.setattr(cover_runner, "generate_codex_cover_image", fail_image_generator)

    assert asyncio.run(cover_runner.run_next_cover_job(
        db_factory=factory, audio_dir=audio_dir, settings=_settings(CoverExecutor.WEB),
    ))

    with factory() as session:
        job = session.get(Job, job_id)
        assert job.status == JobStatus.FAILED
        assert job.error == JOB_ERROR_COVER_IMAGE_FAILED
        assert job.error_type == "cover_suggestion_error"
        assert list(job.album.cover_suggestions) == []

"""Durable cover usage through real publication transactions and migrations."""

from __future__ import annotations

import asyncio
import os
import shutil
import threading
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest
from agent_providers.catalog import ProviderRoute
from alembic import command
from alembic.config import Config
from PIL import Image
from sqlalchemy import create_engine, delete, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from songmaker_cli import cover_runner
from songmaker_cli.constants import JobStatus, JobType
from songmaker_cli.cowriter.routing import CoverImageDispatch
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, AlbumCoverSuggestion, Base, Job, User, aware_timestamp
from songmaker_cli.db.queries.jobs import JobStatusUpdate, count_cover_jobs_since, update_job_status
from songmaker_cli.settings import CoverExecutor, Settings

STARTED = datetime(2026, 10, 18, tzinfo=timezone.utc)
GENERATED_PIXEL = (20, 80, 160)
PREVIOUS_REVISION = "5f4912bc4a31"
ACCOUNTING_REVISION = "1968214a67b1"


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 4), GENERATED_PIXEL).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def accounting_pg_url():
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("TEST_DATABASE_URL not set to PostgreSQL")
    engine = create_engine(url)
    schema = "cover_accounting_" + uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        yield make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


@pytest.fixture(params=["sqlite", "postgresql"])
def accounting_factory(request, tmp_path):
    if request.param == "sqlite":
        factory = init_test_db(tmp_path / "accounting.db")
    else:
        engine = create_engine(request.getfixturevalue("accounting_pg_url"))
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
    yield factory
    factory.kw["bind"].dispose()


@pytest.fixture
def running_cover(accounting_factory, tmp_path, monkeypatch):
    with accounting_factory() as session:
        session.add(User(id="owner", username="owner"))
        session.flush()
        session.add(Album(id="album", title="Album", artist="Artist", created_by="owner"))
        session.flush()
        session.add(Job(
            id="cover", type=JobType.COVER, status=JobStatus.RUNNING,
            album_id="album", user_id="owner", started_at=STARTED,
        ))
        session.commit()
    monkeypatch.setattr(
        cover_runner, "cover_image_provider_method",
        lambda session: CoverImageDispatch(provider="codex", route=ProviderRoute.CLI, model=""),
    )
    monkeypatch.setattr(cover_runner, "generate_codex_cover_image", lambda *a, **kw: _png_bytes())
    return {
        "job_id": "cover", "db_factory": accounting_factory, "audio_dir": tmp_path / "audio",
        "settings": Settings(
            database_url="postgresql://example", redis_url="redis://example",
            session_secret="session-secret", songmaker_internal_token="internal-token",
            cover_executor=CoverExecutor.WEB,
        ),
    }


def _assert_cover_accounting(factory, audio_dir, status):
    with factory() as session:
        job = session.get(Job, "cover")
        assert job.status == status
        assert job.user_id == "owner"
        assert aware_timestamp(job.started_at) == STARTED
        produced = status == JobStatus.COMPLETED
        assert count_cover_jobs_since(session, "album", STARTED) == int(produced)
        suggestions = session.query(AlbumCoverSuggestion).all()
        assert len(suggestions) == int(produced)
        assert len(list(audio_dir.rglob("*.png"))) == int(produced)
        for suggestion in suggestions:
            with Image.open(audio_dir / suggestion.png_path) as published:
                assert published.format == "PNG"
                assert published.getpixel((0, 0)) == GENERATED_PIXEL
        if produced:
            assert job.completed_at is not None
            assert job.progress == 1.0
    assert not list(audio_dir.rglob(".*.staging"))


@pytest.mark.parametrize(
    ("failure", "cancel_task"),
    [("none", False), ("rollback", False), ("staging-cleanup", False),
     ("none", True), ("rollback", True)],
)
def test_publication_cleanup_preserves_only_committed_images(
    accounting_factory, running_cover, monkeypatch, cancel_task, failure,
):
    """1301-F3-C1-CLEANUP / ATOMIC: settle publication before task cleanup."""
    publication_ready = threading.Event()
    allow_publication = threading.Event()

    def hold_publication(session):
        if any(isinstance(row, AlbumCoverSuggestion) for row in session.new):
            publication_ready.set()
            assert allow_publication.wait(10)
            if failure == "rollback":
                raise RuntimeError("publication transaction rejected")

    real_rmtree = shutil.rmtree

    def remove_staging(path, *args, **kwargs):
        if failure == "staging-cleanup" and not kwargs.get("ignore_errors", False):
            raise OSError("staging cleanup unavailable")
        return real_rmtree(path, *args, **kwargs)

    event.listen(accounting_factory, "before_commit", hold_publication)
    monkeypatch.setattr(shutil, "rmtree", remove_staging)

    async def exercise():
        task = asyncio.create_task(cover_runner.run_claimed_cover_suggestion_job(**running_cover))
        try:
            assert await asyncio.to_thread(publication_ready.wait, 10)
            if cancel_task:
                task.cancel()
        finally:
            allow_publication.set()
        if cancel_task:
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task

    try:
        asyncio.run(exercise())
    finally:
        event.remove(accounting_factory, "before_commit", hold_publication)
    _assert_cover_accounting(
        accounting_factory, running_cover["audio_dir"],
        JobStatus.FAILED if failure == "rollback" else JobStatus.COMPLETED,
    )


def test_late_cancellation_preserves_publication_with_a_preloaded_job(
    accounting_factory, running_cover,
):
    """1301-F3-C1-ATOMIC: cached RUNNING state cannot erase committed usage."""
    with accounting_factory() as cancellation:
        cached_job = cancellation.get(Job, "cover")
        assert cached_job.status == JobStatus.RUNNING
        with accounting_factory() as publication:
            assert update_job_status(
                publication, "cover", JobStatusUpdate(JobStatus.COMPLETED, progress=1.0),
            )
            publication.commit()
        assert cached_job.status == JobStatus.RUNNING
        assert not update_job_status(
            cancellation, "cover", JobStatusUpdate(JobStatus.CANCELLED),
        )
        cancellation.commit()
    with accounting_factory() as verification:
        job = verification.get(Job, "cover")
        assert job.status == JobStatus.COMPLETED
        assert job.completed_at is not None
        assert count_cover_jobs_since(verification, "album", STARTED) == 1


@pytest.mark.parametrize("winner", ["publication", "cancellation"])
def test_postgresql_serializes_publication_and_cancellation(
    accounting_factory, running_cover, monkeypatch, winner,
):
    """1301-F3-C1-ATOMIC: the first terminal transition owns image and charge."""
    engine = accounting_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("Row-lock ordering requires PostgreSQL")
    publication_locked = threading.Event()
    allow_publication = threading.Event()
    contender_started = threading.Event()

    def hold_completed_transition(session, context):
        if any(isinstance(row, Job) and row.status == JobStatus.COMPLETED for row in session.dirty):
            publication_locked.set()
            assert allow_publication.wait(10)

    def observe_lock_request(connection, cursor, statement, parameters, context, executemany):
        if (
            "FOR UPDATE" in statement
            and context.execution_options.get("populate_existing")
            and publication_locked.is_set()
        ):
            contender_started.set()

    cancellation_loaded = threading.Event()

    def cancel_cover():
        with accounting_factory() as session:
            cached_job = session.get(Job, "cover")
            assert cached_job.status == JobStatus.RUNNING
            cancellation_loaded.set()
            assert publication_locked.wait(10)
            accepted = update_job_status(session, "cover", JobStatusUpdate(JobStatus.CANCELLED))
            session.commit()
            return accepted

    image_started = threading.Event()
    allow_image = threading.Event()
    image_returned = threading.Event()

    def generate_after_cancellation(*args, **kwargs):
        image_started.set()
        assert allow_image.wait(10)
        image_returned.set()
        return _png_bytes()

    if winner == "cancellation":
        monkeypatch.setattr(cover_runner, "generate_codex_cover_image", generate_after_cancellation)

    async def exercise():
        if winner == "cancellation":
            task = asyncio.create_task(
                cover_runner.run_claimed_cover_suggestion_job(**running_cover),
            )
            try:
                assert await asyncio.to_thread(image_started.wait, 10)
                with accounting_factory() as cancellation:
                    cached_job = cancellation.get(Job, "cover")
                    assert cached_job.status == JobStatus.RUNNING
                    assert update_job_status(
                        cancellation, "cover", JobStatusUpdate(JobStatus.CANCELLED),
                    )
                    cancellation.commit()
            finally:
                allow_image.set()
            await task
            assert image_returned.is_set()
        else:
            contender = asyncio.create_task(asyncio.to_thread(cancel_cover))
            try:
                assert await asyncio.to_thread(cancellation_loaded.wait, 10)
                task = asyncio.create_task(
                    cover_runner.run_claimed_cover_suggestion_job(**running_cover),
                )
                assert await asyncio.to_thread(publication_locked.wait, 10)
                assert await asyncio.to_thread(contender_started.wait, 10)
            finally:
                allow_publication.set()
            await task
            assert not await contender

    if winner == "publication":
        event.listen(engine, "before_cursor_execute", observe_lock_request)
        event.listen(accounting_factory, "after_flush", hold_completed_transition)
    try:
        asyncio.run(exercise())
    finally:
        if winner == "publication":
            event.remove(engine, "before_cursor_execute", observe_lock_request)
            event.remove(accounting_factory, "after_flush", hold_completed_transition)
    _assert_cover_accounting(
        accounting_factory, running_cover["audio_dir"],
        JobStatus.COMPLETED if winner == "publication" else JobStatus.CANCELLED,
    )


@pytest.mark.parametrize("status", list(JobStatus))
def test_album_deletion_retains_cover_history(accounting_factory, running_cover, status):
    """1301-F3-C1-DURABLE: album deletion removes suggestions, never job history."""
    with accounting_factory() as session:
        session.get(Job, "cover").status = status
        if status == JobStatus.COMPLETED:
            session.add(AlbumCoverSuggestion(
                id="suggestion", album_id="album", job_id="cover",
                png_path="cover-suggestions/album/suggestion.png",
            ))
        session.commit()
        session.execute(delete(Album).where(Album.id == "album"))
        session.commit()
    with accounting_factory() as session:
        job = session.get(Job, "cover")
        assert job.album_id is None
        assert job.user_id == "owner"
        assert job.status == status
        assert aware_timestamp(job.started_at) == STARTED
        assert session.query(AlbumCoverSuggestion).count() == 0


def test_migration_preserves_usage_across_upgrade_album_deletion_and_downgrade(accounting_pg_url):
    """1301-F3-C1-DURABLE: change the FK without erasing existing or orphaned jobs."""
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        accounting_pg_url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(accounting_pg_url)
    factory = sessionmaker(bind=engine)
    try:
        with factory() as session:
            # The revision under test predates the cutover: its users carry a password hash.
            session.execute(text(
                "INSERT INTO users (id, username, password_hash, role, is_active, created_at,"
                " updated_at) VALUES ('owner', 'owner', 'x', 'user', true, now(), now())"
            ))
            session.add_all([
                Album(id=album_id, title=album_id, artist="Artist", created_by="owner")
                for album_id in ("deleted", "retained")
            ])
            session.flush()
            session.add_all([
                Job(id=f"{album_id}-{status}", type=JobType.COVER, status=status,
                    user_id="owner", album_id=album_id, started_at=STARTED)
                for album_id in ("deleted", "retained") for status in JobStatus
            ])
            session.commit()
        command.upgrade(config, ACCOUNTING_REVISION)
        with factory() as session:
            assert session.query(Job).count() == 2 * len(JobStatus)
            session.execute(delete(Album).where(Album.id == "deleted"))
            session.commit()
        for revision in (ACCOUNTING_REVISION, PREVIOUS_REVISION, ACCOUNTING_REVISION):
            if revision == PREVIOUS_REVISION:
                command.downgrade(config, revision)
            else:
                command.upgrade(config, revision)
            fk = next(
                fk for fk in inspect(engine).get_foreign_keys("jobs")
                if fk["constrained_columns"] == ["album_id"]
            )
            assert fk["options"]["ondelete"] == (
                "CASCADE" if revision == PREVIOUS_REVISION else "SET NULL"
            )
            with factory() as session:
                assert session.query(Job).count() == 2 * len(JobStatus)
                for job in session.query(Job):
                    original_album, original_status = job.id.split("-", 1)
                    assert job.album_id == (None if original_album == "deleted" else "retained")
                    assert job.status == original_status
                    assert job.user_id == "owner"
                    assert aware_timestamp(job.started_at) == STARTED
    finally:
        engine.dispose()

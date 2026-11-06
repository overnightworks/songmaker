"""Durable cover usage through real publication transactions and migrations."""

from __future__ import annotations

import asyncio
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest
from agent_runtime_client.backend.fake_gateway import picture
from alembic import command
from alembic.config import Config
from PIL import Image
from sqlalchemy import create_engine, delete, event, inspect, text
from sqlalchemy.orm import sessionmaker
from support.cowriter_gateway import HeldGateway, attach_cowriter_gateway
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli import cover_runner
from songmaker_cli.constants import JobStatus, JobType
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, AlbumCoverSuggestion, Job, User, aware_timestamp
from songmaker_cli.db.queries.jobs import JobStatusUpdate, count_cover_jobs_since, update_job_status

STARTED = datetime(2026, 10, 18, tzinfo=timezone.utc)
GENERATED_PIXEL = (20, 80, 160)
PREVIOUS_REVISION = "5f4912bc4a31"
ACCOUNTING_REVISION = "1968214a67b1"


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 4), GENERATED_PIXEL).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def accounting_factory(database_pg_factory, tmp_path):
    if database_pg_factory is not None:
        yield database_pg_factory
        return
    factory = init_test_db(tmp_path / "accounting.db")
    yield factory
    factory.kw["bind"].dispose()


@dataclass
class RunningCover:
    """One RUNNING cover job of ``owner`` on an app whose gateway draws ``gateway``'s picture."""

    app: object
    audio_dir: Path
    gateway: HeldGateway

    def run(self):
        return cover_runner.run_claimed_cover_suggestion_job(self.app, "cover")


@pytest.fixture
def running_cover(accounting_factory, tmp_path):
    with accounting_factory() as session:
        session.add(User(id="owner", username="owner"))
        session.flush()
        session.add(Album(id="album", title="Album", artist="Artist", created_by="owner"))
        session.commit()
    ctx = make_router_ctx(tmp_path, db=accounting_factory)
    client = web_client(make_router_app(ctx, user=make_authenticated_user("owner")))
    stack = attach_cowriter_gateway(client, accounting_factory, tmp_path, "owner")
    gateway = HeldGateway(picture(_png_bytes()))
    gateway.released.set()
    stack.uses(gateway)
    with accounting_factory() as session:
        session.add(Job(
            id="cover", type=JobType.COVER, status=JobStatus.RUNNING,
            album_id="album", user_id="owner", session_id=stack.session_id, started_at=STARTED,
        ))
        session.commit()
    return RunningCover(client.app, ctx.audio_dir, gateway)


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
        task = asyncio.create_task(running_cover.run())
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
    # A cancelled web task leaves its job RUNNING for startup recovery to fail.
    expected_status = (
        JobStatus.RUNNING if cancel_task and failure == "rollback"
        else JobStatus.FAILED if failure == "rollback"
        else JobStatus.COMPLETED
    )
    _assert_cover_accounting(accounting_factory, running_cover.audio_dir, expected_status)


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


@pytest.mark.parametrize(
    "database_backend", ["postgresql"], indirect=True,
)
@pytest.mark.parametrize("winner", ["publication", "cancellation"])
def test_postgresql_serializes_publication_and_cancellation(
    accounting_factory, running_cover, winner,
):
    """1301-F3-C1-ATOMIC: the first terminal transition owns image and charge."""
    engine = accounting_factory.kw["bind"]
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

    held = running_cover.gateway
    if winner == "cancellation":
        held.released.clear()

    async def exercise():
        if winner == "cancellation":
            task = asyncio.create_task(
                running_cover.run(),
            )
            try:
                assert await asyncio.to_thread(held.received.wait, 10)
                with accounting_factory() as cancellation:
                    cached_job = cancellation.get(Job, "cover")
                    assert cached_job.status == JobStatus.RUNNING
                    assert update_job_status(
                        cancellation, "cover", JobStatusUpdate(JobStatus.CANCELLED),
                    )
                    cancellation.commit()
            finally:
                held.released.set()
            await task
            assert len(held.requests) == 1
        else:
            contender = asyncio.create_task(asyncio.to_thread(cancel_cover))
            try:
                assert await asyncio.to_thread(cancellation_loaded.wait, 10)
                task = asyncio.create_task(
                    running_cover.run(),
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
        accounting_factory, running_cover.audio_dir,
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


def _seed_owner_with_jobs_on_two_albums(factory) -> None:
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
        # Named columns only: the ORM Job also writes columns later revisions add.
        session.execute(
            text(
                "INSERT INTO jobs (id, type, status, progress, user_id, album_id,"
                " heartbeat_at, started_at) VALUES (:id, :type, :status, 0.0, 'owner',"
                " :album_id, :started_at, :started_at)"
            ),
            [
                {"id": f"{album_id}-{status}", "type": JobType.COVER, "status": status,
                 "album_id": album_id, "started_at": STARTED}
                for album_id in ("deleted", "retained") for status in JobStatus
            ],
        )
        session.commit()


def test_migration_preserves_usage_across_upgrade_album_deletion_and_downgrade(
    empty_postgresql_url,
):
    """1301-F3-C1-DURABLE: change the FK without erasing existing or orphaned jobs."""
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        empty_postgresql_url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(empty_postgresql_url)
    factory = sessionmaker(bind=engine)
    try:
        _seed_owner_with_jobs_on_two_albums(factory)
        command.upgrade(config, ACCOUNTING_REVISION)
        with factory() as session:
            assert session.execute(text("SELECT count(*) FROM jobs")).scalar() == 2 * len(JobStatus)
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
                jobs = session.execute(text(
                    "SELECT id, album_id, status, user_id, started_at FROM jobs"
                )).all()
                assert len(jobs) == 2 * len(JobStatus)
                for job in jobs:
                    original_album, original_status = job.id.split("-", 1)
                    assert job.album_id == (None if original_album == "deleted" else "retained")
                    assert job.status == original_status
                    assert job.user_id == "owner"
                    assert aware_timestamp(job.started_at) == STARTED
    finally:
        engine.dispose()

"""A cover job's reference to the session that asked: where it ends."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from support.web_app import TEST_SECRET, make_fake_redis

from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS
from songmaker_cli.db.models import Album, AlbumCoverSuggestion, Job, User, UserSession
from songmaker_cli.db.queries.auth import delete_expired_sessions, delete_session
from songmaker_cli.db.queries.jobs import (
    JobStatusUpdate,
    recover_stale_jobs_by_type,
    update_job_status,
)
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.lifecycle import reap_stale_jobs

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
SESSION_ID = "s" * 43


@pytest.fixture
def ctx(tmp_path: Path, pg_factory) -> AppContext:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    with pg_factory() as session:
        session.add(User(id="u1", username="u1", role="user"))
        session.flush()
        session.add(Album(id="alb", title="A", artist="B", created_by="u1"))
        session.add(
            UserSession(
                id=SESSION_ID,
                user_id="u1",
                expires_at=NOW + timedelta(days=1),
            )
        )
        session.commit()
    return AppContext(
        db=pg_factory,
        audio_dir=audio_dir,
        data_dir=tmp_path / "data",
        signing_key=TEST_SECRET,
        redis=make_fake_redis(),
    )


def _add_job_asked_by_the_session(
    ctx: AppContext, *, status: str, heartbeat_at: datetime | None = None
) -> None:
    with ctx.db() as session:
        kwargs = {} if heartbeat_at is None else {"heartbeat_at": heartbeat_at}
        session.add(
            Job(
                id="job",
                type=JobType.COVER,
                status=status,
                album_id="alb",
                user_id="u1",
                session_id=SESSION_ID,
                **kwargs,
            )
        )
        session.commit()


def _reference(ctx: AppContext) -> str | None:
    with ctx.db() as session:
        return session.get(Job, "job").session_id


@pytest.mark.parametrize(
    "terminal",
    [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED],
)
def test_a_job_that_reaches_a_terminal_status_forgets_its_session(ctx, terminal):
    _add_job_asked_by_the_session(ctx, status=JobStatus.RUNNING)
    with ctx.db() as session:
        update_job_status(session, "job", JobStatusUpdate(terminal))
        session.commit()
    assert _reference(ctx) is None


def test_a_job_that_goes_on_running_keeps_its_session(ctx):
    _add_job_asked_by_the_session(ctx, status=JobStatus.QUEUED)
    with ctx.db() as session:
        update_job_status(session, "job", JobStatusUpdate(JobStatus.RUNNING))
        session.commit()
    assert _reference(ctx) == SESSION_ID


def test_the_bulk_recovery_at_start_clears_the_session(ctx):
    _add_job_asked_by_the_session(ctx, status=JobStatus.RUNNING)
    with ctx.db() as session:
        recover_stale_jobs_by_type(session, {JobType.COVER: {JobStatus.RUNNING}})
        session.commit()
    assert _reference(ctx) is None


def test_the_reaper_clears_the_session_of_a_job_it_fails(ctx):
    dead = NOW - timedelta(seconds=JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS + 60)
    _add_job_asked_by_the_session(ctx, status=JobStatus.RUNNING, heartbeat_at=dead)
    assert reap_stale_jobs(ctx, now=NOW) == 1
    assert _reference(ctx) is None


@pytest.mark.parametrize("ending", ["logout", "expiry"])
def test_a_session_that_ends_keeps_the_job_and_its_suggestions(ctx, ending):
    _add_job_asked_by_the_session(ctx, status=JobStatus.RUNNING)
    with ctx.db() as session:
        session.add(
            AlbumCoverSuggestion(
                id="sug",
                album_id="alb",
                job_id="job",
                png_path="p.png",
            )
        )
        session.query(UserSession).update({"expires_at": datetime(2000, 1, 1, tzinfo=timezone.utc)})
        if ending == "logout":
            delete_session(session, SESSION_ID)
        else:
            delete_expired_sessions(session)
        session.commit()
    with ctx.db() as session:
        assert session.get(Job, "job").session_id is None
        assert session.get(AlbumCoverSuggestion, "sug") is not None

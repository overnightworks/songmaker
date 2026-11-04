"""PostgreSQL contract of the stale-job reaper and a cover job's session reference."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import OperationalError
from support.web_app import make_authenticated_user

from songmaker_cli.constants import JobStatus, JobType
from songmaker_cli.cover_suggestions import (
    CoverSuggestionSessionEndedError,
    request_cover_suggestions,
)
from songmaker_cli.db.models import Album, Job, User, UserSession
from songmaker_cli.db.queries import jobs as job_queries
from songmaker_cli.db.queries.jobs import (
    JobStatusUpdate,
    create_job,
    recover_stale_jobs_by_age_and_type,
    update_job_heartbeat,
    update_job_status,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"),
    reason="No PostgreSQL URL",
)


def test_a_reaper_that_loses_its_race_leaves_the_competitors_row_and_session(
    pg_factory,
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    with pg_factory() as session:
        session.add(User(id="reaper-user", username="reaper-user"))
        session.flush()
        asking_session = UserSession(user_id="reaper-user", expires_at=now + timedelta(days=1))
        session.add(asking_session)
        session.flush()
        job = create_job(session, JobType.COVER, session_id=asking_session.id)
        update_job_status(session, job.id, JobStatusUpdate(JobStatus.RUNNING))
        job.heartbeat_at = now - timedelta(hours=1)
        session.commit()
        job_id, asking_session_id = job.id, asking_session.id

    def competing_heartbeat(candidate: Job) -> None:
        if candidate.id == job_id:
            with pg_factory() as other:
                update_job_heartbeat(other, job_id)
                other.commit()

    monkeypatch.setattr(job_queries, "_before_stale_job_recovery_update", competing_heartbeat)

    with pg_factory() as session:
        assert recover_stale_jobs_by_age_and_type(session, now=now) == {}
        session.commit()

    with pg_factory() as session:
        job = session.get(Job, job_id)
        assert job.status == JobStatus.RUNNING
        assert job.heartbeat_at > now - timedelta(minutes=1)
        assert job.session_id == asking_session_id


def test_an_ended_session_is_refused_on_postgresql_without_a_job_or_log_trace(
    pg_factory, caplog: pytest.LogCaptureFixture,
) -> None:
    ended_session_id = "e" * 43
    with pg_factory() as session:
        session.add(User(id="asker", username="asker"))
        session.add(Album(id="pg-album", title="T", artist="A", created_by="asker"))
        session.commit()
    caplog.set_level(logging.DEBUG)

    with pg_factory() as session:
        with pytest.raises(CoverSuggestionSessionEndedError) as refusal:
            request_cover_suggestions(
                session, "pg-album", make_authenticated_user("asker"),
                session_id=ended_session_id,
            )
        session.rollback()

    assert refusal.value.status_code == 401
    with pg_factory() as session:
        assert session.query(Job).count() == 0
    assert ended_session_id not in caplog.text


def test_a_live_session_row_cannot_be_deleted_until_the_job_that_references_it_commits(
    pg_factory,
) -> None:
    from sqlalchemy import text

    with pg_factory() as session:
        session.add(User(id="asker", username="asker"))
        session.add(Album(id="pg-album", title="T", artist="A", created_by="asker"))
        asking = UserSession(
            user_id="asker", expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        session.add(asking)
        session.commit()
        asking_id = asking.id

    with pg_factory() as admitting:
        job = request_cover_suggestions(
            admitting, "pg-album", make_authenticated_user("asker"), session_id=asking_id,
        )
        with pg_factory() as logout:
            logout.execute(text("SET LOCAL lock_timeout = '300ms'"))
            with pytest.raises(OperationalError):
                logout.execute(delete(UserSession).where(UserSession.id == asking_id))
        admitting.commit()
        job_id = job.id

    with pg_factory() as session:
        session.execute(delete(UserSession).where(UserSession.id == asking_id))
        session.commit()
        assert session.get(Job, job_id).session_id is None

"""PostgreSQL contract of the stale-job reaper and a cover job's session reference."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from songmaker_cli.constants import JobStatus, JobType
from songmaker_cli.db.models import Job, User, UserSession
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

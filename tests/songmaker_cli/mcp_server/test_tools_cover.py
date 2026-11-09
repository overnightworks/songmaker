"""The cover tool queues a job through the album admission owner, as the asking session."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from support.cover_album_world import album_owner, seed_cover_albums

from songmaker_cli.db.models import Job
from songmaker_cli.db.queries.auth import create_session
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.mcp_server import tools


@pytest.fixture
def db_session(pg_factory):
    with pg_factory() as session:
        seed_cover_albums(session)
        session.commit()
        yield session


def _signed_in(session, user_id: str) -> str:
    """A browser session of ``user_id``: the cover tool runs only as one."""
    record = create_session(session, user_id, datetime.now(timezone.utc) + timedelta(hours=1))
    session.commit()
    return record.id


def test_suggest_album_cover_queues_a_cover_job(db_session):
    owner = album_owner(db_session)

    result = tools.tool_suggest_album_cover(
        db_session, owner, album_id="alice-album", session_id=_signed_in(db_session, owner.id),
    )

    assert result.status == JobStatus.QUEUED
    assert result.message == "Cover suggestion queued."
    job = db_session.query(Job).filter_by(id=result.job_id).one()
    assert (job.type, job.album_id) == (JobType.COVER, "alice-album")


def test_an_eleventh_cover_suggestion_of_a_day_queues_a_job(db_session):
    owner = album_owner(db_session)
    for number in range(11):
        db_session.add(Job(
            id=f"cover-job-{number}", type=JobType.COVER, status=JobStatus.COMPLETED,
            album_id="alice-album", user_id=owner.id,
        ))
    db_session.commit()

    result = tools.tool_suggest_album_cover(
        db_session, owner, album_id="alice-album", session_id=_signed_in(db_session, owner.id),
    )

    assert result.status == JobStatus.QUEUED
    assert db_session.query(Job).filter_by(id=result.job_id).one().type == JobType.COVER


@pytest.mark.parametrize(
    ("album_id", "existing_status", "message"),
    [
        ("missing", None, "Album not found"),
        ("alice-album", JobStatus.QUEUED, "Cover suggestions are already being generated"),
    ],
)
def test_suggest_album_cover_surfaces_the_admission_owner_errors(
    db_session, album_id, existing_status, message,
):
    owner = album_owner(db_session)
    if existing_status is not None:
        db_session.add(Job(
            id="cover-job", type=JobType.COVER, status=existing_status,
            album_id="alice-album", user_id=owner.id,
        ))
        db_session.commit()
    session_id = _signed_in(db_session, owner.id)

    with pytest.raises(tools.MCPToolError, match=message):
        tools.tool_suggest_album_cover(
            db_session, owner, album_id=album_id, session_id=session_id,
        )


def test_suggest_album_cover_refuses_a_caller_without_a_browser_session(db_session):
    """A tool call outside a bound web turn fails closed: a tool error and no job."""
    owner = album_owner(db_session)

    with pytest.raises(tools.MCPToolError, match="need a browser login"):
        tools.tool_suggest_album_cover(
            db_session, owner, album_id="alice-album", session_id=None,
        )

    assert db_session.query(Job).count() == 0

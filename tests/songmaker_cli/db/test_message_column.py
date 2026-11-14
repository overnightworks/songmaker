"""The column type that stores a `Message`: checked on write, shape-checked on read."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import StatementError

from songmaker_cli.db.models import Job
from songmaker_cli.db.queries.jobs import get_job
from songmaker_cli.messages import Message, message


def _add_queued_job(session, job_id: str, wait: Message | None) -> None:
    session.add(Job(id=job_id, type="generate", status="queued", queue_reason_message=wait))
    session.flush()


def _stored_as_sql_null(session, job_id: str) -> bool:
    return session.execute(
        sa.text("SELECT queue_reason_message IS NULL FROM jobs WHERE id = :id"), {"id": job_id},
    ).scalar_one()


def test_a_message_is_stored_and_read_back_equal(pg_factory):
    wait = message("jobWait.voiceTraining")
    with pg_factory() as session:
        _add_queued_job(session, "j1", wait)
        session.commit()
    with pg_factory() as session:
        assert get_job(session, "j1").queue_reason_message == wait


@pytest.mark.parametrize(
    "wrong",
    [
        pytest.param(Message(key="jobWait.noSuchKey", values={}), id="unknown-key"),
        pytest.param(
            Message(key="jobWait.voiceTraining", values={"extra": "gap"}), id="gap-the-key-lacks",
        ),
        pytest.param(Message(key="jobRefusal.hourlyLimit", values={}), id="gaps-missing"),
    ],
)
def test_a_wrong_key_or_wrong_gaps_raise_on_write_and_store_nothing(pg_factory, wrong):
    with pg_factory() as session:
        with pytest.raises(StatementError):
            _add_queued_job(session, "j1", wrong)
        session.rollback()
        assert session.query(Job).count() == 0


def test_reading_an_unknown_key_only_checks_the_shape(pg_factory):
    with pg_factory() as session:
        session.execute(sa.text(
            "INSERT INTO jobs (id, type, status, progress, heartbeat_at, started_at, "
            "queue_reason_message) VALUES ('old', 'generate', 'queued', 0, CURRENT_TIMESTAMP, "
            "CURRENT_TIMESTAMP, CAST('{\"key\": \"jobWait.retired\", \"values\": {}}' AS json))"
        ))
        session.commit()
    with pg_factory() as session:
        assert get_job(session, "old").queue_reason_message == Message(
            key="jobWait.retired", values={},
        )


def test_no_message_is_sql_null_when_added_without_one_and_when_cleared(pg_factory):
    with pg_factory() as session:
        _add_queued_job(session, "without", None)
        _add_queued_job(session, "cleared", message("jobWait.voiceTraining"))
        get_job(session, "cleared").queue_reason_message = None
        session.flush()
        assert _stored_as_sql_null(session, "without")
        assert _stored_as_sql_null(session, "cleared")

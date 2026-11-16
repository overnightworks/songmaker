"""A co-writer tool edit never commits after its turn's chat job was cancelled."""

from __future__ import annotations

import asyncio
import threading

from agents.tools import Principal
from sqlalchemy import text

from songmaker_cli.agent.tools import CallingTurn, bound_to_turn, cowriter_hand_tools
from songmaker_cli.db.models import Album, Job, Song, User
from songmaker_cli.db.queries.jobs import JobStatusUpdate, update_job_status
from songmaker_cli.job_types import JobStatus, JobType


def _seed_a_running_turn(factory) -> tuple[str, str]:
    with factory() as session:
        session.add(User(id="writer", username="writer", role="user"))
        session.flush()
        session.add(Album(id="album-w", title="Album", artist="writer", created_by="writer"))
        session.add(Song(id="song-w", title="Before", album_id="album-w", track_number=1))
        job = Job(type=JobType.CHAT, user_id="writer", status=JobStatus.RUNNING)
        session.add(job)
        session.commit()
        return job.id, "song-w"


def _rename(factory, job_id: str, outcomes: list) -> None:
    tool = next(t for t in cowriter_hand_tools(factory) if t.declaration.name == "rename_song")
    with bound_to_turn(CallingTurn("session", job_id)):
        outcomes.append(asyncio.run(
            tool.handler(Principal(iss="issuer.test", sub="writer"),
                         {"song_id": "song-w", "title": "After"}),
        ))


def _count(factory, statement) -> int:
    with factory() as observer:  # why: pg_stat_activity is fixed within one transaction.
        return observer.execute(statement).scalar_one()


def _wait_until_the_edit_waits_on_a_lock_or_ends(factory, edit: threading.Thread) -> None:
    waiting = text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'")
    while edit.is_alive() and not _count(factory, waiting):
        threading.Event().wait(0.01)


def test_an_edit_waiting_on_a_cancel_that_commits_first_leaves_the_song_unchanged(pg_factory):
    job_id, song_id = _seed_a_running_turn(pg_factory)
    outcomes: list = []
    with pg_factory() as canceller:
        assert update_job_status(canceller, job_id, JobStatusUpdate(JobStatus.CANCELLED))
        edit = threading.Thread(target=_rename, args=(pg_factory, job_id, outcomes))
        edit.start()
        _wait_until_the_edit_waits_on_a_lock_or_ends(pg_factory, edit)
        canceller.commit()
    edit.join(timeout=30)

    with pg_factory() as session:
        assert session.get(Song, song_id).title == "Before"
    assert [outcome.is_error for outcome in outcomes] == [True]

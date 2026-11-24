"""Queued score jobs for tests that claim or run them."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import fakeredis
import pytest
from support.web_app import SettledFakeAsyncRedis
from tandem import wake_channel

from songmaker_cli.constants import REDIS_KEY_PREFIX
from songmaker_cli.db.models import Album, Generation, Job, Song, User, Version
from songmaker_cli.db.queries.jobs import create_job
from songmaker_cli.job_payloads import ScorePayload
from songmaker_cli.job_queue import JobQueue
from songmaker_cli.job_types import JobType, WorkerLivenessSignal
from songmaker_cli.scoring.models import SongScores
from songmaker_cli.scoring.subprocess_runner import get_scorer_process, set_scorer_process
from songmaker_cli.timestamps import utcnow
from songmaker_cli.worker_liveness import worker_kind_leases

SUBSCRIBED_WITHIN_SECONDS = 5
A_TAKE_THAT_DOES_NOT_EXIST = ScorePayload(gen_id="no-such-take")


def queued_score_job(
    session,
    *,
    payload: ScorePayload | None = A_TAKE_THAT_DOES_NOT_EXIST,
    due_in: float = 0,
) -> Job:
    """A queued score job whose wait ends ``due_in`` seconds from now.

    The default payload names a take that does not exist, so a run of the job ends at once, failed.
    """
    job = create_job(session, JobType.SCORE, payload=payload)
    job.run_after = utcnow() + timedelta(seconds=due_in)
    session.flush()
    return job


class ScoringRedis(SettledFakeAsyncRedis):
    """The Redis a generation job dispatches an auto-score job through.

    A scoring worker holds its lease while it runs; ``woken_queues`` reads what was
    published on the app's wake channel since this Redis was made.
    """

    def __init__(self, *, worker_running: bool = True) -> None:
        super().__init__()
        if worker_running:
            scoring_leases = worker_kind_leases(self, WorkerLivenessSignal.SCORING)
            asyncio.run(scoring_leases.renew("scoring-worker"))
        self._listener = fakeredis.FakeRedis(server=self.server).pubsub(
            ignore_subscribe_messages=False,
        )
        self._listener.subscribe(wake_channel(REDIS_KEY_PREFIX))
        self._listener.get_message(timeout=SUBSCRIBED_WITHIN_SECONDS)  # the confirmation

    def woken_queues(self) -> list[JobQueue]:
        woken: list[JobQueue] = []
        while (wake := self._listener.get_message()) is not None:
            woken += [queue for queue in JobQueue if wake["data"].endswith(queue.encode())]
        return woken


def a_scoreable_take(factory, audio_dir: Path) -> str:
    """Store a take with an audio file; returns its id."""
    with factory() as session:
        session.add(User(id="u1", username="user1", role="user"))
        session.flush()
        session.add(Album(id="alb1", title="Rock", artist="Band", created_by="u1"))
        session.add(Song(id="s1", title="Song One", album_id="alb1", track_number=1))
        session.add(Version(id="v1", song_id="s1", version_number=1, prompt="rock", bpm=120))
        session.add(Generation(
            id="g1", song_id="s1", version_id="v1", generation_number=1,
            mp3_path="user1/g1.mp3", seed=42,
        ))
        session.commit()
    mp3 = audio_dir / "user1" / "g1.mp3"
    mp3.parent.mkdir(parents=True, exist_ok=True)
    mp3.write_bytes(b"audio")
    return "g1"


@pytest.fixture
def installed_scorer_restored() -> Iterator[None]:
    """The scorer installed before the test is back after it, whoever installed another."""
    try:
        installed_before = get_scorer_process()
    except RuntimeError:
        installed_before = None
    yield
    set_scorer_process(installed_before)


@pytest.fixture
def scorer_requests(installed_scorer_restored: None) -> MagicMock:
    """The ``score`` of the scorer the worker hands its audio to, in place of the child process.

    It answers every request with an empty result; the scorer installed before is back after.
    """
    scorer = MagicMock()
    scorer.score.return_value = SongScores()
    set_scorer_process(scorer)
    return scorer.score

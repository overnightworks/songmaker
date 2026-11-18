"""A job names the process that runs it; only an owner read as gone ends its jobs."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import fakeredis
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import event, text
from support.job_owner import an_owner, create_job_of_unstamped_owner
from support.web_app import (
    arrange_fake_async_redis,
    make_authenticated_user,
    make_fake_redis,
    seed_user,
    settle_owner_leases,
)
from tandem import Liveness

from songmaker_cli.api_helpers import create_job_with_rate_limit
from songmaker_cli.constants import SETTING_MAX_QUEUE_DEPTH
from songmaker_cli.db.models import Job
from songmaker_cli.db.queries.jobs import (
    JOB_ERROR_SERVER_RESTARTED,
    JobStatusUpdate,
    active_job_owner_stamps,
    claim_next_cover_job,
    create_job,
    recover_jobs_of_dead_owners,
    recover_stale_jobs_by_age_and_type,
    update_job_status,
)
from songmaker_cli.db.queries.rate_limits import upsert_rate_limit_setting
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.messages import message
from songmaker_cli.refusals import Refusal
from songmaker_cli.timestamps import utcnow
from songmaker_cli.worker_liveness import JobOwnerStamp, owner_leases

GONE = "owner-gone"
HERE = "owner-here"
UNREAD = "owner-unread"
PERSON = make_authenticated_user("person", username="person")


def _running_job(
    session, job_type: JobType, owner_id: str | None, user_id: str | None = None,
    *, generation: str | None = None,
) -> str:
    if owner_id is None:
        job = create_job(session, job_type, user_id=user_id)
    elif generation is None:
        job = create_job_of_unstamped_owner(session, job_type, owner_id, user_id=user_id)
    else:
        job = create_job(
            session, job_type, owner=an_owner(owner_id, generation), user_id=user_id,
        )
    assert update_job_status(session, job.id, JobStatusUpdate(JobStatus.RUNNING))
    return job.id


def _unstamped(owner_id: str) -> JobOwnerStamp:
    return JobOwnerStamp(owner_id, None)


def _outcome(session, job_id: str) -> tuple[str, str | None]:
    job = session.get(Job, job_id)
    session.refresh(job)
    return job.status, job.error_type


def test_only_the_jobs_of_a_dead_owner_fail_with_the_restart_verdict(pg_factory) -> None:
    with pg_factory() as session:
        gone = _running_job(session, JobType.CHAT, GONE)
        gone_cover = _running_job(session, JobType.COVER, GONE)
        here = _running_job(session, JobType.CHAT, HERE)
        unread = _running_job(session, JobType.CHAT, UNREAD)
        missing_from_the_map = _running_job(session, JobType.CHAT, "owner-not-asked")
        unowned = _running_job(session, JobType.CHAT, None)

        recovered = recover_jobs_of_dead_owners(session, {
            _unstamped(GONE): Liveness.GONE,
            _unstamped(HERE): Liveness.ALIVE,
            _unstamped(UNREAD): Liveness.UNKNOWN,
        })

        assert recovered == {JobType.CHAT: 1, JobType.COVER: 1}
        assert [_outcome(session, job_id) for job_id in (gone, gone_cover)] == [
            (JobStatus.FAILED, JOB_ERROR_SERVER_RESTARTED.error_type),
        ] * 2
        still_running = (here, unread, missing_from_the_map)
        assert [_outcome(session, job_id)[0] for job_id in still_running] == [JobStatus.RUNNING] * 3
        assert _outcome(session, unowned)[0] == JobStatus.RUNNING


def test_a_failed_job_stores_its_message(pg_factory) -> None:
    with pg_factory() as session:
        job = create_job(session, JobType.CHAT)
        failure = message("jobFailure.workerReported", cause="ACE-Step down")
        update_job_status(
            session, job.id, JobStatusUpdate(JobStatus.FAILED, error_message=failure),
        )
        session.commit()
        assert session.get(Job, job.id).error_message == failure


def test_a_job_of_a_dead_owner_stores_the_restart_message(pg_factory) -> None:
    with pg_factory() as session:
        gone = _running_job(session, JobType.CHAT, GONE)
        recover_jobs_of_dead_owners(session, {_unstamped(GONE): Liveness.GONE})
        assert session.get(Job, gone).error_message == JOB_ERROR_SERVER_RESTARTED.error_message


def test_a_queued_job_of_a_dead_owner_fails_too_and_a_finished_one_is_left(pg_factory) -> None:
    with pg_factory() as session:
        queued = create_job_of_unstamped_owner(session, JobType.CHAT, GONE).id
        finished = _running_job(session, JobType.CHAT, GONE)
        update_job_status(session, finished, JobStatusUpdate(JobStatus.COMPLETED))

        recover_jobs_of_dead_owners(session, {_unstamped(GONE): Liveness.GONE})

        assert (_outcome(session, queued)[0], _outcome(session, finished)[0]) == (
            JobStatus.FAILED, JobStatus.COMPLETED,
        )


def test_the_owners_asked_about_are_those_of_active_jobs_only(pg_factory) -> None:
    with pg_factory() as session:
        _running_job(session, JobType.CHAT, HERE)
        _running_job(session, JobType.CHAT, None)
        done = _running_job(session, JobType.CHAT, GONE)
        update_job_status(session, done, JobStatusUpdate(JobStatus.COMPLETED))

        assert active_job_owner_stamps(session) == {_unstamped(HERE)}


def test_only_the_jobs_of_a_lapsed_generation_fail_and_a_later_start_keeps_its_jobs(
    pg_factory,
) -> None:
    with pg_factory() as session:
        lapsed = _running_job(session, JobType.CHAT, HERE, generation="first")
        current = _running_job(session, JobType.COVER, HERE, generation="second")
        written_after_the_read = _running_job(session, JobType.CHAT, HERE, generation="third")

        recovered = recover_jobs_of_dead_owners(session, {
            JobOwnerStamp(HERE, "first"): Liveness.GONE,
            JobOwnerStamp(HERE, "second"): Liveness.ALIVE,
        })

        assert recovered == {JobType.CHAT: 1}
        assert [
            _outcome(session, job_id)[0]
            for job_id in (lapsed, current, written_after_the_read)
        ] == [JobStatus.FAILED, JobStatus.RUNNING, JobStatus.RUNNING]


def test_the_stamps_asked_about_name_the_generation_of_each_active_job(pg_factory) -> None:
    with pg_factory() as session:
        _running_job(session, JobType.CHAT, HERE, generation="first")
        _running_job(session, JobType.COVER, HERE, generation="second")
        _running_job(session, JobType.CHAT, UNREAD)

        assert active_job_owner_stamps(session) == {
            JobOwnerStamp(HERE, "first"), JobOwnerStamp(HERE, "second"), _unstamped(UNREAD),
        }


def test_the_age_recovery_fails_the_job_of_an_owner_the_given_liveness_reads_dead(
    pg_factory,
) -> None:
    with pg_factory() as session:
        gone = _running_job(session, JobType.CHAT, GONE)

        recover_stale_jobs_by_age_and_type(
            session, owner_liveness={_unstamped(GONE): Liveness.GONE},
        )

        assert _outcome(session, gone) == (
            JobStatus.FAILED, JOB_ERROR_SERVER_RESTARTED.error_type,
        )


class _OwnerLeaseServer(fakeredis.FakeAsyncRedis):
    """A Redis that holds no owner lease and notes when it is read.

    ``events`` lists, in order, each owner reading and each commit of the session;
    ``readable=False`` makes the reading fail as an unreachable server does.
    """

    def __init__(self, session, *, readable: bool) -> None:
        super().__init__()
        self._session = session
        self._readable = readable
        self.advisory_locks_held_at_the_reading = 0
        self.events: list[str] = []
        event.listen(session, "after_commit", lambda _session: self.events.append("commit"))

    async def execute_command(self, *args, **options):
        if args[0] != "EVALSHA":
            return await super().execute_command(*args, **options)
        if not self._readable:
            raise RedisConnectionError("down")
        reply = await super().execute_command(*args, **options)
        self.events.append("reading")
        self.advisory_locks_held_at_the_reading = self._session.execute(text(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()",
        )).scalar_one()
        return reply


@pytest.fixture
def person_at_the_queue_limit(pg_factory) -> str:
    """A person whose only active job, run by an owner without a lease, fills the queue."""
    with pg_factory() as session:
        seed_user(session, PERSON.username, user_id=PERSON.id)
        upsert_rate_limit_setting(session, SETTING_MAX_QUEUE_DEPTH, 1)
        gone = _running_job(session, JobType.CHAT, GONE, user_id=PERSON.id)
        session.commit()
    return gone


def test_a_submission_ends_the_job_of_a_dead_owner_instead_of_refusing_for_the_full_queue(
    pg_factory, person_at_the_queue_limit,
) -> None:
    with pg_factory() as session:
        server = _OwnerLeaseServer(session, readable=True)
        arrange_fake_async_redis(server, settle_owner_leases)
        server.events.clear()

        admitted = asyncio.run(create_job_with_rate_limit(
            session, PERSON, JobType.SCORE, redis=make_fake_redis(),
            owner_leases=owner_leases(server),
        ))

        assert (admitted.type, admitted.user_id) == (JobType.SCORE, PERSON.id)
        assert _outcome(session, person_at_the_queue_limit) == (
            JobStatus.FAILED, JOB_ERROR_SERVER_RESTARTED.error_type,
        )
        assert server.advisory_locks_held_at_the_reading == 0
        assert server.events[:2] == ["reading", "commit"]


def test_a_submission_that_cannot_read_owner_liveness_leaves_the_job_and_is_refused(
    pg_factory, person_at_the_queue_limit,
) -> None:
    with pg_factory() as session:
        server = _OwnerLeaseServer(session, readable=False)

        with pytest.raises(Refusal) as refusal:
            asyncio.run(create_job_with_rate_limit(
                session, PERSON, JobType.SCORE, redis=make_fake_redis(),
                owner_leases=owner_leases(server),
            ))

        assert (refusal.value.status_code, refusal.value.message.key) == (
            429, "jobRefusal.queueFull",
        )
        assert _outcome(session, person_at_the_queue_limit)[0] == JobStatus.RUNNING


@pytest.mark.parametrize("owner_liveness", [None, {JobOwnerStamp(GONE, None): Liveness.UNKNOWN}])
def test_the_age_reaper_without_a_dead_owner_leaves_a_fresh_job_alone(
    pg_factory, owner_liveness,
) -> None:
    with pg_factory() as session:
        gone = _running_job(session, JobType.CHAT, GONE)

        recover_stale_jobs_by_age_and_type(session, owner_liveness=owner_liveness)

        assert _outcome(session, gone)[0] == JobStatus.RUNNING


def test_claiming_a_cover_job_names_the_claimer_as_its_owner(pg_factory) -> None:
    with pg_factory() as session:
        queued = create_job(session, JobType.COVER)

        claimed = claim_next_cover_job(session, an_owner(HERE, "claimer-generation"))

        assert (claimed.id, claimed.owner_id, claimed.owner_generation) == (
            queued.id, HERE, "claimer-generation",
        )


def test_a_running_score_job_without_an_owner_is_left_to_its_heartbeat(pg_factory) -> None:
    with pg_factory() as session:
        fresh = _running_job(session, JobType.SCORE, None)
        silent = _running_job(session, JobType.SCORE, None)
        session.get(Job, silent).heartbeat_at = utcnow() - timedelta(days=1)

        recover_jobs_of_dead_owners(session, {_unstamped(GONE): Liveness.GONE})
        recover_stale_jobs_by_age_and_type(session)

        assert (_outcome(session, fresh)[0], _outcome(session, silent)) == (
            JobStatus.RUNNING, (JobStatus.FAILED, "heartbeat_lost"),
        )

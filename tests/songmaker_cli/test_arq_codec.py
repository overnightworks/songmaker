"""The job wrapper's trace and outcome line, and the Redis test server helpers."""

import asyncio
from contextlib import asynccontextmanager

import pytest
from arq import create_pool, func
from arq.connections import RedisSettings
from arq.worker import create_worker
from logline import current_traceparent, unit_trace
from support.redis_server import configured_redis_url, database_number

from songmaker_cli.arq_codec import TRACEPARENT_KWARG
from songmaker_cli.job_types import JobStatus as RowStatus
from songmaker_cli.worker_base import JOB_ENDED_EVENT, logged_job


class CodecWorkerSettings:
    """The arq settings these tests' workers read: a queue of their own."""

    queue_name = "arq:queue:codec-test"


@asynccontextmanager
async def codec_pool(redis_url):
    pool = await create_pool(RedisSettings.from_dsn(redis_url))
    try:
        yield pool
    finally:
        await pool.aclose()


def codec_worker(settings, redis_url, function, name):
    return create_worker(
        settings,
        redis_settings=RedisSettings.from_dsn(redis_url),
        functions=[func(function, name=name)],
        on_startup=None,
        on_shutdown=None,
        cron_jobs=[],
        burst=True,
        poll_delay=0.01,
        retry_jobs=False,
        handle_signals=False,
    )


def test_redis_cases_without_a_server_fail_naming_the_variable():
    with pytest.raises(pytest.fail.Exception, match="TEST_REDIS_URL"):
        configured_redis_url({})


@pytest.mark.parametrize(
    ("worker_id", "number"),
    [("master", 0), ("gw0", 0), ("gw3", 3)],
    ids=["without-xdist", "first-worker", "fourth-worker"],
)
def test_each_worker_selects_its_own_redis_database(worker_id, number):
    assert database_number(worker_id, database_count=16) == number


def test_a_worker_beyond_the_servers_databases_fails_naming_both():
    with pytest.raises(pytest.fail.Exception, match=r"gw16.*16 databases"):
        database_number("gw16", database_count=16)


@pytest.mark.parametrize(
    ("raises", "row_status", "outcome", "reason", "arguments", "logged_job_id"),
    [
        (None, RowStatus.COMPLETED, "ok", None, ("job-1", "private content"), "job-1"),
        (
            ValueError("private content"),
            None,
            "failed",
            None,
            ("job-1", "private content"),
            "job-1",
        ),
        (None, None, "ok", None, (), None),
        (None, RowStatus.FAILED, "failed", "job_failed", ("job-1", "private content"), "job-1"),
        (None, RowStatus.CANCELLED, "cancelled", None, ("job-1", "private content"), "job-1"),
        (
            None,
            OSError("private content"),
            "failed",
            "status_unreadable",
            ("job-1", "private content"),
            "job-1",
        ),
    ],
    ids=["completed", "raised", "cron", "row-failed", "row-cancelled", "status-unreadable"],
)
def test_a_job_ends_with_one_line_carrying_its_id_and_outcome(
    raises, row_status, outcome, reason, arguments, logged_job_id, redis_url, caplog
):
    """One line per job: its id (a cron job has none), duration and the outcome its row shows."""

    async def job(ctx, *job_arguments):
        if raises is not None:
            raise raises
        return "probe result"

    def read_status(_job_id):
        if isinstance(row_status, Exception):
            raise row_status
        return row_status

    async def scenario():
        async with codec_pool(redis_url) as pool:
            worker = codec_worker(
                CodecWorkerSettings,
                redis_url,
                logged_job("probe", job, status_of=read_status),
                "probe",
            )
            try:
                queued = await pool.enqueue_job(
                    "probe", *arguments, _queue_name=CodecWorkerSettings.queue_name
                )
                await worker.async_run()
                if reason == "status_unreadable":
                    assert await queued.result(timeout=1) == "probe result"
            finally:
                await worker.close()

    with caplog.at_level("INFO"):
        asyncio.run(asyncio.wait_for(scenario(), timeout=30))

    (ended,) = [record for record in caplog.records if record.getMessage() == JOB_ENDED_EVENT]
    assert (
        getattr(ended, "job_id", None),
        ended.job_function,
        ended.outcome,
        getattr(ended, "reason", None),
    ) == (logged_job_id, "probe", outcome, reason)
    assert ended.duration_ms >= 0
    assert "private content" not in "".join(
        str(value) for value in vars(ended).values() if isinstance(value, str)
    )
    if reason == "status_unreadable":
        (warning,) = [
            record
            for record in caplog.records
            if record.getMessage() == "arq_job.status_unreadable"
        ]
        assert (warning.job_id, warning.error_type) == ("job-1", "OSError")
        assert ended.levelname == "WARNING"


def test_a_job_runs_in_its_enqueuers_trace_and_a_failed_job_leaves_none_behind(redis_url):
    seen_traceparents = {}

    async def job(ctx, name, fails):
        seen_traceparents[name] = current_traceparent()
        if fails:
            raise ValueError("deliberate failure")

    async def scenario():
        async with codec_pool(redis_url) as pool:
            worker = codec_worker(
                CodecWorkerSettings, redis_url, logged_job("probe", job), "probe",
            )
            try:
                with unit_trace(None):
                    enqueuer_traceparent = current_traceparent()
                    await pool.enqueue_job(
                        "probe", "failing", True,
                        _queue_name=CodecWorkerSettings.queue_name,
                        **{TRACEPARENT_KWARG: enqueuer_traceparent},
                    )
                await pool.enqueue_job(
                    "probe", "good", False, _queue_name=CodecWorkerSettings.queue_name
                )
                await worker.async_run()
            finally:
                await worker.close()
        return enqueuer_traceparent

    enqueuer_traceparent = asyncio.run(asyncio.wait_for(scenario(), timeout=30))

    def trace_id_of(traceparent):
        return traceparent.split("-")[1]

    assert trace_id_of(seen_traceparents["failing"]) == trace_id_of(enqueuer_traceparent)
    assert trace_id_of(seen_traceparents["good"]) != trace_id_of(enqueuer_traceparent)
    assert current_traceparent() is None

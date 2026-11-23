"""Wire compatibility and inert-data boundary for #1301 F1."""

import asyncio
import json
import pickle
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from arq import cron, func
from arq.connections import RedisSettings
from arq.constants import in_progress_key_prefix, job_key_prefix, result_key_prefix
from arq.jobs import DeserializationError, Job, JobStatus, SerializationError
from arq.worker import create_worker
from logline import current_traceparent, unit_trace
from support.redis_server import configured_redis_url, database_number

from songmaker_cli import arq_pool
from songmaker_cli.arq_codec import deserialize_arq
from songmaker_cli.job_types import JobFunction
from songmaker_cli.job_types import JobStatus as RowStatus
from songmaker_cli.scoring_worker import ScoringWorkerSettings
from songmaker_cli.worker_base import JOB_ENDED_EVENT, logged_job


@asynccontextmanager
async def codec_pool(redis_url, monkeypatch):
    monkeypatch.setenv("REDIS_URL", redis_url)
    pool = await arq_pool.init_arq_pool()
    try:
        yield pool
    finally:
        await arq_pool.close_arq_pool()


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


JOB_CASES = [
    (ScoringWorkerSettings, JobFunction.SCORE, ("job", "generation", ["bpm", "lyrics"]), False),
    (ScoringWorkerSettings, JobFunction.SCORE, ("job", "generation", None), False),
]


@pytest.mark.parametrize(
    "settings,function,args,deferred",
    JOB_CASES,
    ids=["score", "auto-score"],
)
def test_configured_producers_and_workers_exchange_json(
    settings, function, args, deferred, redis_url, monkeypatch
):
    """1301-F1-CODEC-JOBS: real web/worker pools preserve each caller's payload."""

    async def echo(ctx, *received, **kwargs):
        return {"args": received, "kwargs": kwargs}

    async def scenario():
        async with codec_pool(redis_url, monkeypatch) as pool:
            worker = codec_worker(settings, redis_url, echo, function)
            try:
                job = await pool.enqueue_job(function, *args, _queue_name=settings.queue_name)
                raw = await pool.get(job_key_prefix + job.job_id)
                assert json.loads(raw)["a"] == list(args)
                await worker.async_run()
                assert await job.result(timeout=1) == {"args": list(args), "kwargs": {}}
                # Follow-on producers inherit the pool arq built from the worker settings.
                follow_on = await worker.pool.enqueue_job(
                    function,
                    *args,
                    _queue_name=settings.queue_name,
                    _defer_by=timedelta(minutes=1) if deferred else None,
                )
                assert json.loads(await pool.get(job_key_prefix + follow_on.job_id))["a"] == list(
                    args
                )
                info = await follow_on.info()
                assert list(info.args) == list(args)
                assert await follow_on.status() == (
                    JobStatus.deferred if deferred else JobStatus.queued
                )
            finally:
                await worker.close()

    asyncio.run(asyncio.wait_for(scenario(), timeout=30))


@pytest.mark.parametrize("settings", [ScoringWorkerSettings])
@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
def test_results_remain_readable_with_correct_success(settings, outcome, redis_url, monkeypatch):
    """1301-F1-CODEC-RESULTS: public readers distinguish success from inert failure."""

    async def complete(ctx):
        if outcome == "failure":
            raise ValueError("deliberate failure")
        if outcome == "cancelled":
            raise asyncio.CancelledError()
        return {"finished": True, "details": [None, 42, "🎵"]}

    async def scenario():
        async with codec_pool(redis_url, monkeypatch) as pool:
            worker = codec_worker(settings, redis_url, complete, "complete")
            try:
                job = await pool.enqueue_job("complete", _queue_name=settings.queue_name)
                await worker.async_run()
                info = await job.result_info()
                assert info.success is (outcome == "success")
                assert (
                    json.loads(await pool.get(result_key_prefix + job.job_id))["s"] is info.success
                )
                if outcome == "success":
                    assert await job.result(timeout=1) == {
                        "finished": True,
                        "details": [None, 42, "🎵"],
                    }
                else:
                    assert info.result == "unable to serialize result"
                    with pytest.raises(SerializationError):
                        await job.result(timeout=1)
            finally:
                await worker.close()

    asyncio.run(asyncio.wait_for(scenario(), timeout=30))


@pytest.mark.parametrize(
    "value", [object(), b"bytes", {1, 2}, {1: "key"}, float("nan"), float("inf"), float("-inf")]
)
def test_unsupported_values_cannot_be_enqueued(value, redis_url, monkeypatch):
    """1301-F1-CODEC-REJECT: rejected values leave no partial job or queue entry."""

    async def scenario():
        async with codec_pool(redis_url, monkeypatch) as pool:
            job_id = "unsupported-value"
            queue = ScoringWorkerSettings.queue_name
            with pytest.raises(SerializationError):
                await pool.enqueue_job("rejected", value, _job_id=job_id, _queue_name=queue)
            assert await pool.exists(job_key_prefix + job_id) == 0
            assert await pool.zscore(queue, job_id) is None
            assert await pool.zcard(queue) == 0

    asyncio.run(asyncio.wait_for(scenario(), timeout=30))


@pytest.mark.parametrize(
    "payload",
    [
        b"{",
        b"\xff",
        b"[]",
        b"null",
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b'{"a":-Infinity}',
        b'{"a":1e400}',
        *[
            json.dumps(
                {"f": "rejected", "a": [], "k": {}, "t": 1, "et": 0} | {field: value}
            ).encode()
            for field, value in [
                ("f", ["rejected"]),
                ("a", {}),
                ("k", []),
                ("t", "1"),
                ("et", "0"),
                ("t", True),
                ("et", False),
                ("et", 10**20),
                ("et", -1),
                ("t", -1),
            ]
        ],
    ],
)
@pytest.mark.parametrize("settings", [ScoringWorkerSettings])
def test_invalid_json_fails_visibly_without_execution(
    payload, settings, redis_url, monkeypatch, caplog
):
    """1301-F1-CODEC-REJECT: poison messages finish failed without execution or retry."""
    executed = []

    async def rejected(ctx, *args, **kwargs):
        executed.append(True)

    async def scenario():
        async with codec_pool(redis_url, monkeypatch) as pool:
            worker = codec_worker(settings, redis_url, rejected, "rejected")
            try:
                job = await pool.enqueue_job("rejected", _queue_name=settings.queue_name)
                await pool.set(job_key_prefix + job.job_id, payload)
                await worker.async_run()
                info = await job.result_info()
                assert info.job_id == job.job_id
                assert info.success is False
                with pytest.raises(SerializationError):
                    await job.result(timeout=1)
                assert await job.status() == JobStatus.complete
                assert await pool.exists(job_key_prefix + job.job_id) == 0
                assert await pool.exists(in_progress_key_prefix + job.job_id) == 0
                assert await pool.zscore(settings.queue_name, job.job_id) is None
                assert any(
                    job.job_id in record.getMessage()
                    and isinstance(record.exc_info[1], DeserializationError)
                    for record in caplog.records
                    if record.exc_info
                )
            finally:
                await worker.close()

    asyncio.run(asyncio.wait_for(scenario(), timeout=30))
    assert not executed


class PickleSentinel:
    def __init__(self, marker: Path):
        self.marker = marker

    def __reduce__(self):
        return Path.touch, (self.marker,)


@pytest.mark.parametrize("settings", [ScoringWorkerSettings])
def test_legacy_jobs_and_results_never_execute_pickle(settings, redis_url, monkeypatch, tmp_path):
    """1301-F1-CODEC-LEGACY / 1301-F1-CODEC-REJECT: rejection is visible and inert."""
    marker = tmp_path / "pickle-executed"
    payload = pickle.dumps(
        {
            "f": "legacy",
            "a": (PickleSentinel(marker),),
            "k": {},
            "t": 1,
            "et": 0,
        }
    )
    with pytest.raises(ValueError):
        deserialize_arq(payload)
    executed = []

    async def legacy(ctx, *args):
        executed.append(True)

    async def scenario():
        async with codec_pool(redis_url, monkeypatch) as pool:
            worker = codec_worker(settings, redis_url, legacy, "legacy")
            try:
                job = await pool.enqueue_job("legacy", _queue_name=settings.queue_name)
                await pool.set(job_key_prefix + job.job_id, payload)
                await worker.async_run()
                info = await job.result_info()
                assert info.success is False
                assert info.result == "unable to serialize result"
                with pytest.raises(SerializationError):
                    await job.result(timeout=1)
                assert await job.status() == JobStatus.complete
                await pool.set(result_key_prefix + "old-result", payload)
                old = Job("old-result", pool, _deserializer=deserialize_arq)
                with pytest.raises(DeserializationError):
                    await old.result(timeout=1)
                assert await pool.get(result_key_prefix + "old-result") == payload
            finally:
                await worker.close()

    asyncio.run(asyncio.wait_for(scenario(), timeout=30))
    assert not marker.exists()
    assert not executed


def test_cron_scheduler_uses_the_worker_json_pool(redis_url, monkeypatch):
    """1301-F1-CODEC-JOBS: arq itself enqueues and consumes a cron envelope."""

    async def scheduled(ctx):
        return "cron completed"

    async def scenario():
        async with codec_pool(redis_url, monkeypatch) as pool:
            worker = create_worker(
                ScoringWorkerSettings,
                redis_settings=RedisSettings.from_dsn(redis_url),
                functions=[],
                on_startup=None,
                on_shutdown=None,
                cron_jobs=[
                    cron(scheduled, run_at_startup=True, keep_result=60, job_id="cron-proof")
                ],
                burst=True,
                max_burst_jobs=1,
                poll_delay=0.01,
                handle_signals=False,
            )
            try:
                await worker.async_run()
                raw = await pool.get(result_key_prefix + "cron-proof")
                assert json.loads(raw)["r"] == "cron completed"
                job = Job("cron-proof", pool, _deserializer=deserialize_arq)
                assert await job.result(timeout=1) == "cron completed"
            finally:
                await worker.close()

    asyncio.run(asyncio.wait_for(scenario(), timeout=30))


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
    raises, row_status, outcome, reason, arguments, logged_job_id, redis_url, monkeypatch, caplog
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
        async with codec_pool(redis_url, monkeypatch) as pool:
            worker = codec_worker(
                ScoringWorkerSettings,
                redis_url,
                logged_job("probe", job, status_of=read_status),
                "probe",
            )
            try:
                queued = await pool.enqueue_job(
                    "probe", *arguments, _queue_name=ScoringWorkerSettings.queue_name
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


def test_a_job_runs_in_its_enqueuers_trace_and_a_failed_job_leaves_none_behind(
    redis_url, monkeypatch
):
    seen_traceparents = {}

    async def job(ctx, name, fails):
        seen_traceparents[name] = current_traceparent()
        if fails:
            raise ValueError("deliberate failure")

    async def scenario():
        async with codec_pool(redis_url, monkeypatch) as pool:
            worker = codec_worker(
                ScoringWorkerSettings, redis_url, logged_job("probe", job), "probe",
            )
            try:
                with unit_trace(None):
                    enqueuer_traceparent = current_traceparent()
                    await pool.enqueue_job(
                        "probe", "failing", True, _queue_name=ScoringWorkerSettings.queue_name
                    )
                await pool.enqueue_job(
                    "probe", "good", False, _queue_name=ScoringWorkerSettings.queue_name
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

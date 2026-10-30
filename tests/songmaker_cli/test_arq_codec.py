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

from songmaker_cli import arq_pool
from songmaker_cli.arq_codec import deserialize_arq
from songmaker_cli.constants import JobFunction
from songmaker_cli.generation_params import CoverTaskParams, RepaintTaskParams
from songmaker_cli.music_worker import MusicWorkerSettings
from songmaker_cli.scoring_worker import ScoringWorkerSettings


@asynccontextmanager
async def codec_pool(socket, monkeypatch):
    monkeypatch.setenv("REDIS_URL", f"unix://{socket}")
    pool = await arq_pool.init_arq_pool()
    try:
        yield pool
    finally:
        await arq_pool.close_arq_pool()


def codec_worker(settings, socket, function, name):
    return create_worker(
        settings,
        redis_settings=RedisSettings(unix_socket_path=str(socket)),
        functions=[func(function, name=name)],
        on_startup=None,
        on_shutdown=None,
        cron_jobs=[],
        burst=True,
        poll_delay=0.01,
        retry_jobs=False,
        handle_signals=False,
    )


GENERATION_ARGS = ("job", "song", "version", 2, "owner", None, "turbo")
REFERENCE_AUDIO = dict(
    src_wav_path="owner/source.wav",
    src_generation_id="source",
    lyrics="Grüße 🎵",
    prompt="warm",
)
JOB_CASES = [
    (MusicWorkerSettings, JobFunction.GENERATE, GENERATION_ARGS, False),
    (
        MusicWorkerSettings,
        JobFunction.GENERATE,
        (
            *GENERATION_ARGS,
            RepaintTaskParams(
                **REFERENCE_AUDIO,
                repainting_start=0.2,
                repainting_end=0.8,
            ).model_dump(),
        ),
        False,
    ),
    (
        MusicWorkerSettings,
        JobFunction.GENERATE,
        (
            *GENERATION_ARGS,
            None,
            CoverTaskParams(
                **REFERENCE_AUDIO,
                audio_cover_strength=0.5,
            ).model_dump(),
        ),
        False,
    ),
    (MusicWorkerSettings, JobFunction.COVER, ("job",), False),
    (ScoringWorkerSettings, JobFunction.SCORE, ("job", "generation", ["bpm", "lyrics"]), False),
    (ScoringWorkerSettings, JobFunction.SCORE, ("job", "generation", None), False),
    (MusicWorkerSettings, JobFunction.LOAD_MODEL_ON_WORKER, ("job", "worker", "turbo"), False),
    (MusicWorkerSettings, JobFunction.DOWNLOAD_MODEL_ON_WORKER, ("job", "turbo"), False),
    (MusicWorkerSettings, JobFunction.LORA_TRAINING, ("job", "lora", "owner"), False),
    (MusicWorkerSettings, JobFunction.LORA_TRAINING, ("job", "lora", "owner", "turbo"), True),
    (MusicWorkerSettings, JobFunction.GENERATE, (*GENERATION_ARGS, None, None), True),
    (MusicWorkerSettings, "cron:cleanup_files_cron", (), False),
]


@pytest.mark.parametrize(
    "settings,function,args,deferred",
    JOB_CASES,
    ids=[
        "generation",
        "repaint",
        "audio-cover",
        "image-cover",
        "score",
        "auto-score",
        "load-model",
        "download-model",
        "lora",
        "deferred-lora",
        "deferred-generation",
        "cron",
    ],
)
def test_configured_producers_and_workers_exchange_json(
    settings, function, args, deferred, redis_socket, monkeypatch
):
    """1301-F1-CODEC-JOBS: real web/worker pools preserve each caller's payload."""

    async def echo(ctx, *received, **kwargs):
        return {"args": received, "kwargs": kwargs}

    async def scenario():
        async with codec_pool(redis_socket, monkeypatch) as pool:
            worker = codec_worker(settings, redis_socket, echo, function)
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


@pytest.mark.parametrize("settings", [MusicWorkerSettings, ScoringWorkerSettings])
@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
def test_results_remain_readable_with_correct_success(settings, outcome, redis_socket, monkeypatch):
    """1301-F1-CODEC-RESULTS: public readers distinguish success from inert failure."""

    async def complete(ctx):
        if outcome == "failure":
            raise ValueError("deliberate failure")
        if outcome == "cancelled":
            raise asyncio.CancelledError()
        return {"finished": True, "details": [None, 42, "🎵"]}

    async def scenario():
        async with codec_pool(redis_socket, monkeypatch) as pool:
            worker = codec_worker(settings, redis_socket, complete, "complete")
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
def test_unsupported_values_cannot_be_enqueued(value, redis_socket, monkeypatch):
    """1301-F1-CODEC-REJECT: rejected values leave no partial job or queue entry."""

    async def scenario():
        async with codec_pool(redis_socket, monkeypatch) as pool:
            job_id = "unsupported-value"
            queue = MusicWorkerSettings.queue_name
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
@pytest.mark.parametrize("settings", [MusicWorkerSettings, ScoringWorkerSettings])
def test_invalid_json_fails_visibly_without_execution(
    payload, settings, redis_socket, monkeypatch, caplog
):
    """1301-F1-CODEC-REJECT: poison messages finish failed without execution or retry."""
    executed = []

    async def rejected(ctx, *args, **kwargs):
        executed.append(True)

    async def scenario():
        async with codec_pool(redis_socket, monkeypatch) as pool:
            worker = codec_worker(settings, redis_socket, rejected, "rejected")
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


@pytest.mark.parametrize("settings", [MusicWorkerSettings, ScoringWorkerSettings])
def test_legacy_jobs_and_results_never_execute_pickle(
    settings, redis_socket, monkeypatch, tmp_path
):
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
        async with codec_pool(redis_socket, monkeypatch) as pool:
            worker = codec_worker(settings, redis_socket, legacy, "legacy")
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


def test_cron_scheduler_uses_the_worker_json_pool(redis_socket, monkeypatch):
    """1301-F1-CODEC-JOBS: arq itself enqueues and consumes a cron envelope."""

    async def scheduled(ctx):
        return "cron completed"

    async def scenario():
        async with codec_pool(redis_socket, monkeypatch) as pool:
            worker = create_worker(
                MusicWorkerSettings,
                redis_settings=RedisSettings(unix_socket_path=str(redis_socket)),
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

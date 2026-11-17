"""A job that meets a hold or loses a lock ends deferred or stopped, never as a failed take."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path

import pytest
from support.generation_job_world import run_async
from support.job_owner import an_owner
from support.web_app import SettledFakeAsyncRedis
from support.worker_http_peer import WorkerReply, WorkerScenario

from acestep_engine.constants import GPU_HELD_DETAIL
from songmaker_cli.acestep_state import (
    download_locks,
    read_queue_depth,
    worker_state_key,
)
from songmaker_cli.db.models import Generation, Job
from songmaker_cli.db.queries.jobs import get_job
from songmaker_cli.job_types import JobFunction
from songmaker_cli.jobs import download_model_on_worker, run_generation_job
from songmaker_cli.messages import message


@pytest.mark.parametrize("completed", [0, 1], ids=["first-take", "second-take"])
def test_a_take_the_worker_refuses_as_held_requeues_the_job_and_fails_nothing(
    seeded_db, generation_worker_peer, completed, locked_ffmpeg,
):
    """A hold or an unsettled Redis restart met at /generate requeues the takes still missing."""
    queued = []

    async def enqueue_job(function, *args, **kwargs):
        queued.append((function, args, kwargs))

    async def exercise():
        held = WorkerReply(409, GPU_HELD_DETAIL)
        scenario = WorkerScenario(
            loaded_modes=("sft",), submit_answers=(None,) * completed + (held,),
        )
        async with generation_worker_peer(scenario, db_factory=seeded_db) as peer:
            peer.redis.enqueue_job = enqueue_job
            await run_generation_job(
                "j1", "s1", "v1", 2, "u1", db_factory=seeded_db,
                audio_dir=peer.audio_dir, data_dir=peer.data_dir, redis=peer.redis,
                target_model="sft", owner=an_owner("o1"),
            )
            assert await read_queue_depth(peer.redis, peer.settings.worker_id) == 0

    run_async(exercise())
    assert [(function, args[3]) for function, args, _ in queued] == [
        (JobFunction.GENERATE, 2 - completed),
    ]
    with seeded_db() as session:
        job = get_job(session, "j1")
        assert job.status == "queued"
        assert job.queue_reason_message == message("jobWait.voiceTraining")
        assert job.error_message is None
        assert session.query(Generation).count() == completed


def test_a_download_that_lost_its_lock_stops_and_the_next_job_joins_the_running_transfer(
    seeded_db, generation_worker_peer, monkeypatch,
) -> None:
    """The transfer on the worker cannot be cancelled, so the next job of the mode joins it."""
    monkeypatch.setattr(
        "songmaker_cli.acestep_state.DOWNLOAD_LOCK_EXTEND_EVERY", timedelta(milliseconds=10),
    )
    with seeded_db() as session:
        for job_id in ("dl-lost", "dl-next"):
            session.add(Job(id=job_id, type="download_model_on_worker", status="queued"))
        session.commit()
    redis = SettledFakeAsyncRedis()
    transfers_started = 0

    async def exercise() -> None:
        nonlocal transfers_started
        async with generation_worker_peer(WorkerScenario(), db_factory=seeded_db) as peer:
            redis.store[worker_state_key(peer.settings.worker_id)] = json.dumps(
                {"loaded": [], "gpu_healthy": True},
            )
            transfer_running = asyncio.Event()
            transfer_may_end = asyncio.Event()

            async def controllable_transfer(repo_id: str, local_dir: Path) -> None:
                nonlocal transfers_started
                transfers_started += 1
                transfer_running.set()
                await transfer_may_end.wait()

            peer.deps.download_fn = controllable_transfer
            lost_job = asyncio.create_task(download_model_on_worker(
                {"redis": redis}, "dl-lost", "sft", db_factory=seeded_db, owner=an_owner("o1"),
            ))
            await transfer_running.wait()
            other_process = redis.another_process()
            other_locks = download_locks(other_process)
            await other_process.zrem(other_locks.keys.expiry, "sft")
            generation = await other_locks.acquire("sft")
            assert generation is not None
            await lost_job
            await other_locks.release("sft", generation)
            streams_before = [kind for kind, _ in peer.requests].count("stream")
            next_job = asyncio.create_task(download_model_on_worker(
                {"redis": redis}, "dl-next", "sft", db_factory=seeded_db, owner=an_owner("o1"),
            ))
            while [kind for kind, _ in peer.requests].count("stream") == streams_before:
                await asyncio.sleep(0.01)
            transfer_may_end.set()
            await next_job

    run_async(exercise())

    with seeded_db() as session:
        assert get_job(session, "dl-lost").status == "failed"
        assert get_job(session, "dl-lost").error_type == "download_lock_lost"
        assert get_job(session, "dl-next").status == "completed"
    assert transfers_started == 1

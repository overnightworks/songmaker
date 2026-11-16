"""A job that meets a hold or loses a lock ends deferred or stopped, never as a failed take."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from support.generation_job_world import run_async
from support.web_app import SettledFakeAsyncRedis
from support.worker_http_peer import WorkerReply, WorkerScenario

from acestep_engine.constants import GPU_HELD_DETAIL
from songmaker_cli.acestep_state import (
    download_key,
    download_locks,
    read_queue_depth,
    worker_state_key,
)
from songmaker_cli.db.models import Generation, Job
from songmaker_cli.db.queries.jobs import get_job
from songmaker_cli.db.queries.workers import register_worker
from songmaker_cli.job_types import JobFunction
from songmaker_cli.jobs import download_model_on_worker, run_generation_job
from songmaker_cli.messages import message


@pytest.mark.parametrize("completed", [0, 1], ids=["first-take", "second-take"])
def test_a_take_the_worker_refuses_as_held_requeues_the_job_and_fails_nothing(
    seeded_db, generation_worker_peer, completed,
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
                target_model="sft", owner_id="o1",
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
        assert job.error is None
        assert session.query(Generation).count() == completed


def test_a_download_that_lost_its_lock_stops_and_fails_its_job(seeded_db, monkeypatch) -> None:
    monkeypatch.setattr(
        "songmaker_cli.acestep_state.DOWNLOAD_LOCK_EXTEND_EVERY", timedelta(milliseconds=10),
    )
    with seeded_db() as session:
        session.add(Job(id="dl-lost", type="download_model_on_worker", status="queued"))
        register_worker(
            session, worker_id="w1", host="acestep-worker", port=8001, gpu_id=0,
            vram_total_gb=24.0,
        )
        session.commit()
    redis = SettledFakeAsyncRedis()
    redis.store[worker_state_key("w1")] = json.dumps({"loaded": [], "gpu_healthy": True})
    new_holder = redis.another_process()
    new_holder_locks = download_locks(new_holder)

    fake_submit_response = MagicMock(status_code=200)
    fake_submit_response.json = MagicMock(return_value={"task_id": "t"})
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_submit_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    downloads_started = 0

    async def a_download_another_job_takes_over(*args, **kwargs):
        nonlocal downloads_started
        downloads_started += 1
        await new_holder.zrem(new_holder_locks.keys.expiry, "sft")
        assert await new_holder_locks.acquire("sft") is not None
        await new_holder.set(download_key("sft"), "job-2", ex=15)
        await asyncio.sleep(30)

    with (
        patch("httpx.AsyncClient", return_value=fake_client),
        patch(
            "songmaker_cli.scheduler.consume_download_task_stream",
            new=a_download_another_job_takes_over,
        ),
    ):
        run_async(download_model_on_worker(
            {"redis": redis}, "dl-lost", "sft", db_factory=seeded_db, owner_id="o1",
        ))

    with seeded_db() as session:
        job = get_job(session, "dl-lost")
        assert job.status == "failed"
        assert job.error_type == "download_lock_lost"
    assert downloads_started == 1
    assert redis.store[download_key("sft")] == "job-2"

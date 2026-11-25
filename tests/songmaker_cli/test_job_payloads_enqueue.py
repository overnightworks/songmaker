"""Every route that queues a job stores the job's arguments on its row, as the typed payload."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.generation_job_world import worker_up
from support.job_owner import stored_payload
from support.lora_api_world import USER_A
from support.web_app import (
    arrange_fake_async_redis,
    make_authenticated_user,
    make_router_app,
    make_router_ctx,
    web_client,
)

from songmaker_cli.acestep_state import worker_state_key
from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import MODEL_DEFAULT_MODE
from songmaker_cli.db.models import Album, AvailableModel, Generation, Song, User, Version
from songmaker_cli.db.queries.loras import add_user_lora_sample, create_user_lora
from songmaker_cli.db.queries.workers import register_worker
from songmaker_cli.generation_params import CoverTaskParams, RepaintTaskParams
from songmaker_cli.job_payloads import (
    DownloadModelPayload,
    GeneratePayload,
    LoadModelPayload,
    LoraTrainingPayload,
    ScorePayload,
)
from songmaker_cli.jobs.generation import _create_auto_score_job

OWNER_ID = "owner"
WORKER_ID = "gpu-1"
MODE = "sft"


def _seed_one_take(session) -> None:
    session.add(User(id=OWNER_ID, username="owner", role="user"))
    session.flush()
    session.add(Album(id="album", title="Album", artist="X", created_by=OWNER_ID))
    session.add(Song(id="song", title="Song", album_id="album", track_number=1, slug="song"))
    session.add(Version(id="version", song_id="song", version_number=1, lyrics="l", prompt="p"))
    session.add(Generation(
        id="take", song_id="song", version_id="version", generation_number=1,
        mp3_path="owner/take.mp3", wav_path="owner/take.wav",
    ))
    session.query(AvailableModel).filter(AvailableModel.id == MODE).update({"is_active": True})
    session.commit()


@pytest.fixture
def client(tmp_path: Path, pg_factory) -> TestClient:
    audio = tmp_path / "audio" / OWNER_ID
    audio.mkdir(parents=True)
    (audio / "take.wav").write_bytes(b"RIFF" + b"\x00" * 40)
    ctx = make_router_ctx(tmp_path, db=pg_factory, seed_db=_seed_one_take)
    return web_client(make_router_app(ctx, user=make_authenticated_user(OWNER_ID)))


def _queue_via(client: TestClient, path: str, body: dict):
    with worker_up(client):
        return client.post(f"/api/{path}", json=body)


def test_generate_stores_its_arguments(client: TestClient) -> None:
    response = _queue_via(client, "songs/song/generate", {"count": 2, "seed": 7, "model": MODE})

    assert stored_payload(client.app.state.ctx.db, response.json()["id"]) == GeneratePayload(
        song_id="song", version_id="version", count=2, user_id=OWNER_ID, seed=7,
        target_model=MODE, task_params=None,
    )


def test_repaint_stores_its_arguments_and_its_task(client: TestClient) -> None:
    response = _queue_via(client, "generations/take/repaint", {
        "src_generation_id": "take", "repainting_start": 0.2, "repainting_end": 0.8,
        "count": 3, "model": MODE,
    })

    payload = stored_payload(client.app.state.ctx.db, response.json()["id"])
    assert (payload.count, payload.target_model, type(payload.task_params)) == (
        3, MODE, RepaintTaskParams,
    )
    assert (payload.task_params.repainting_start, payload.task_params.repainting_end) == (0.2, 0.8)


def test_cover_stores_its_arguments_and_its_task(client: TestClient) -> None:
    response = _queue_via(client, "generations/take/cover", {
        "src_generation_id": "take", "audio_cover_strength": 0.7, "model": MODE,
    })

    payload = stored_payload(client.app.state.ctx.db, response.json()["id"])
    assert (payload.song_id, payload.version_id, type(payload.task_params)) == (
        "song", "version", CoverTaskParams,
    )
    assert payload.task_params.audio_cover_strength == 0.7


@pytest.mark.parametrize("scorers", [["silence"], None])
def test_score_stores_its_arguments(client: TestClient, scorers) -> None:
    response = _queue_via(client, "generations/take/score", {"scorers": scorers})

    assert stored_payload(client.app.state.ctx.db, response.json()["id"]) == ScorePayload(
        gen_id="take", scorers=scorers,
    )


def test_the_automatic_score_of_a_new_take_stores_its_arguments(client: TestClient) -> None:
    ctx = client.app.state.ctx

    job_id = _create_auto_score_job(ctx.db, "take", "song")

    assert stored_payload(ctx.db, job_id) == ScorePayload(gen_id="take", scorers=None)


def test_training_a_voice_stores_its_arguments(client_and_ctx) -> None:
    client, ctx = client_and_ctx
    with ctx.db() as session:
        lora = create_user_lora(session, USER_A, "Trainable", "trainable")
        for index in range(3):
            add_user_lora_sample(
                session, lora.id, f"a/{index}.wav", caption=f"caption {index}", lyrics="lyrics",
            )
        session.commit()
        lora_id = lora.id

    response = client.post(f"/api/loras/{lora_id}/train")

    assert stored_payload(ctx.db, response.json()["training_job_id"]) == LoraTrainingPayload(
        lora_id=lora_id, user_id=USER_A, target_mode=MODEL_DEFAULT_MODE,
    )


def _register_worker(ctx: AppContext) -> None:
    with ctx.db() as session:
        register_worker(
            session, worker_id=WORKER_ID, host="gpu", port=8001, gpu_id=0, vram_total_gb=24.0,
        )
        session.commit()


def test_loading_a_model_on_a_worker_stores_its_arguments(admin_client: TestClient) -> None:
    ctx = admin_client.app.state.ctx
    _register_worker(ctx)

    response = admin_client.post(
        f"/api/admin/workers/{WORKER_ID}/load_model", json={"mode": MODE},
    )

    assert stored_payload(ctx.db, response.json()["id"]) == LoadModelPayload(
        worker_id=WORKER_ID, mode=MODE,
    )


def test_downloading_a_model_stores_its_arguments(admin_client: TestClient) -> None:
    ctx = admin_client.app.state.ctx
    _register_worker(ctx)
    heartbeat = json.dumps({"available_modes": [], "gpu_healthy": True})
    arrange_fake_async_redis(
        ctx.async_redis, lambda redis: redis.set(worker_state_key(WORKER_ID), heartbeat),
    )

    response = admin_client.post(f"/api/admin/registry/{MODE}/download")

    assert stored_payload(ctx.db, response.json()["id"]) == DownloadModelPayload(mode=MODE)

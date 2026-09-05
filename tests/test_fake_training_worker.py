"""Protocol checks for the Voices E2E fake training worker."""

from __future__ import annotations

import importlib.util
import json
import sys
import wave
from io import BytesIO
from pathlib import Path

import fakeredis.aioredis
from conftest import make_test_app
from fastapi.testclient import TestClient

from acestep_worker.heartbeat import worker_state_key
from songmaker_cli.internal_api import INTERNAL_TOKEN_HEADER
from songmaker_cli.settings import get_settings

_FIXTURE_PATH = Path(__file__).with_name("e2e_fixtures") / "fake_training_worker.py"
_fixture_spec = importlib.util.spec_from_file_location("fake_training_worker", _FIXTURE_PATH)
if _fixture_spec is None or _fixture_spec.loader is None:
    raise RuntimeError(f"Could not load test fixture: {_FIXTURE_PATH}")
_fixture_module = importlib.util.module_from_spec(_fixture_spec)
sys.modules[_fixture_spec.name] = _fixture_module
_fixture_spec.loader.exec_module(_fixture_module)

FAKE_WORKER_ID = _fixture_module.FAKE_WORKER_ID
FakeTrainingWorkerSettings = _fixture_module.FakeTrainingWorkerSettings
build_fake_worker_deps = _fixture_module.build_fake_worker_deps
create_fake_training_worker_app = _fixture_module.create_fake_training_worker_app
fake_generation_wav_bytes = _fixture_module.fake_generation_wav_bytes


def _training_request(dataset_dir: Path, output_dir: Path, hold_token: str) -> dict[str, object]:
    return {
        "mode": "sft",
        "dataset_dir": str(dataset_dir),
        "output_dir": str(output_dir),
        "hold_token": hold_token,
        "lokr_linear_dim": 64,
        "lokr_linear_alpha": 128,
        "lokr_factor": -1,
        "lokr_decompose_both": False,
        "lokr_use_tucker": False,
        "lokr_use_scalar": False,
        "lokr_weight_decompose": True,
        "learning_rate": 0.03,
        "train_epochs": 4,
        "train_batch_size": 1,
        "gradient_accumulation": 4,
        "save_every_n_epochs": 5,
        "training_shift": 3.0,
        "training_seed": 42,
        "gradient_checkpointing": False,
        "poll_interval_seconds": 0.01,
    }


def _events(stream: str) -> list[tuple[str, dict[str, object]]]:
    events = []
    for block in stream.strip().split("\n\n"):
        event_type, data = block.splitlines()
        events.append((event_type.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


def test_fake_worker_registers_with_the_internal_api(tmp_path: Path, mock_arq_pool) -> None:
    settings = FakeTrainingWorkerSettings(
        redis_url="redis://unused",
        internal_token=get_settings().songmaker_internal_token.get_secret_value(),
        audio_dir=tmp_path,
    )
    registration = build_fake_worker_deps(settings).registration
    assert registration is not None

    client, _ = make_test_app(tmp_path)
    with client:
        response = client.post(
            "/api/internal/workers/register",
            json=registration.to_payload(),
            headers={INTERNAL_TOKEN_HEADER: settings.internal_token},
        )

    assert response.status_code == 200
    assert response.json()["worker_id"] == FAKE_WORKER_ID


def test_fake_worker_publishes_the_worker_heartbeat(tmp_path: Path) -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    settings = FakeTrainingWorkerSettings(
        redis_url="redis://unused",
        internal_token=get_settings().songmaker_internal_token.get_secret_value(),
        audio_dir=tmp_path,
        control_plane_url="",
    )
    deps = build_fake_worker_deps(settings, redis=redis)

    import asyncio

    async def publish_and_read_heartbeat() -> bytes | None:
        await deps.heartbeat.publish_once()
        return await redis.get(worker_state_key(FAKE_WORKER_ID))

    heartbeat = asyncio.run(publish_and_read_heartbeat())

    assert heartbeat is not None
    state = json.loads(heartbeat)
    assert state["gpu_healthy"] is True
    assert state["loaded"] == []


def test_fake_worker_emits_epoch_progress_and_an_adapter_result(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    (dataset_dir / "sample.caption.txt").write_text("voice", encoding="utf-8")
    output_dir = tmp_path / "output"
    settings = FakeTrainingWorkerSettings(
        redis_url="redis://unused",
        internal_token=get_settings().songmaker_internal_token.get_secret_value(),
        audio_dir=tmp_path,
        control_plane_url="",
    )
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    app = create_fake_training_worker_app(settings, redis=redis)
    headers = {INTERNAL_TOKEN_HEADER: settings.internal_token}

    with TestClient(app) as client:
        assert client.post("/load_model", json={"mode": "sft"}, headers=headers).status_code == 200
        hold = client.post("/gpu_hold/reserve", headers=headers)
        assert hold.status_code == 200
        task = client.post(
            "/tasks/train_lora",
            json=_training_request(dataset_dir, output_dir, hold.json()["token"]),
            headers=headers,
        )
        assert task.status_code == 200
        stream = client.get(f"/tasks/{task.json()['task_id']}/stream")

    assert stream.status_code == 200
    events = _events(stream.text)
    progress = [data for event_type, data in events if event_type == "progress"]
    assert progress
    assert all(data["current_epoch"] is not None for data in progress)
    assert all(data["train_epochs"] == 4 for data in progress)
    done = next(data for event_type, data in events if event_type == "done")
    assert done["result"]["adapter_dir"] == str(output_dir)
    assert (output_dir / "adapter_model.safetensors").is_file()


def test_fake_generation_wav_is_deterministic_and_binds_every_input() -> None:
    prompt = "warm e2e tenor"
    seed = 1234
    adapter_a = "/app/data/audio/user_loras/u1/a/output"
    adapter_b = "/app/data/audio/user_loras/u1/b/output"

    baseline = fake_generation_wav_bytes(prompt, seed, None)
    assert baseline == fake_generation_wav_bytes(prompt, seed, "")
    assert baseline == fake_generation_wav_bytes(prompt, seed, None)
    assert baseline != fake_generation_wav_bytes("different prompt", seed, None)
    assert baseline != fake_generation_wav_bytes(prompt, seed + 1, None)
    assert baseline != fake_generation_wav_bytes(prompt, seed, adapter_a)
    assert fake_generation_wav_bytes(prompt, seed, adapter_a) != fake_generation_wav_bytes(
        prompt, seed, adapter_b
    )

    with wave.open(BytesIO(baseline), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 8_000
        assert wav.getnframes() == 8_000

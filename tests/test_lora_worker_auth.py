"""1301-F10-HTTP: LoRA authentication across an owned HTTP boundary."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

import fakeredis.aioredis
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from worker_http_peer import LoopbackServer

from songmaker_cli.acestep_state import worker_state_key
from songmaker_cli.constants import INTERNAL_TOKEN_HEADER, JobStatus, JobType, LoraStatus
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Job, User, UserLora, UserLoraSample
from songmaker_cli.db.queries.jobs import get_job
from songmaker_cli.db.queries.loras import get_user_lora
from songmaker_cli.db.queries.workers import register_worker
from songmaker_cli.jobs.lora_training import run_lora_training_job
from songmaker_cli.settings import get_settings


class LoraAuthPeer:
    def __init__(self, token: str) -> None:
        self.token = token
        self.requests: list[tuple[str, str | None]] = []
        self.adapter_dir: Path | None = None
        self.app = Starlette(
            routes=[
                Route("/{path:path}", self.respond, methods=["GET", "POST"]),
            ]
        )

    async def respond(self, request: Request) -> Response:
        path = request.url.path
        token = request.headers.get(INTERNAL_TOKEN_HEADER)
        self.requests.append((path, token))
        if token != self.token:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        if path == "/gpu_hold/reserve":
            return JSONResponse({"token": "lora-hold"})
        if path in {"/gpu_hold/renew", "/gpu_hold/release", "/load_model"}:
            return JSONResponse({})
        if path == "/tasks/train_lora":
            payload = await request.json()
            self.adapter_dir = Path(payload["output_dir"])
            self.adapter_dir.mkdir(parents=True)
            (self.adapter_dir / "adapter_config.json").write_text("{}")
            return JSONResponse({"task_id": "training"})
        if path == "/tasks/training/stream":
            assert self.adapter_dir is not None
            result = {"mode": "sft", "adapter_dir": str(self.adapter_dir), "num_samples": 1}
            return Response(
                f"event: done\ndata: {json.dumps({'result': result})}\n\n",
                media_type="text/event-stream",
            )
        return JSONResponse({"detail": "Unknown route"}, status_code=404)


@pytest.fixture
def lora_auth_db(tmp_path: Path):
    """1301-F10-HTTP: real persistence and sample input for the public job."""
    factory = init_test_db(tmp_path / "lora.db")
    (tmp_path / "sample.wav").write_bytes(b"RIFF0000WAVEfmt ")
    with factory() as session:
        session.add(User(id="user", username="trainer", role="user"))
        session.add(
            UserLora(
                id="lora",
                user_id="user",
                name="Proof",
                slug="proof",
                status=LoraStatus.QUEUED,
                training_job_id="job",
            )
        )
        session.add(
            UserLoraSample(
                id="sample",
                user_lora_id="lora",
                audio_path="sample.wav",
                caption="sample",
                lyrics="lyrics",
                position=0,
            )
        )
        session.add(Job(id="job", type=JobType.LORA_TRAINING, status=JobStatus.QUEUED))
        session.commit()
    return factory


@pytest.mark.parametrize(
    ("accepted_token_suffix", "lora_status", "job_status", "adapter_published", "paths"),
    [
        pytest.param(
            "", LoraStatus.READY, JobStatus.COMPLETED, True,
            ["/load_model", "/tasks/training/stream"], id="configured",
        ),
        pytest.param(
            "-different", LoraStatus.FAILED, JobStatus.FAILED, False,
            ["/gpu_hold/reserve"], id="mismatched-at-first-worker-request",
        ),
    ],
)
def test_lora_job_sends_configured_token_and_fails_on_worker_token_mismatch(
    accepted_token_suffix: str,
    lora_status: LoraStatus,
    job_status: JobStatus,
    adapter_published: bool,
    paths: list[str],
    internal_token: str,
    lora_auth_db,
    tmp_path: Path,
) -> None:
    """1301-F10-HTTP: load and stream requests carry the configured token.

    A mismatch fails the job at its first worker request, /gpu_hold/reserve,
    without publishing an adapter.
    """

    async def exercise() -> None:
        peer = LoraAuthPeer(internal_token + accepted_token_suffix)
        server = LoopbackServer(peer.app)
        async with fakeredis.aioredis.FakeRedis() as redis:
            try:
                async with asyncio.timeout(15):
                    base_url = await server.start()
                    with lora_auth_db() as session:
                        register_worker(
                            session,
                            worker_id="worker",
                            host="127.0.0.1",
                            port=urlsplit(base_url).port,
                            gpu_id=None,
                            vram_total_gb=24,
                        )
                        session.commit()
                    await redis.set(
                        worker_state_key("worker"),
                        json.dumps(
                            {
                                "loaded": [],
                                "gpu_healthy": True,
                            }
                        ),
                    )
                    await run_lora_training_job(
                        {},
                        "job",
                        "lora",
                        "user",
                        db_factory=lora_auth_db,
                        audio_dir=tmp_path,
                        redis=redis,
                        target_mode="sft",
                        training_config=get_settings().lora_training_config,
                    )
                    with lora_auth_db() as session:
                        lora = get_user_lora(session, "lora")
                        assert lora.status == lora_status
                        assert get_job(session, "job").status == job_status
                        assert (lora.storage_path is not None) == adapter_published
                    assert bool(list(tmp_path.rglob("adapter_config.json"))) == adapter_published
                    for path in paths:
                        assert (path, internal_token) in peer.requests
            finally:
                async with asyncio.timeout(3):
                    await server.stop()

    asyncio.run(exercise())

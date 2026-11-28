"""Database and audio-directory arrangement for LoRA training job tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.audio_paths import USER_LORAS_DIRNAME
from songmaker_cli.constants import LoraStatus
from songmaker_cli.db.models import Job, User, UserLora, UserLoraSample
from songmaker_cli.job_types import JobType


def seed_queued_lora(db_factory: sessionmaker[Session], tmp_path: Path) -> dict:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    user_id = "user-1"
    lora_id = "lora-1"
    sample_dir = audio_dir / USER_LORAS_DIRNAME / user_id / lora_id / "samples"
    sample_dir.mkdir(parents=True)
    sample_ids = ["sample-a", "sample-b", "sample-c"]
    sample_files: list[str] = []
    for sid in sample_ids:
        f = sample_dir / f"{sid}.wav"
        f.write_bytes(b"RIFF0000WAVEfmt ")
        sample_files.append(
            f"{USER_LORAS_DIRNAME}/{user_id}/{lora_id}/samples/{sid}.wav",
        )

    with db_factory() as session:
        session.add(
            User(id=user_id, username="u1", role="user"),
        )
        session.add(
            UserLora(
                id=lora_id,
                user_id=user_id,
                name="My LoRA",
                slug="my-lora",
                status=LoraStatus.QUEUED,
                training_job_id="job-1",
            ),
        )
        for idx, sid in enumerate(sample_ids):
            session.add(
                UserLoraSample(
                    id=sid,
                    user_lora_id=lora_id,
                    audio_path=sample_files[idx],
                    caption=f"caption {idx}",
                    lyrics=f"lyrics {idx}",
                    position=idx,
                ),
            )
        session.add(Job(id="job-1", type=JobType.LORA_TRAINING, status="queued"))
        session.commit()

    return {
        "audio_dir": audio_dir,
        "user_id": user_id,
        "lora_id": lora_id,
        "sample_ids": sample_ids,
    }


class FakeWorker:
    id = "w0"
    base_url = "http://fake"
    loaded_modes = ("sft",)


async def fake_events_ok(*args, **kwargs) -> AsyncIterator[tuple[str, dict]]:
    yield ("progress", {"progress": 0.05, "current_epoch": 0, "train_epochs": 500})
    yield ("progress", {"progress": 0.25, "current_epoch": 25, "train_epochs": 500})
    yield ("progress", {"progress": 0.90, "current_epoch": 500, "train_epochs": 500})
    yield (
        "done",
        {
            "result": {
                "mode": "sft",
                "adapter_dir": "",
                "num_samples": 3,
            },
        },
    )


def patch_worker_calls(adapter_dir: str, *, events=None, submitted_requests=None):
    """Return context-manager patches for worker-side HTTP + SSE stubs."""
    events = events or fake_events_ok

    @contextmanager
    def _cm():
        submit = AsyncMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(return_value={"task_id": "t-1"})

        async def post(*args, **kwargs):
            if submitted_requests is not None:
                submitted_requests.append((args[0], kwargs.get("json")))
            if args[0].endswith("/gpu_hold/reserve"):
                response.json = MagicMock(return_value={"token": "hold-token"})
            elif args[0].endswith("/tasks/train_lora"):
                response.json = MagicMock(return_value={"task_id": "t-1"})
            return response

        submit.post = AsyncMock(side_effect=post)
        submit.__aenter__ = AsyncMock(return_value=submit)
        submit.__aexit__ = AsyncMock(return_value=None)

        async def async_events(*_a, **_kw):
            async for ev_type, data in events(*_a, **_kw):
                if ev_type == "done" and isinstance(data.get("result"), dict):
                    if not data["result"].get("adapter_dir"):
                        data["result"]["adapter_dir"] = adapter_dir
                    Path(adapter_dir).parent.mkdir(parents=True, exist_ok=True)
                    if not Path(adapter_dir).exists():
                        Path(adapter_dir).mkdir(parents=True)
                        (Path(adapter_dir) / "adapter_config.json").write_text("{}")
                yield ev_type, data

        with (
            patch(
                "songmaker_cli.jobs.lora_training.pick_worker",
                AsyncMock(return_value=FakeWorker()),
            ),
            patch(
                "songmaker_cli.jobs.lora_training._iterate_task_events",
                async_events,
            ),
            patch(
                "httpx.AsyncClient",
                return_value=submit,
            ),
        ):
            yield

    return _cm()

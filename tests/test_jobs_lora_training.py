"""Tests for songmaker_cli.jobs.lora_training.run_lora_training_job.

The worker HTTP bridge is mocked: we stub ``pick_worker`` and
``_iterate_task_events`` so the unit test exercises the songmaker-side
orchestration (dataset materialization, DB state transitions, cleanup,
audit) without a real ACE-Step subprocess.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from songmaker_cli.constants import (
    USER_LORA_DATASET_DIRNAME,
    USER_LORA_OUTPUT_DIRNAME,
    USER_LORAS_DIRNAME,
    JobStatus,
    JobType,
    LoraStatus,
)
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import AuditLog, Job, User, UserLora, UserLoraSample
from songmaker_cli.db.queries import get_job, get_user_lora
from songmaker_cli.jobs.lora_training import (
    _validate_export_path,
    cleanup_failed_lora_with_factory,
    run_lora_training_job,
)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def db_factory(tmp_path: Path):
    return init_db(tmp_path / "test.db")


@pytest.fixture()
def seeded(db_factory, tmp_path: Path) -> dict:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    user_id = "user-1"
    lora_id = "lora-1"
    sample_dir = (
        audio_dir / USER_LORAS_DIRNAME / user_id / lora_id / "samples"
    )
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
            User(id=user_id, username="u1", password_hash="x", role="user"),
        )
        session.add(
            UserLora(
                id=lora_id, user_id=user_id, name="My LoRA", slug="my-lora",
                status=LoraStatus.QUEUED, training_job_id="job-1",
            ),
        )
        for idx, sid in enumerate(sample_ids):
            session.add(
                UserLoraSample(
                    id=sid, user_lora_id=lora_id, audio_path=sample_files[idx],
                    caption=f"caption {idx}", lyrics=f"lyrics {idx}",
                    position=idx,
                ),
            )
        session.add(Job(id="job-1", type=JobType.LORA_TRAINING, status="queued"))
        session.commit()

    return {
        "audio_dir": audio_dir, "user_id": user_id, "lora_id": lora_id,
        "sample_ids": sample_ids,
    }


class _FakeWorker:
    id = "w0"
    base_url = "http://fake"
    loaded_modes = ("sft",)


async def _fake_events_ok(*args, **kwargs) -> AsyncIterator[tuple[str, dict]]:
    yield ("progress", {"progress": 0.05})
    yield ("progress", {"progress": 0.25})
    yield ("progress", {"progress": 0.80})
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


def _patch_worker_calls(adapter_dir: str, *, events=None):
    """Return context-manager patches for worker-side HTTP + SSE stubs."""
    from contextlib import contextmanager

    events = events or _fake_events_ok

    @contextmanager
    def _cm():
        submit = AsyncMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(return_value={"task_id": "t-1"})
        submit.post = AsyncMock(return_value=response)
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
                AsyncMock(return_value=_FakeWorker()),
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


def test_happy_path_transitions_and_persists(seeded, db_factory, tmp_path) -> None:
    output_dir = (
        seeded["audio_dir"] / USER_LORAS_DIRNAME / seeded["user_id"]
        / seeded["lora_id"] / "training_tmp"
    )

    def _create_adapter_dir() -> str:
        adapter = output_dir / "final"
        adapter.parent.mkdir(parents=True, exist_ok=True)
        adapter.mkdir(exist_ok=True)
        (adapter / "adapter_config.json").write_text("{}")
        return str(adapter)

    adapter_src = _create_adapter_dir()

    with _patch_worker_calls(adapter_src):
        _run(run_lora_training_job(
            {}, "job-1", seeded["lora_id"], seeded["user_id"],
            db_factory=db_factory, audio_dir=seeded["audio_dir"],
            redis=MagicMock(),
        ))

    with db_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        assert lora.status == LoraStatus.READY
        assert lora.storage_path is not None
        assert lora.storage_path.endswith(
            f"/{seeded['lora_id']}/{USER_LORA_OUTPUT_DIRNAME}",
        )
        assert lora.error is None
        assert lora.completed_at is not None

        job = get_job(session, "job-1")
        assert job.status == JobStatus.COMPLETED

        audits = session.query(AuditLog).filter_by(
            user_id=seeded["user_id"], resource_id=seeded["lora_id"],
        ).all()
        actions = [a.detail for a in audits]
        assert any("ready" in d for d in actions)

    final_path = (
        seeded["audio_dir"] / USER_LORAS_DIRNAME / seeded["user_id"]
        / seeded["lora_id"] / USER_LORA_OUTPUT_DIRNAME
    )
    dataset_path = (
        seeded["audio_dir"] / USER_LORAS_DIRNAME / seeded["user_id"]
        / seeded["lora_id"] / USER_LORA_DATASET_DIRNAME
    )
    assert final_path.exists()
    assert not dataset_path.exists()


def test_dataset_materialization_writes_files(seeded, db_factory, tmp_path) -> None:
    from songmaker_cli.jobs.lora_training import _materialize_dataset

    with db_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        samples = list(lora.samples)

    dataset_dir = _materialize_dataset(
        audio_dir=seeded["audio_dir"],
        user_id=seeded["user_id"], lora_id=seeded["lora_id"], samples=samples,
    )
    for sid in seeded["sample_ids"]:
        assert (dataset_dir / f"{sid}.wav").exists()
        caption = (dataset_dir / f"{sid}.caption.txt").read_text()
        lyrics = (dataset_dir / f"{sid}.lyrics.txt").read_text()
        assert "caption" in caption
        assert "lyrics" in lyrics


def test_missing_sample_audio_raises_and_marks_failed(
    seeded, db_factory,
) -> None:
    sample_path = seeded["audio_dir"] / (
        f"{USER_LORAS_DIRNAME}/{seeded['user_id']}/{seeded['lora_id']}"
        f"/samples/sample-a.wav"
    )
    sample_path.unlink()

    _run(run_lora_training_job(
        {}, "job-1", seeded["lora_id"], seeded["user_id"],
        db_factory=db_factory, audio_dir=seeded["audio_dir"],
        redis=MagicMock(),
    ))
    with db_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        assert lora.status == LoraStatus.FAILED
        assert lora.error is not None


def test_cancellation_triggers_cleanup(seeded, db_factory) -> None:
    async def raising_events(*args, **kwargs):
        raise asyncio.CancelledError()
        yield  # unreachable

    from contextlib import contextmanager

    @contextmanager
    def patches():
        submit = AsyncMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(return_value={"task_id": "t-1"})
        submit.post = AsyncMock(return_value=response)
        submit.__aenter__ = AsyncMock(return_value=submit)
        submit.__aexit__ = AsyncMock(return_value=None)
        with (
            patch(
                "songmaker_cli.jobs.lora_training.pick_worker",
                AsyncMock(return_value=_FakeWorker()),
            ),
            patch(
                "songmaker_cli.jobs.lora_training._iterate_task_events",
                raising_events,
            ),
            patch("httpx.AsyncClient", return_value=submit),
        ):
            yield

    with patches():
        with pytest.raises(asyncio.CancelledError):
            _run(run_lora_training_job(
                {}, "job-1", seeded["lora_id"], seeded["user_id"],
                db_factory=db_factory, audio_dir=seeded["audio_dir"],
                redis=MagicMock(),
            ))

    with db_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        assert lora.status == LoraStatus.FAILED


def test_path_traversal_in_adapter_dir_rejected(seeded, db_factory) -> None:
    malicious = "/etc/passwd"
    with _patch_worker_calls(malicious):
        _run(run_lora_training_job(
            {}, "job-1", seeded["lora_id"], seeded["user_id"],
            db_factory=db_factory, audio_dir=seeded["audio_dir"],
            redis=MagicMock(),
        ))
    with db_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        assert lora.status == LoraStatus.FAILED
        assert lora.error is not None


def test_validate_export_path_accepts_inside_user_dir(tmp_path) -> None:
    user_dir = tmp_path / "audio" / USER_LORAS_DIRNAME / "u1" / "L1" / "training_tmp" / "final"
    user_dir.mkdir(parents=True)
    resolved = _validate_export_path(
        audio_dir=tmp_path / "audio", user_id="u1", reported=str(user_dir),
    )
    assert resolved == user_dir.resolve()


def test_validate_export_path_rejects_outside(tmp_path) -> None:
    with pytest.raises(ValueError):
        _validate_export_path(
            audio_dir=tmp_path / "audio", user_id="u1", reported="/etc/shadow",
        )


def test_cleanup_failed_lora_removes_dirs(seeded, db_factory) -> None:
    audio_dir = seeded["audio_dir"]
    lora_root = (
        audio_dir / USER_LORAS_DIRNAME / seeded["user_id"] / seeded["lora_id"]
    )
    (lora_root / USER_LORA_DATASET_DIRNAME).mkdir(parents=True, exist_ok=True)
    (lora_root / USER_LORA_OUTPUT_DIRNAME).mkdir(parents=True, exist_ok=True)
    (lora_root / "training_tmp").mkdir(parents=True, exist_ok=True)
    (lora_root / USER_LORA_DATASET_DIRNAME / "stub.txt").write_text("x")

    cleanup_failed_lora_with_factory(
        lora_id=seeded["lora_id"], user_id=seeded["user_id"],
        audio_dir=audio_dir, db_factory=db_factory,
        error_message="testing",
    )
    assert not (lora_root / USER_LORA_DATASET_DIRNAME).exists()
    assert not (lora_root / USER_LORA_OUTPUT_DIRNAME).exists()

    with db_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        assert lora.status == LoraStatus.FAILED
        assert lora.error == "testing"
        audit = session.query(AuditLog).filter_by(
            resource_id=seeded["lora_id"],
        ).all()
        assert any("failed" in (a.detail or "") for a in audit)


def test_deleted_lora_rejected(seeded, db_factory) -> None:
    from datetime import datetime, timezone

    with db_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"], include_deleted_rows=True)
        lora.deleted_at = datetime.now(timezone.utc)
        session.commit()

    _run(run_lora_training_job(
        {}, "job-1", seeded["lora_id"], seeded["user_id"],
        db_factory=db_factory, audio_dir=seeded["audio_dir"],
        redis=MagicMock(),
    ))
    with db_factory() as session:
        job = get_job(session, "job-1")
        assert job.status == JobStatus.FAILED
        assert "deleted" in (job.error or "").lower()


def test_missing_lora_fails_job(seeded, db_factory) -> None:
    _run(run_lora_training_job(
        {}, "job-1", "does-not-exist", seeded["user_id"],
        db_factory=db_factory, audio_dir=seeded["audio_dir"],
        redis=MagicMock(),
    ))
    with db_factory() as session:
        job = get_job(session, "job-1")
        assert job.status == JobStatus.FAILED


def test_no_capacity_marks_failed(seeded, db_factory) -> None:
    from songmaker_cli.scheduler import NoCapacityError

    with patch(
        "songmaker_cli.jobs.lora_training.pick_worker",
        AsyncMock(side_effect=NoCapacityError("no workers")),
    ):
        _run(run_lora_training_job(
            {}, "job-1", seeded["lora_id"], seeded["user_id"],
            db_factory=db_factory, audio_dir=seeded["audio_dir"],
            redis=MagicMock(),
        ))
    with db_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        assert lora.status == LoraStatus.FAILED
        job = get_job(session, "job-1")
        assert job.status == JobStatus.FAILED


def test_run_without_factory_raises(db_factory, tmp_path) -> None:
    with pytest.raises(RuntimeError):
        _run(run_lora_training_job({}, "j", "l", "u"))

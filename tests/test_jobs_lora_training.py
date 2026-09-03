"""Tests for songmaker_cli.jobs.lora_training.run_lora_training_job.

The worker HTTP bridge is mocked: we stub ``pick_worker`` and
``_iterate_task_events`` so the unit test exercises the songmaker-side
orchestration (dataset materialization, DB state transitions, cleanup,
audit) without a real ACE-Step subprocess.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
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
    reconcile_crashed_loras,
    run_lora_training_job,
)
from songmaker_cli.lifecycle import reap_stale_jobs
from songmaker_cli.settings import Settings
from songmaker_cli.worker_liveness import WorkerLiveness

TEST_SETTINGS = Settings(
    database_url="postgresql://example",
    redis_url="redis://example",
    session_secret="session-secret",
    songmaker_internal_token="internal-token",
)
TEST_LORA_TRAINING_CONFIG = TEST_SETTINGS.lora_training_config


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


def _patch_worker_calls(adapter_dir: str, *, events=None, submitted_requests=None):
    """Return context-manager patches for worker-side HTTP + SSE stubs."""
    from contextlib import contextmanager

    events = events or _fake_events_ok

    @contextmanager
    def _cm():
        submit = AsyncMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(return_value={"task_id": "t-1"})
        async def post(*args, **kwargs):
            if submitted_requests is not None:
                submitted_requests.append((args[0], kwargs["json"]))
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


def test_happy_path_transitions_and_persists(seeded, db_factory, tmp_path, caplog) -> None:
    output_dir = (
        seeded["audio_dir"] / USER_LORAS_DIRNAME / seeded["user_id"]
        / seeded["lora_id"] / "training_tmp"
    )

    def _create_adapter_dir() -> str:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "adapter_config.json").write_text("{}")
        return str(output_dir)

    adapter_src = _create_adapter_dir()

    submitted_requests: list[tuple[str, dict]] = []
    with _patch_worker_calls(adapter_src, submitted_requests=submitted_requests):
        _run(run_lora_training_job(
            {}, "job-1", seeded["lora_id"], seeded["user_id"],
            db_factory=db_factory, audio_dir=seeded["audio_dir"],
            redis=MagicMock(),
            training_config=TEST_LORA_TRAINING_CONFIG,
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
    assert not any(
        "Failed to remove tmp training dir" in record.message
        for record in caplog.records
    )
    assert submitted_requests == [
        ("http://fake/load_model", {"mode": "sft"}),
        ("http://fake/tasks/train_lora", {
            "mode": "sft",
            "dataset_dir": str(dataset_path),
            "output_dir": str(output_dir),
            **TEST_LORA_TRAINING_CONFIG.payload(),
        }),
    ]


@pytest.fixture()
def fake_clock():
    class FakeClock:
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)

        def advance(self, seconds: int) -> None:
            self.now += timedelta(seconds=seconds)

    return FakeClock()


def test_training_progress_keeps_a_long_running_lora_alive(
    seeded, db_factory, fake_clock,
) -> None:
    generation_timeout_seconds = TEST_SETTINGS.arq_job_timeout
    assert TEST_LORA_TRAINING_CONFIG.train_epochs == 500
    assert TEST_SETTINGS.lora_training_job_timeout > generation_timeout_seconds

    output_dir = (
        seeded["audio_dir"] / USER_LORAS_DIRNAME / seeded["user_id"]
        / seeded["lora_id"] / "training_tmp"
    )

    async def progress_for_long_training(*_args, **_kwargs):
        yield ("progress", {"progress": 0.20})
        fake_clock.advance(generation_timeout_seconds + 1)
        yield ("progress", {"progress": 0.80})
        assert reap_stale_jobs(
            SimpleNamespace(db=db_factory),
            now=fake_clock.now,
            worker_liveness={JobType.LORA_TRAINING: WorkerLiveness.ALIVE},
        ) == 0
        yield (
            "done",
            {"result": {"mode": "sft", "adapter_dir": "", "num_samples": 3}},
        )

    def touch_heartbeat(_db_factory, job_id: str) -> None:
        with db_factory() as session:
            job = get_job(session, job_id)
            job.heartbeat_at = fake_clock.now
            session.commit()

    with (
        _patch_worker_calls(str(output_dir), events=progress_for_long_training),
        patch("songmaker_cli.jobs.lora_training._touch_heartbeat", touch_heartbeat),
    ):
        _run(run_lora_training_job(
            {}, "job-1", seeded["lora_id"], seeded["user_id"],
            db_factory=db_factory, audio_dir=seeded["audio_dir"], redis=MagicMock(),
            training_config=TEST_LORA_TRAINING_CONFIG,
        ))

    with db_factory() as session:
        assert get_user_lora(session, seeded["lora_id"]).status == LoraStatus.READY
        assert get_job(session, "job-1").status == JobStatus.COMPLETED


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
        training_config=TEST_LORA_TRAINING_CONFIG,
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
                training_config=TEST_LORA_TRAINING_CONFIG,
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
            training_config=TEST_LORA_TRAINING_CONFIG,
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
    with pytest.raises(ValueError):
        _validate_export_path(
            audio_dir=tmp_path / "audio",
            user_id="u1",
            reported=str(tmp_path / "audio" / USER_LORAS_DIRNAME / "u1"),
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
    assert (lora_root / USER_LORA_OUTPUT_DIRNAME).exists()
    assert not (lora_root / "training_tmp").exists()

    with db_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        assert lora.status == LoraStatus.FAILED
        assert lora.error == "testing"
        audit = session.query(AuditLog).filter_by(
            resource_id=seeded["lora_id"],
        ).all()
        assert any("failed" in (a.detail or "") for a in audit)


@pytest.mark.parametrize(
    ("crash_point", "expected_adapter_file"),
    [
        ("after_first_rename", "adapter.txt"),
        ("after_second_rename", "adapter_config.json"),
        ("after_previous_cleanup", "adapter_config.json"),
    ],
)
def test_reconcile_crashed_lora_preserves_an_adapter_after_adoption_crash(
    seeded, db_factory, monkeypatch, crash_point: str,
    expected_adapter_file: str,
) -> None:
    from songmaker_cli.jobs import lora_training

    lora_root = (
        seeded["audio_dir"]
        / USER_LORAS_DIRNAME
        / seeded["user_id"]
        / seeded["lora_id"]
    )
    final_dir = lora_root / USER_LORA_OUTPUT_DIRNAME
    previous_dir = final_dir.with_name(f"{final_dir.name}.previous")
    final_dir.mkdir(parents=True)
    (final_dir / "adapter.txt").write_text("old")
    temporary_dir = lora_root / "training_tmp"

    original_rename = lora_training.os.rename
    rename_count = 0

    def crash_during_adoption(source, destination) -> None:
        nonlocal rename_count
        original_rename(source, destination)
        rename_count += 1
        if (
            crash_point == "after_first_rename" and rename_count == 1
        ) or (
            crash_point == "after_second_rename" and rename_count == 2
        ):
            raise SystemExit("simulated process crash")

    monkeypatch.setattr(lora_training.os, "rename", crash_during_adoption)
    original_rmtree = lora_training.shutil.rmtree

    def crash_after_previous_cleanup(path, *args, **kwargs) -> None:
        original_rmtree(path, *args, **kwargs)
        if crash_point == "after_previous_cleanup" and Path(path) == previous_dir:
            raise SystemExit("simulated process crash")

    monkeypatch.setattr(lora_training.shutil, "rmtree", crash_after_previous_cleanup)

    with _patch_worker_calls(str(temporary_dir)):
        with pytest.raises(SystemExit, match="simulated process crash"):
            _run(run_lora_training_job(
                {}, "job-1", seeded["lora_id"], seeded["user_id"],
                db_factory=db_factory, audio_dir=seeded["audio_dir"],
                redis=MagicMock(),
                training_config=TEST_LORA_TRAINING_CONFIG,
            ))

    with db_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        job = get_job(session, "job-1")
        job.status = JobStatus.FAILED
        session.commit()

    assert reconcile_crashed_loras(db_factory, seeded["audio_dir"]) == 1
    assert (final_dir / expected_adapter_file).exists()
    assert not previous_dir.exists()
    with db_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        assert lora.status == LoraStatus.READY


def test_adoption_stays_ready_when_previous_cleanup_fails(
    seeded, db_factory, monkeypatch, caplog,
) -> None:
    from songmaker_cli.jobs import lora_training

    lora_root = (
        seeded["audio_dir"]
        / USER_LORAS_DIRNAME
        / seeded["user_id"]
        / seeded["lora_id"]
    )
    final_dir = lora_root / USER_LORA_OUTPUT_DIRNAME
    previous_dir = final_dir.with_name(f"{final_dir.name}.previous")
    final_dir.mkdir(parents=True)
    (final_dir / "adapter.txt").write_text("old")
    temporary_dir = lora_root / "training_tmp"
    original_rmtree = lora_training.shutil.rmtree

    def fail_to_remove_previous(path, *args, **kwargs) -> None:
        if Path(path) == previous_dir:
            raise OSError("simulated cleanup failure")
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(lora_training.shutil, "rmtree", fail_to_remove_previous)

    with _patch_worker_calls(str(temporary_dir)):
        _run(run_lora_training_job(
            {}, "job-1", seeded["lora_id"], seeded["user_id"],
            db_factory=db_factory, audio_dir=seeded["audio_dir"],
            redis=MagicMock(),
            training_config=TEST_LORA_TRAINING_CONFIG,
        ))

    assert (final_dir / "adapter_config.json").exists()
    assert previous_dir.exists()
    assert "Failed to remove previous LoRA adapter" in caplog.text
    with db_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        assert lora.status == LoraStatus.READY


def test_adoption_restores_the_previous_adapter_when_second_rename_fails(
    seeded, db_factory, monkeypatch,
) -> None:
    from songmaker_cli.jobs import lora_training

    lora_root = (
        seeded["audio_dir"]
        / USER_LORAS_DIRNAME
        / seeded["user_id"]
        / seeded["lora_id"]
    )
    final_dir = lora_root / USER_LORA_OUTPUT_DIRNAME
    previous_dir = final_dir.with_name(f"{final_dir.name}.previous")
    final_dir.mkdir(parents=True)
    (final_dir / "adapter.txt").write_text("old")
    temporary_dir = lora_root / "training_tmp"
    original_rename = lora_training.os.rename
    rename_count = 0

    def fail_second_rename(source, destination) -> None:
        nonlocal rename_count
        rename_count += 1
        if rename_count == 2:
            raise OSError("simulated second rename failure")
        original_rename(source, destination)

    monkeypatch.setattr(lora_training.os, "rename", fail_second_rename)

    with _patch_worker_calls(str(temporary_dir)):
        _run(run_lora_training_job(
            {}, "job-1", seeded["lora_id"], seeded["user_id"],
            db_factory=db_factory, audio_dir=seeded["audio_dir"],
            redis=MagicMock(),
            training_config=TEST_LORA_TRAINING_CONFIG,
        ))

    assert (final_dir / "adapter.txt").read_text() == "old"
    assert not previous_dir.exists()
    assert not temporary_dir.exists()
    with db_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        job = get_job(session, "job-1")
        assert lora.status == LoraStatus.READY
        assert job.status == JobStatus.FAILED


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
        training_config=TEST_LORA_TRAINING_CONFIG,
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
        training_config=TEST_LORA_TRAINING_CONFIG,
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
            training_config=TEST_LORA_TRAINING_CONFIG,
        ))
    with db_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        assert lora.status == LoraStatus.FAILED
        assert lora.error == "No ACE-Step workers available"
        assert "no workers" not in lora.error
        job = get_job(session, "job-1")
        assert job.status == JobStatus.FAILED
        assert job.error == "No ACE-Step workers available"


def test_run_without_factory_raises(db_factory, tmp_path) -> None:
    with pytest.raises(RuntimeError):
        _run(run_lora_training_job({}, "j", "l", "u"))

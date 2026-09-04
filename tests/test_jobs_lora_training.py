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


@pytest.fixture(autouse=True)
def lora_training_config(monkeypatch: pytest.MonkeyPatch) -> None:
    job_runner = run_lora_training_job

    async def run_with_test_training_config(*args, **kwargs) -> None:
        kwargs.setdefault("training_config", TEST_LORA_TRAINING_CONFIG)
        await job_runner(*args, **kwargs)

    monkeypatch.setattr(
        "test_jobs_lora_training.run_lora_training_job",
        run_with_test_training_config,
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
            User(id=user_id, username="u1", password_hash="x", role="user"),
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


class _FakeWorker:
    id = "w0"
    base_url = "http://fake"
    loaded_modes = ("sft",)


async def _fake_events_ok(*args, **kwargs) -> AsyncIterator[tuple[str, dict]]:
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


def _patch_worker_calls(adapter_dir: str, *, events=None, submitted_requests=None):
    """Return context-manager patches for worker-side HTTP + SSE stubs."""
    from contextlib import contextmanager

    events = events or _fake_events_ok

    @contextmanager
    def _cm():
        submit = AsyncMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        handover_response = MagicMock()
        handover_response.raise_for_status = MagicMock()
        handover_response.json.return_value = {"claimed": True, "task_id": "t-1"}
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
        seeded["audio_dir"]
        / USER_LORAS_DIRNAME
        / seeded["user_id"]
        / seeded["lora_id"]
        / "training_tmp"
    )

    def _create_adapter_dir() -> str:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "adapter_config.json").write_text("{}")
        return str(output_dir)

    adapter_src = _create_adapter_dir()

    submitted_requests: list[tuple[str, dict]] = []
    with _patch_worker_calls(adapter_src, submitted_requests=submitted_requests):
        _run(
            run_lora_training_job(
                {},
                "job-1",
                seeded["lora_id"],
                seeded["user_id"],
                db_factory=db_factory,
                audio_dir=seeded["audio_dir"],
                redis=MagicMock(),
                training_config=TEST_LORA_TRAINING_CONFIG,
            )
        )

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
        assert job.current_epoch == 500
        assert job.train_epochs == 500

        audits = (
            session.query(AuditLog)
            .filter_by(
                user_id=seeded["user_id"],
                resource_id=seeded["lora_id"],
            )
            .all()
        )
        actions = [a.detail for a in audits]
        assert any("ready" in d for d in actions)

    final_path = (
        seeded["audio_dir"]
        / USER_LORAS_DIRNAME
        / seeded["user_id"]
        / seeded["lora_id"]
        / USER_LORA_OUTPUT_DIRNAME
    )
    dataset_path = (
        seeded["audio_dir"]
        / USER_LORAS_DIRNAME
        / seeded["user_id"]
        / seeded["lora_id"]
        / USER_LORA_DATASET_DIRNAME
    )
    assert final_path.exists()
    assert not dataset_path.exists()
    assert not any(
        "Failed to remove tmp training dir" in record.message for record in caplog.records
    )
    assert submitted_requests == [
        ("http://fake/gpu_hold/reserve", None),
        ("http://fake/load_model", {"mode": "sft"}),
        (
            "http://fake/tasks/train_lora",
            {
                "mode": "sft",
                "dataset_dir": str(dataset_path),
                "output_dir": str(output_dir),
                "hold_token": "hold-token",
                **TEST_LORA_TRAINING_CONFIG.payload(),
            },
        ),
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
        yield ("progress", {"progress": 0.20, "current_epoch": 0, "train_epochs": 500})
        fake_clock.advance(generation_timeout_seconds + 1)
        yield ("progress", {"progress": 0.80, "current_epoch": 400, "train_epochs": 500})
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
            db_factory=db_factory,
            audio_dir=seeded["audio_dir"],
            redis=MagicMock(),
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
        user_id=seeded["user_id"],
        lora_id=seeded["lora_id"],
        samples=samples,
    )
    for sid in seeded["sample_ids"]:
        assert (dataset_dir / f"{sid}.wav").exists()
        caption = (dataset_dir / f"{sid}.caption.txt").read_text()
        lyrics = (dataset_dir / f"{sid}.lyrics.txt").read_text()
        assert "caption" in caption
        assert "lyrics" in lyrics


def test_missing_sample_audio_raises_and_marks_failed(
    seeded,
    db_factory,
) -> None:
    sample_path = seeded["audio_dir"] / (
        f"{USER_LORAS_DIRNAME}/{seeded['user_id']}/{seeded['lora_id']}/samples/sample-a.wav"
    )
    sample_path.unlink()

    _run(
        run_lora_training_job(
            {},
            "job-1",
            seeded["lora_id"],
            seeded["user_id"],
            db_factory=db_factory,
            audio_dir=seeded["audio_dir"],
            redis=MagicMock(),
        )
    )
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

        async def post(url, **kwargs):
            response.json = MagicMock(
                return_value={"token": "hold-token"}
                if url.endswith("/gpu_hold/reserve")
                else {"task_id": "t-1"},
            )
            return response

        submit.post = AsyncMock(side_effect=post)
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

    with db_factory() as session:
        get_job(session, "job-1").queue_reason = "Waiting for LoRA training on this GPU."
        session.commit()

    with patches():
        with pytest.raises(asyncio.CancelledError):
            _run(
                run_lora_training_job(
                    {},
                    "job-1",
                    seeded["lora_id"],
                    seeded["user_id"],
                    db_factory=db_factory,
                    audio_dir=seeded["audio_dir"],
                    redis=MagicMock(),
                )
            )

    with db_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        assert lora.status == LoraStatus.FAILED
        assert get_job(session, "job-1").queue_reason is None


def test_path_traversal_in_adapter_dir_rejected(seeded, db_factory) -> None:
    malicious = "/etc/passwd"
    with _patch_worker_calls(malicious):
        _run(
            run_lora_training_job(
                {},
                "job-1",
                seeded["lora_id"],
                seeded["user_id"],
                db_factory=db_factory,
                audio_dir=seeded["audio_dir"],
                redis=MagicMock(),
            )
        )
    with db_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        assert lora.status == LoraStatus.FAILED
        assert lora.error is not None


def test_validate_export_path_accepts_inside_user_dir(tmp_path) -> None:
    user_dir = tmp_path / "audio" / USER_LORAS_DIRNAME / "u1" / "L1" / "training_tmp" / "final"
    user_dir.mkdir(parents=True)
    resolved = _validate_export_path(
        audio_dir=tmp_path / "audio",
        user_id="u1",
        reported=str(user_dir),
    )
    assert resolved == user_dir.resolve()


def test_validate_export_path_rejects_outside(tmp_path) -> None:
    with pytest.raises(ValueError):
        _validate_export_path(
            audio_dir=tmp_path / "audio",
            user_id="u1",
            reported="/etc/shadow",
        )
    with pytest.raises(ValueError):
        _validate_export_path(
            audio_dir=tmp_path / "audio",
            user_id="u1",
            reported=str(tmp_path / "audio" / USER_LORAS_DIRNAME / "u1"),
        )


def test_cleanup_failed_lora_removes_dirs(seeded, db_factory) -> None:
    audio_dir = seeded["audio_dir"]
    lora_root = audio_dir / USER_LORAS_DIRNAME / seeded["user_id"] / seeded["lora_id"]
    (lora_root / USER_LORA_DATASET_DIRNAME).mkdir(parents=True, exist_ok=True)
    (lora_root / USER_LORA_OUTPUT_DIRNAME).mkdir(parents=True, exist_ok=True)
    (lora_root / "training_tmp").mkdir(parents=True, exist_ok=True)
    (lora_root / USER_LORA_DATASET_DIRNAME / "stub.txt").write_text("x")

    cleanup_failed_lora_with_factory(
        lora_id=seeded["lora_id"],
        user_id=seeded["user_id"],
        audio_dir=audio_dir,
        db_factory=db_factory,
        error_message="testing",
    )
    assert not (lora_root / USER_LORA_DATASET_DIRNAME).exists()
    assert (lora_root / USER_LORA_OUTPUT_DIRNAME).exists()
    assert not (lora_root / "training_tmp").exists()

    with db_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        assert lora.status == LoraStatus.FAILED
        assert lora.error == "testing"
        audit = (
            session.query(AuditLog)
            .filter_by(
                resource_id=seeded["lora_id"],
            )
            .all()
        )
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
    seeded,
    db_factory,
    monkeypatch,
    crash_point: str,
    expected_adapter_file: str,
) -> None:
    from songmaker_cli.jobs import lora_training

    lora_root = seeded["audio_dir"] / USER_LORAS_DIRNAME / seeded["user_id"] / seeded["lora_id"]
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
        if (crash_point == "after_first_rename" and rename_count == 1) or (
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
            _run(
                run_lora_training_job(
                    {},
                    "job-1",
                    seeded["lora_id"],
                    seeded["user_id"],
                    db_factory=db_factory,
                    audio_dir=seeded["audio_dir"],
                    redis=MagicMock(),
                )
            )

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
    seeded,
    db_factory,
    monkeypatch,
    caplog,
) -> None:
    from songmaker_cli.jobs import lora_training

    lora_root = seeded["audio_dir"] / USER_LORAS_DIRNAME / seeded["user_id"] / seeded["lora_id"]
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
        _run(
            run_lora_training_job(
                {},
                "job-1",
                seeded["lora_id"],
                seeded["user_id"],
                db_factory=db_factory,
                audio_dir=seeded["audio_dir"],
                redis=MagicMock(),
            )
        )

    assert (final_dir / "adapter_config.json").exists()
    assert previous_dir.exists()
    assert "Failed to remove previous LoRA adapter" in caplog.text
    with db_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        assert lora.status == LoraStatus.READY


def test_adoption_restores_the_previous_adapter_when_second_rename_fails(
    seeded,
    db_factory,
    monkeypatch,
) -> None:
    from songmaker_cli.jobs import lora_training

    lora_root = seeded["audio_dir"] / USER_LORAS_DIRNAME / seeded["user_id"] / seeded["lora_id"]
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
        _run(
            run_lora_training_job(
                {},
                "job-1",
                seeded["lora_id"],
                seeded["user_id"],
                db_factory=db_factory,
                audio_dir=seeded["audio_dir"],
                redis=MagicMock(),
            )
        )

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

    _run(
        run_lora_training_job(
            {},
            "job-1",
            seeded["lora_id"],
            seeded["user_id"],
            db_factory=db_factory,
            audio_dir=seeded["audio_dir"],
            redis=MagicMock(),
        )
    )
    with db_factory() as session:
        job = get_job(session, "job-1")
        assert job.status == JobStatus.FAILED
        assert "deleted" in (job.error or "").lower()


def test_missing_lora_fails_job(seeded, db_factory) -> None:
    _run(
        run_lora_training_job(
            {},
            "job-1",
            "does-not-exist",
            seeded["user_id"],
            db_factory=db_factory,
            audio_dir=seeded["audio_dir"],
            redis=MagicMock(),
        )
    )
    with db_factory() as session:
        job = get_job(session, "job-1")
        assert job.status == JobStatus.FAILED


def test_no_capacity_marks_failed(seeded, db_factory) -> None:
    from songmaker_cli.scheduler import NoCapacityError

    with patch(
        "songmaker_cli.jobs.lora_training.pick_worker",
        AsyncMock(side_effect=NoCapacityError("no workers")),
    ):
        _run(
            run_lora_training_job(
                {},
                "job-1",
                seeded["lora_id"],
                seeded["user_id"],
                db_factory=db_factory,
                audio_dir=seeded["audio_dir"],
                redis=MagicMock(),
            )
        )
    with db_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        assert lora.status == LoraStatus.FAILED
        job = get_job(session, "job-1")
        assert job.status == JobStatus.FAILED


def test_held_lora_fails_after_the_queued_drain_threshold(seeded, db_factory) -> None:
    from datetime import datetime, timedelta, timezone

    from songmaker_cli.constants import STALE_JOB_THRESHOLDS
    from songmaker_cli.scheduler import AllWorkersHeld

    with db_factory() as session:
        job = get_job(session, "job-1")
        job.started_at = datetime.now(timezone.utc) - timedelta(
            seconds=STALE_JOB_THRESHOLDS[JobType.LORA_TRAINING].queued_seconds + 1,
        )
        session.commit()

    redis = MagicMock()
    redis.enqueue_job = AsyncMock()
    with patch(
        "songmaker_cli.jobs.lora_training._reserve_lora_worker",
        AsyncMock(side_effect=AllWorkersHeld("held")),
    ):
        _run(
            run_lora_training_job(
                {},
                "job-1",
                seeded["lora_id"],
                seeded["user_id"],
                db_factory=db_factory,
                audio_dir=seeded["audio_dir"],
                redis=redis,
            )
        )

    redis.enqueue_job.assert_not_awaited()
    with db_factory() as session:
        job = get_job(session, "job-1")
        assert job.status == JobStatus.FAILED
        assert job.error == "Generation queue did not drain before LoRA training could start"
        lora = get_user_lora(session, seeded["lora_id"])
        assert lora.status == LoraStatus.FAILED


def test_held_lora_defers_without_running_or_materializing_a_dataset(seeded, db_factory) -> None:
    from songmaker_cli.constants import ARQ_MUSIC_QUEUE_NAME, JobFunction
    from songmaker_cli.scheduler import AllWorkersHeld

    redis = MagicMock()
    redis.enqueue_job = AsyncMock()
    with patch(
        "songmaker_cli.jobs.lora_training._reserve_lora_worker",
        AsyncMock(side_effect=AllWorkersHeld("held")),
    ):
        _run(
            run_lora_training_job(
                {},
                "job-1",
                seeded["lora_id"],
                seeded["user_id"],
                db_factory=db_factory,
                audio_dir=seeded["audio_dir"],
                redis=redis,
            )
        )

    redis.enqueue_job.assert_awaited_once()
    args, kwargs = redis.enqueue_job.await_args
    assert args == (JobFunction.LORA_TRAINING, "job-1", seeded["lora_id"], seeded["user_id"])
    assert kwargs == {"_queue_name": ARQ_MUSIC_QUEUE_NAME, "_defer_by": 5}
    with db_factory() as session:
        job = get_job(session, "job-1")
        assert job.status == JobStatus.QUEUED
        assert job.queue_reason == "Waiting for queued generations on this GPU."
        assert get_user_lora(session, seeded["lora_id"]).status == LoraStatus.QUEUED
    dataset_dir = (
        seeded["audio_dir"]
        / USER_LORAS_DIRNAME
        / seeded["user_id"]
        / seeded["lora_id"]
        / USER_LORA_DATASET_DIRNAME
    )
    assert not dataset_dir.exists()


def test_queued_generation_in_the_database_defers_lora_before_running(seeded, db_factory) -> None:
    from songmaker_cli.constants import JobFunction

    with db_factory() as session:
        session.add(
            Job(
                id="generation-waiting",
                type=JobFunction.GENERATE,
                status=JobStatus.QUEUED,
            )
        )
        session.commit()

    redis = MagicMock()
    redis.enqueue_job = AsyncMock()
    materialize = MagicMock()
    with (
        patch(
            "songmaker_cli.jobs.lora_training.pick_worker",
            AsyncMock(return_value=_FakeWorker()),
        ),
        patch("songmaker_cli.jobs.lora_training._materialize_dataset", materialize),
    ):
        _run(
            run_lora_training_job(
                {}, "job-1", seeded["lora_id"], seeded["user_id"],
                db_factory=db_factory, audio_dir=seeded["audio_dir"], redis=redis,
            )
        )

    materialize.assert_not_called()
    redis.enqueue_job.assert_awaited_once()
    with db_factory() as session:
        job = get_job(session, "job-1")
        assert job.status == JobStatus.QUEUED
        assert job.queue_reason == "Waiting for queued generations on this GPU."
        assert get_user_lora(session, seeded["lora_id"]).status == LoraStatus.QUEUED


def test_lora_defer_passes_do_not_sleep_or_hold_an_arq_slot(seeded, db_factory) -> None:
    from songmaker_cli.scheduler import AllWorkersHeld

    async def exercise() -> None:
        redis = MagicMock()
        redis.enqueue_job = AsyncMock()
        materialize = MagicMock()
        with (
            patch(
                "songmaker_cli.jobs.lora_training._reserve_lora_worker",
                AsyncMock(side_effect=AllWorkersHeld("held")),
            ),
            patch("songmaker_cli.jobs.lora_training._materialize_dataset", materialize),
            patch(
                "songmaker_cli.jobs.lora_training.asyncio.sleep",
                AsyncMock(side_effect=AssertionError("defer must not sleep in its ARQ slot")),
            ),
        ):
            for _ in range(1100):
                await run_lora_training_job(
                    {}, "job-1", seeded["lora_id"], seeded["user_id"],
                    db_factory=db_factory, audio_dir=seeded["audio_dir"], redis=redis,
                )

        materialize.assert_not_called()
        assert redis.enqueue_job.await_count == 1100

    _run(exercise())


def test_renewal_failure_cancels_materialization_and_releases_the_hold(seeded, db_factory) -> None:
    materialization_started = asyncio.Event()
    materialization_cancelled = asyncio.Event()

    async def slow_materialization(*args, **kwargs):
        materialization_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            materialization_cancelled.set()

    async def failed_renewal(*args, **kwargs):
        await materialization_started.wait()
        raise RuntimeError("hold renewal failed")

    release = AsyncMock()
    with (
        patch(
            "songmaker_cli.jobs.lora_training._reserve_lora_worker",
            AsyncMock(return_value=(_FakeWorker(), "hold-token")),
        ),
        patch("songmaker_cli.jobs.lora_training._renew_lora_hold", failed_renewal),
        patch("songmaker_cli.jobs.lora_training.asyncio.to_thread", slow_materialization),
        patch("songmaker_cli.jobs.lora_training._release_lora_hold", release),
    ):
        _run(
            run_lora_training_job(
                {},
                "job-1",
                seeded["lora_id"],
                seeded["user_id"],
                db_factory=db_factory,
                audio_dir=seeded["audio_dir"],
                redis=MagicMock(),
            )
        )

    assert materialization_cancelled.is_set()
    release.assert_awaited_once()
    with db_factory() as session:
        assert get_job(session, "job-1").status == JobStatus.FAILED


def test_lora_renews_repeatedly_while_model_load_outlasts_the_hold_ttl() -> None:
    from songmaker_cli.jobs.lora_training import (
        _pick_and_call_worker,
        _renew_lora_hold,
        _WorkerHandle,
    )

    async def exercise() -> int:
        real_sleep = asyncio.sleep
        renewals = 0
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(return_value={"task_id": "task-1"})
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        async def post(url, **kwargs):
            nonlocal renewals

            if url.endswith("/gpu_hold/renew"):
                renewals += 1
                return response
            if url.endswith("/load_model"):
                while renewals < 4:
                    await asyncio.sleep(0)
                return response
            return response

        client.post = AsyncMock(side_effect=post)

        async def events(*args, **kwargs):
            yield ("done", {"result": {"mode": "sft", "adapter_dir": "/tmp/adapter"}})

        async def immediate_sleep(*args, **kwargs) -> None:
            await real_sleep(0)

        worker = _WorkerHandle(base_url="http://fake", id="w0")
        renew_task = asyncio.create_task(_renew_lora_hold(worker, "hold-token"))
        with (
            patch("httpx.AsyncClient", return_value=client),
            patch("songmaker_cli.jobs.lora_training._iterate_task_events", events),
            patch("songmaker_cli.jobs.lora_training.asyncio.sleep", immediate_sleep),
        ):
            await _pick_and_call_worker(
                target_mode="sft",
                request_payload={},
                worker=worker,
                hold_token="hold-token",
                renew_task=renew_task,
                on_progress=lambda _fraction, _current_epoch, _train_epochs, _started_at: None,
                on_heartbeat=lambda: None,
            )
        return renewals

    assert _run(exercise()) >= 4


def test_lora_worker_progress_requires_training_epochs() -> None:
    from songmaker_cli.jobs.lora_training import _pick_and_call_worker, _WorkerHandle
    from songmaker_cli.scheduler import WorkerProtocolError

    async def exercise() -> None:
        renew_task = asyncio.create_task(asyncio.Event().wait())
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {"task_id": "task-1"}
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.post = AsyncMock(return_value=response)

        async def events(*_args, **_kwargs):
            yield ("progress", {"progress": 0.5})

        with (
            patch("httpx.AsyncClient", return_value=client),
            patch("songmaker_cli.jobs.lora_training._iterate_task_events", events),
            pytest.raises(WorkerProtocolError, match="invalid training epoch fields"),
        ):
            await _pick_and_call_worker(
                target_mode="sft",
                request_payload={},
                worker=_WorkerHandle(base_url="http://fake", id="w0"),
                hold_token="hold-token",
                renew_task=renew_task,
                on_progress=lambda _fraction, _current_epoch, _train_epochs, _started_at: None,
                on_heartbeat=lambda: None,
            )

        assert renew_task.cancelled()

    _run(exercise())


def test_lora_starts_hold_renewal_before_marking_the_job_running(seeded, db_factory) -> None:
    renewal_started = asyncio.Event()

    async def renewal(*args, **kwargs) -> None:
        renewal_started.set()
        await asyncio.Event().wait()

    from songmaker_cli.jobs import lora_training

    update_job = lora_training._update_job

    def checked_update_job(*args, **kwargs) -> None:
        if kwargs.get("worker_pid") is not None:
            assert renewal_started.is_set()
        update_job(*args, **kwargs)

    with (
        patch(
            "songmaker_cli.jobs.lora_training._reserve_lora_worker",
            AsyncMock(return_value=(_FakeWorker(), "hold-token")),
        ),
        patch("songmaker_cli.jobs.lora_training._renew_lora_hold", renewal),
        patch("songmaker_cli.jobs.lora_training._update_job", checked_update_job),
        patch(
            "songmaker_cli.jobs.lora_training._materialize_dataset",
            side_effect=RuntimeError("dataset setup failed"),
        ),
        patch("songmaker_cli.jobs.lora_training._release_lora_hold", AsyncMock()),
    ):
        _run(
            run_lora_training_job(
                {},
                "job-1",
                seeded["lora_id"],
                seeded["user_id"],
                db_factory=db_factory,
                audio_dir=seeded["audio_dir"],
                redis=MagicMock(),
            )
        )


def test_running_update_failure_releases_the_new_lora_hold(seeded, db_factory) -> None:
    renew_task: asyncio.Task[None] | None = None

    async def start_renewal(*args, **kwargs) -> asyncio.Task[None]:
        nonlocal renew_task

        renew_task = asyncio.create_task(asyncio.Event().wait())
        return renew_task

    from songmaker_cli.jobs import lora_training

    update_job = lora_training._update_job

    def fail_first_running_update(*args, **kwargs) -> None:
        if kwargs.get("worker_pid") is not None:
            raise RuntimeError("running update failed")
        update_job(*args, **kwargs)

    release = AsyncMock()
    with (
        patch(
            "songmaker_cli.jobs.lora_training._reserve_lora_worker",
            AsyncMock(return_value=(_FakeWorker(), "hold-token")),
        ),
        patch("songmaker_cli.jobs.lora_training._start_lora_hold_renewal", start_renewal),
        patch("songmaker_cli.jobs.lora_training._update_job", fail_first_running_update),
        patch("songmaker_cli.jobs.lora_training._release_lora_hold", release),
    ):
        _run(
            run_lora_training_job(
                {},
                "job-1",
                seeded["lora_id"],
                seeded["user_id"],
                db_factory=db_factory,
                audio_dir=seeded["audio_dir"],
                redis=MagicMock(),
            )
        )

    release.assert_awaited_once()
    assert renew_task is not None and renew_task.cancelled()


def test_post_materialization_failure_releases_the_hold_and_stops_renewal(
    seeded, db_factory
) -> None:
    import fakeredis.aioredis

    from songmaker_cli.acestep_state import release_gpu_hold, reserve_gpu_hold

    async def exercise() -> None:
        from songmaker_cli.jobs.lora_training import update_user_lora

        redis = fakeredis.aioredis.FakeRedis()
        assert await reserve_gpu_hold(redis, "w0", "hold-token", 15)
        renew_task = asyncio.create_task(asyncio.Event().wait())

        async def start_renewal(*_args, **_kwargs) -> asyncio.Task[None]:
            return renew_task

        async def release_hold(*_args, **_kwargs) -> None:
            assert await release_gpu_hold(redis, "w0", "hold-token")

        def fail_preprocessing(session, *args, **kwargs) -> None:
            if kwargs.get("status") == LoraStatus.PREPROCESSING:
                raise RuntimeError("preprocessing update failed")
            update_user_lora(session, *args, **kwargs)

        with (
            patch(
                "songmaker_cli.jobs.lora_training._reserve_lora_worker",
                AsyncMock(return_value=(_FakeWorker(), "hold-token")),
            ),
            patch("songmaker_cli.jobs.lora_training._start_lora_hold_renewal", start_renewal),
            patch(
                "songmaker_cli.jobs.lora_training._materialize_dataset",
                return_value=seeded["audio_dir"],
            ),
            patch(
                "songmaker_cli.jobs.lora_training.update_user_lora",
                fail_preprocessing,
            ),
            patch("songmaker_cli.jobs.lora_training._release_lora_hold", release_hold),
        ):
            await run_lora_training_job(
                {},
                "job-1",
                seeded["lora_id"],
                seeded["user_id"],
                db_factory=db_factory,
                audio_dir=seeded["audio_dir"],
                redis=redis,
            )

        assert renew_task.cancelled()
        assert await reserve_gpu_hold(redis, "w0", "hold-token", 15)

    _run(exercise())


def test_post_materialization_cancellation_releases_the_hold_and_stops_renewal(
    seeded, db_factory
) -> None:
    import fakeredis.aioredis

    from songmaker_cli.acestep_state import release_gpu_hold, reserve_gpu_hold

    async def exercise() -> None:
        from songmaker_cli.jobs.lora_training import update_user_lora

        redis = fakeredis.aioredis.FakeRedis()
        assert await reserve_gpu_hold(redis, "w0", "hold-token", 15)
        renew_task = asyncio.create_task(asyncio.Event().wait())

        async def start_renewal(*_args, **_kwargs) -> asyncio.Task[None]:
            return renew_task

        async def release_hold(*_args, **_kwargs) -> None:
            assert await release_gpu_hold(redis, "w0", "hold-token")

        def cancel_preprocessing(session, *args, **kwargs) -> None:
            if kwargs.get("status") == LoraStatus.PREPROCESSING:
                raise asyncio.CancelledError()
            update_user_lora(session, *args, **kwargs)

        with (
            patch(
                "songmaker_cli.jobs.lora_training._reserve_lora_worker",
                AsyncMock(return_value=(_FakeWorker(), "hold-token")),
            ),
            patch("songmaker_cli.jobs.lora_training._start_lora_hold_renewal", start_renewal),
            patch(
                "songmaker_cli.jobs.lora_training._materialize_dataset",
                return_value=seeded["audio_dir"],
            ),
            patch("songmaker_cli.jobs.lora_training.update_user_lora", cancel_preprocessing),
            patch("songmaker_cli.jobs.lora_training._release_lora_hold", release_hold),
            pytest.raises(asyncio.CancelledError),
        ):
            await run_lora_training_job(
                {},
                "job-1",
                seeded["lora_id"],
                seeded["user_id"],
                db_factory=db_factory,
                audio_dir=seeded["audio_dir"],
                redis=redis,
            )

        assert renew_task.cancelled()
        assert await reserve_gpu_hold(redis, "w0", "hold-token", 15)

    _run(exercise())


def test_lora_releases_its_hold_when_running_cannot_be_applied(seeded, db_factory) -> None:
    renew_task: asyncio.Task[None] | None = None

    async def start_renewal(*args, **kwargs) -> asyncio.Task[None]:
        nonlocal renew_task

        renew_task = asyncio.create_task(asyncio.Event().wait())
        return renew_task

    from songmaker_cli.jobs import lora_training

    update_job = lora_training._update_job

    def refuse_running(*args, **kwargs) -> bool:
        if kwargs.get("worker_pid") is not None:
            return False
        return update_job(*args, **kwargs)

    release = AsyncMock()
    materialize = MagicMock()
    with (
        patch(
            "songmaker_cli.jobs.lora_training._reserve_lora_worker",
            AsyncMock(return_value=(_FakeWorker(), "hold-token")),
        ),
        patch("songmaker_cli.jobs.lora_training._start_lora_hold_renewal", start_renewal),
        patch("songmaker_cli.jobs.lora_training._update_job", refuse_running),
        patch("songmaker_cli.jobs.lora_training._release_lora_hold", release),
        patch("songmaker_cli.jobs.lora_training._materialize_dataset", materialize),
    ):
        _run(
            run_lora_training_job(
                {}, "job-1", seeded["lora_id"], seeded["user_id"],
                db_factory=db_factory, audio_dir=seeded["audio_dir"], redis=MagicMock(),
            )
        )

    release.assert_awaited_once()
    materialize.assert_not_called()
    assert renew_task is not None and renew_task.cancelled()


def test_cancel_before_handover_releases_the_job_hold() -> None:
    from songmaker_cli.jobs.lora_training import _pick_and_call_worker, _WorkerHandle

    async def exercise() -> AsyncMock:
        renew_task = asyncio.create_task(asyncio.Event().wait())
        release = AsyncMock()
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        with (
            patch(
                "songmaker_cli.jobs.lora_training._race_with_renewal",
                AsyncMock(side_effect=asyncio.CancelledError()),
            ),
            patch("songmaker_cli.jobs.lora_training._release_lora_hold", release),
            patch("httpx.AsyncClient", return_value=client),
            pytest.raises(asyncio.CancelledError),
        ):
            await _pick_and_call_worker(
                target_mode="sft",
                request_payload={},
                worker=_WorkerHandle(base_url="http://fake", id="w0"),
                hold_token="hold-token",
                renew_task=renew_task,
                on_progress=lambda _fraction, _current_epoch, _train_epochs, _started_at: None,
                on_heartbeat=lambda: None,
            )
        assert renew_task.cancelled()
        return release

    release = _run(exercise())
    release.assert_awaited_once()


def test_cancel_after_worker_handover_propagates_to_the_lora_job() -> None:
    from songmaker_cli.jobs.lora_training import _pick_and_call_worker, _WorkerHandle

    async def exercise() -> AsyncMock:
        renew_task = asyncio.create_task(asyncio.Event().wait())
        response = MagicMock()
        response.raise_for_status = MagicMock()

        def task_response() -> dict[str, str]:
            current_task = asyncio.current_task()
            assert current_task is not None
            current_task.cancel()
            return {"task_id": "task-1"}

        response.json.side_effect = task_response
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.post = AsyncMock(return_value=response)
        release = AsyncMock()

        with (
            patch("httpx.AsyncClient", return_value=client),
            patch("songmaker_cli.jobs.lora_training._release_lora_hold", release),
            pytest.raises(asyncio.CancelledError),
        ):
            await _pick_and_call_worker(
                target_mode="sft",
                request_payload={},
                worker=_WorkerHandle(base_url="http://fake", id="w0"),
                hold_token="hold-token",
                renew_task=renew_task,
                on_progress=lambda _fraction, _current_epoch, _train_epochs, _started_at: None,
                on_heartbeat=lambda: None,
            )
        assert renew_task.cancelled()
        return release

    release = _run(exercise())
    release.assert_not_awaited()


def test_lost_train_response_keeps_the_hold_for_the_worker(seeded, db_factory) -> None:
    import fakeredis.aioredis
    import httpx

    from songmaker_cli.acestep_state import admit_generation, reserve_gpu_hold
    from songmaker_cli.jobs.lora_training import _pick_and_call_worker, _WorkerHandle

    async def exercise() -> AsyncMock:
        redis = fakeredis.aioredis.FakeRedis()
        assert await reserve_gpu_hold(redis, "w0", "hold-token", 15)
        renew_task = asyncio.create_task(asyncio.Event().wait())
        response = MagicMock()
        response.raise_for_status = MagicMock()
        handover_response = MagicMock()
        handover_response.raise_for_status = MagicMock()
        handover_response.json.return_value = {"claimed": True, "task_id": "t-1"}
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        async def post(url, **kwargs):
            if url.endswith("/load_model"):
                return response
            if url.endswith("/gpu_hold/handover"):
                return handover_response
            raise httpx.ReadError("train request was accepted but its response was lost")

        client.post = AsyncMock(side_effect=post)

        async def release_hold(*args, **kwargs) -> None:
            from songmaker_cli.acestep_state import release_gpu_hold

            await release_gpu_hold(redis, "w0", "hold-token")

        release = AsyncMock(side_effect=release_hold)
        async def events(*_args, **_kwargs):
            yield ("done", {"result": {"mode": "sft", "adapter_dir": "/tmp/adapter"}})

        with (
            patch("httpx.AsyncClient", return_value=client),
            patch("songmaker_cli.jobs.lora_training._release_lora_hold", release),
            patch("songmaker_cli.jobs.lora_training._iterate_task_events", events),
        ):
            result = await _pick_and_call_worker(
                target_mode="sft",
                request_payload={},
                worker=_WorkerHandle(base_url="http://fake", id="w0"),
                hold_token="hold-token",
                renew_task=renew_task,
                on_progress=lambda _fraction, _current_epoch, _train_epochs, _started_at: None,
                on_heartbeat=lambda: None,
            )
        assert result.adapter_dir == "/tmp/adapter"
        assert not await admit_generation(redis, "w0")
        return release

    release = _run(exercise())
    release.assert_not_awaited()


def test_unknown_handover_probe_does_not_release_a_worker_owned_hold() -> None:
    import fakeredis.aioredis
    import httpx

    from songmaker_cli.acestep_state import (
        admit_generation,
        release_gpu_hold,
        renew_gpu_hold,
        reserve_gpu_hold,
    )
    from songmaker_cli.jobs.lora_training import _pick_and_call_worker, _WorkerHandle

    async def exercise() -> AsyncMock:
        redis = fakeredis.aioredis.FakeRedis()
        assert await reserve_gpu_hold(redis, "w0", "hold-token", 15)
        worker_renewed = asyncio.Event()

        async def worker_renewal() -> None:
            assert await renew_gpu_hold(redis, "w0", "hold-token", 15)
            worker_renewed.set()
            await asyncio.Event().wait()

        worker_renew_task = asyncio.create_task(worker_renewal())
        await worker_renewed.wait()
        job_renew_task = asyncio.create_task(asyncio.Event().wait())
        response = MagicMock()
        response.raise_for_status = MagicMock()
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        async def post(url, **_kwargs):
            if url.endswith("/load_model"):
                return response
            if url.endswith("/gpu_hold/handover"):
                raise httpx.ConnectError("handover probe unavailable")
            raise httpx.ReadError("train request response lost")

        client.post = AsyncMock(side_effect=post)
        async def release_hold(*_args, **_kwargs) -> None:
            assert await release_gpu_hold(redis, "w0", "hold-token")

        release = AsyncMock(side_effect=release_hold)
        with (
            patch("httpx.AsyncClient", return_value=client),
            patch("songmaker_cli.jobs.lora_training._release_lora_hold", release),
            pytest.raises(httpx.ReadError),
        ):
            await _pick_and_call_worker(
                target_mode="sft",
                request_payload={},
                worker=_WorkerHandle(base_url="http://fake", id="w0"),
                hold_token="hold-token",
                renew_task=job_renew_task,
                on_progress=lambda _fraction, _current_epoch, _train_epochs, _started_at: None,
                on_heartbeat=lambda: None,
            )
        assert job_renew_task.cancelled()
        assert not await admit_generation(redis, "w0")
        worker_renew_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker_renew_task
        assert await release_gpu_hold(redis, "w0", "hold-token")
        assert await admit_generation(redis, "w0")
        return release

    release = _run(exercise())
    release.assert_not_awaited()


@pytest.mark.parametrize("probe_outcome", ["invalid-json", "cancelled"])
def test_handover_probe_failures_do_not_release_the_hold(probe_outcome: str) -> None:
    import fakeredis.aioredis
    import httpx

    from songmaker_cli.acestep_state import admit_generation, release_gpu_hold, reserve_gpu_hold
    from songmaker_cli.jobs.lora_training import _pick_and_call_worker, _WorkerHandle

    async def exercise() -> AsyncMock:
        redis = fakeredis.aioredis.FakeRedis()
        assert await reserve_gpu_hold(redis, "w0", "hold-token", 15)
        renew_task = asyncio.create_task(asyncio.Event().wait())
        response = MagicMock()
        response.raise_for_status = MagicMock()
        handover_response = MagicMock()
        handover_response.raise_for_status = MagicMock()
        handover_response.json.side_effect = ValueError("not JSON")
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        async def post(url, **_kwargs):
            if url.endswith("/load_model"):
                return response
            if url.endswith("/gpu_hold/handover"):
                if probe_outcome == "cancelled":
                    raise asyncio.CancelledError()
                return handover_response
            raise httpx.ReadError("train request response lost")

        client.post = AsyncMock(side_effect=post)

        async def release_hold(*_args, **_kwargs) -> None:
            assert await release_gpu_hold(redis, "w0", "hold-token")

        release = AsyncMock(side_effect=release_hold)
        expected = asyncio.CancelledError if probe_outcome == "cancelled" else httpx.ReadError
        with (
            patch("httpx.AsyncClient", return_value=client),
            patch("songmaker_cli.jobs.lora_training._release_lora_hold", release),
            pytest.raises(expected),
        ):
            await _pick_and_call_worker(
                target_mode="sft",
                request_payload={},
                worker=_WorkerHandle(base_url="http://fake", id="w0"),
                hold_token="hold-token",
                renew_task=renew_task,
                on_progress=lambda _fraction, _current_epoch, _train_epochs, _started_at: None,
                on_heartbeat=lambda: None,
            )
        assert renew_task.cancelled()
        assert not await admit_generation(redis, "w0")
        return release

    release = _run(exercise())
    release.assert_not_awaited()


def test_successful_train_submit_wins_a_simultaneous_job_renewal_failure() -> None:
    from songmaker_cli.jobs.lora_training import _race_with_renewal

    async def successful_submit() -> str:
        return "task-1"

    async def failed_renewal() -> None:
        raise RuntimeError("renewal failed")

    async def exercise() -> str:
        renew_task = asyncio.create_task(failed_renewal())
        return await _race_with_renewal(successful_submit(), renew_task)

    assert _run(exercise()) == "task-1"


def test_lora_reserve_checks_queued_generations_after_selecting_the_worker(
    seeded,
    db_factory,
) -> None:
    from songmaker_cli.constants import JobFunction
    from songmaker_cli.db.models import Job
    from songmaker_cli.db.queries import count_queued_generation_jobs
    from songmaker_cli.jobs.lora_training import _reserve_lora_worker
    from songmaker_cli.scheduler import AllWorkersHeld

    with db_factory() as session:
        session.add(
            Job(
                id="generation-waiting",
                type=JobFunction.GENERATE,
                status=JobStatus.QUEUED,
            )
        )
        session.commit()

    picked = False

    async def pick(*args, **kwargs):
        nonlocal picked

        picked = True
        return _FakeWorker()

    def count(session):
        assert picked
        return count_queued_generation_jobs(session)

    with (
        patch("songmaker_cli.jobs.lora_training.pick_worker", pick),
        patch("songmaker_cli.jobs.lora_training.count_queued_generation_jobs", count),
        pytest.raises(AllWorkersHeld),
    ):
        _run(
            _reserve_lora_worker(
                target_mode="sft",
                redis=MagicMock(),
                db_factory=db_factory,
            )
        )


def test_run_without_factory_raises(db_factory, tmp_path) -> None:
    with pytest.raises(RuntimeError):
        _run(run_lora_training_job({}, "j", "l", "u"))

"""Tests for lifecycle.reconcile_crashed_loras — detect + cleanup on startup."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import TEST_SECRET, make_fake_redis

from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import (
    USER_LORA_DATASET_DIRNAME,
    USER_LORAS_DIRNAME,
    JobStatus,
    JobType,
    LoraStatus,
)
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import AuditLog, Job, User, UserLora
from songmaker_cli.db.queries import get_user_lora
from songmaker_cli.lifecycle import reconcile_crashed_loras
from songmaker_cli.settings import get_settings


@pytest.fixture()
def ctx(tmp_path: Path) -> AppContext:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    factory = init_test_db(tmp_path / "songmaker.db")
    return AppContext(
        db=factory, audio_dir=audio_dir, data_dir=tmp_path / "data",
        session_secret=TEST_SECRET, redis=make_fake_redis(),
    )


def _create_stuck_lora(
    ctx: AppContext, *,
    lora_id: str, status: LoraStatus,
    job_status: str | None,
) -> None:
    with ctx.db() as session:
        if session.query(User).filter_by(id="u1").first() is None:
            session.add(User(id="u1", username="u1", password_hash="x"))
        job_id = None
        if job_status is not None:
            session.add(
                Job(id=f"job-{lora_id}", type=JobType.LORA_TRAINING, status=job_status),
            )
            job_id = f"job-{lora_id}"
        session.add(
            UserLora(
                id=lora_id, user_id="u1", name=lora_id, slug=lora_id,
                status=status, training_job_id=job_id,
            ),
        )
        session.commit()
    root = ctx.audio_dir / USER_LORAS_DIRNAME / "u1" / lora_id
    (root / USER_LORA_DATASET_DIRNAME).mkdir(parents=True, exist_ok=True)
    (root / USER_LORA_DATASET_DIRNAME / "x.wav").write_text("x")


def test_reconciles_when_job_terminal(ctx) -> None:
    _create_stuck_lora(
        ctx, lora_id="L1", status=LoraStatus.TRAINING,
        job_status=JobStatus.FAILED,
    )
    n = reconcile_crashed_loras(ctx)
    assert n == 1
    with ctx.db() as s:
        lora = get_user_lora(s, "L1", include_deleted_rows=True)
        assert lora.status == LoraStatus.FAILED


def test_reconciliation_is_idempotent_and_records_one_audit(ctx) -> None:
    _create_stuck_lora(
        ctx, lora_id="L-lock", status=LoraStatus.TRAINING,
        job_status=JobStatus.FAILED,
    )

    assert reconcile_crashed_loras(ctx) == 1
    assert reconcile_crashed_loras(ctx) == 0

    with ctx.db() as session:
        audits = session.query(AuditLog).filter_by(resource_id="L-lock").all()
    assert len(audits) == 1


def test_reconciliation_continues_after_one_lora_database_failure(ctx, monkeypatch) -> None:
    _create_stuck_lora(
        ctx, lora_id="L-error", status=LoraStatus.TRAINING,
        job_status=JobStatus.FAILED,
    )
    _create_stuck_lora(
        ctx, lora_id="L-next", status=LoraStatus.TRAINING,
        job_status=JobStatus.FAILED,
    )

    from songmaker_cli.jobs import lora_training

    original_cleanup = lora_training.cleanup_failed_lora

    def fail_one_lora(**kwargs) -> None:
        if kwargs["lora_id"] == "L-error":
            raise RuntimeError("database unavailable")
        original_cleanup(**kwargs)

    monkeypatch.setattr(lora_training, "cleanup_failed_lora", fail_one_lora)

    assert reconcile_crashed_loras(ctx) == 1
    with ctx.db() as session:
        failed = get_user_lora(session, "L-next", include_deleted_rows=True)
        retryable = get_user_lora(session, "L-error", include_deleted_rows=True)
    assert failed.status == LoraStatus.FAILED
    assert retryable.status == LoraStatus.TRAINING


def test_reconciliation_commits_before_disk_cleanup_failure_and_continues(
    ctx, monkeypatch,
) -> None:
    _create_stuck_lora(
        ctx, lora_id="L-first", status=LoraStatus.TRAINING,
        job_status=JobStatus.FAILED,
    )
    _create_stuck_lora(
        ctx, lora_id="L-second", status=LoraStatus.TRAINING,
        job_status=JobStatus.FAILED,
    )

    from songmaker_cli.jobs import lora_training

    first_dataset = (
        ctx.audio_dir / USER_LORAS_DIRNAME / "u1" / "L-first" / USER_LORA_DATASET_DIRNAME
    )
    original_rmtree = lora_training.shutil.rmtree
    committed_before_cleanup: list[tuple[str, int]] = []
    audit_calls: list[tuple[object, Path]] = []

    def fail_first_dataset(path, *args, **kwargs) -> None:
        if Path(path) == first_dataset:
            with ctx.db() as session:
                lora = get_user_lora(session, "L-first", include_deleted_rows=True)
                audits = session.query(AuditLog).filter_by(resource_id="L-first").count()
            committed_before_cleanup.append((lora.status, audits))
            raise OSError("disk unavailable")
        original_rmtree(path, *args, **kwargs)

    original_audit = lora_training.audit_orphaned_lora_work_dirs

    def record_orphan_audit(db_factory, audio_dir: Path) -> None:
        audit_calls.append((db_factory, audio_dir))
        original_audit(db_factory, audio_dir)

    monkeypatch.setattr(lora_training.shutil, "rmtree", fail_first_dataset)
    monkeypatch.setattr(lora_training, "audit_orphaned_lora_work_dirs", record_orphan_audit)

    assert reconcile_crashed_loras(ctx) == 2
    assert committed_before_cleanup == [(LoraStatus.FAILED, 1)]
    assert audit_calls == [(ctx.db, ctx.audio_dir)]
    with ctx.db() as session:
        first = get_user_lora(session, "L-first", include_deleted_rows=True)
        second = get_user_lora(session, "L-second", include_deleted_rows=True)
        first_audits = session.query(AuditLog).filter_by(resource_id="L-first").count()
        second_audits = session.query(AuditLog).filter_by(resource_id="L-second").count()
    assert first.status == LoraStatus.FAILED
    assert second.status == LoraStatus.FAILED
    assert first_audits == 1
    assert second_audits == 1


def test_reconciles_when_job_missing(ctx) -> None:
    _create_stuck_lora(
        ctx, lora_id="L2", status=LoraStatus.PREPROCESSING, job_status=None,
    )
    n = reconcile_crashed_loras(ctx)
    assert n == 1
    with ctx.db() as s:
        assert get_user_lora(s, "L2", include_deleted_rows=True).status == LoraStatus.FAILED


def test_leaves_active_job_alone(ctx) -> None:
    _create_stuck_lora(
        ctx, lora_id="L3", status=LoraStatus.TRAINING,
        job_status=JobStatus.RUNNING,
    )
    n = reconcile_crashed_loras(ctx)
    assert n == 0
    with ctx.db() as s:
        assert get_user_lora(s, "L3").status == LoraStatus.TRAINING


def test_reconciles_exporting_state(ctx) -> None:
    _create_stuck_lora(
        ctx, lora_id="L4", status=LoraStatus.EXPORTING,
        job_status=JobStatus.COMPLETED,
    )
    n = reconcile_crashed_loras(ctx)
    assert n == 1


def test_reconciliation_removes_dataset_dir(ctx) -> None:
    _create_stuck_lora(
        ctx, lora_id="L5", status=LoraStatus.PREPROCESSING, job_status=None,
    )
    root = ctx.audio_dir / USER_LORAS_DIRNAME / "u1" / "L5"
    assert (root / USER_LORA_DATASET_DIRNAME).exists()
    reconcile_crashed_loras(ctx)
    assert not (root / USER_LORA_DATASET_DIRNAME).exists()


def test_no_stuck_loras_returns_zero(ctx) -> None:
    assert reconcile_crashed_loras(ctx) == 0


def test_reconciles_when_worker_process_died_without_terminal_izing_the_job(
    ctx,
) -> None:
    """Before #371: a dead MusicWorker process never terminal-izes the
    LORA_TRAINING job it was running (WorkerBase's recovery is scoped to
    GENERATE only), so this row stayed TRAINING forever — the job it waits
    on was never going to change. reconcile_crashed_loras must now reap the
    job itself instead of waiting on it.
    """
    stale = datetime.now(timezone.utc) - timedelta(
        seconds=get_settings().stale_job_threshold_seconds + 60,
    )
    with ctx.db() as session:
        session.add(User(id="u1", username="u1", password_hash="x"))
        session.add(
            Job(
                id="job-L6", type=JobType.LORA_TRAINING, status=JobStatus.RUNNING,
                started_at=stale, heartbeat_at=stale,
            ),
        )
        session.add(
            UserLora(
                id="L6", user_id="u1", name="L6", slug="L6",
                status=LoraStatus.TRAINING, training_job_id="job-L6",
            ),
        )
        session.commit()

    n = reconcile_crashed_loras(ctx)

    assert n == 1
    with ctx.db() as s:
        assert get_user_lora(s, "L6", include_deleted_rows=True).status == LoraStatus.FAILED
        job = s.query(Job).filter_by(id="job-L6").first()
        assert job.status == JobStatus.FAILED

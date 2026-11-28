"""A training whose job row ended while its trainer ran writes nothing to its voice."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from support.job_owner import an_owner
from support.lora_training_world import fail_the_adapter_move_into_place, patch_worker_calls
from tandem import Liveness

from songmaker_cli.audio_paths import USER_LORAS_DIRNAME
from songmaker_cli.constants import (
    MODEL_DEFAULT_MODE,
    USER_LORA_DATASET_DIRNAME,
    USER_LORA_OUTPUT_DIRNAME,
    USER_LORA_TRAINING_TMP_DIRNAME,
    LoraStatus,
)
from songmaker_cli.db.models import AuditLog
from songmaker_cli.db.queries.jobs import get_job, recover_jobs_of_dead_owners
from songmaker_cli.db.queries.loras import get_user_lora
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.jobs import lora_training
from songmaker_cli.jobs.lora_training import reconcile_crashed_loras, run_lora_training_job
from songmaker_cli.settings import get_settings
from songmaker_cli.worker_liveness import JobOwnerStamp


def _fail_the_job_through_the_owner_pass(pg_factory, seeded) -> tuple:
    """What a web process does once the lease generation of ``an_owner("o1")`` is gone.

    Returns the voice and its audits as the owner pass leaves them.
    """
    with pg_factory() as session:
        stamp = JobOwnerStamp("o1", an_owner("o1").generation)
        assert recover_jobs_of_dead_owners(session, {stamp: Liveness.GONE}) == {
            JobType.LORA_TRAINING: 1,
        }
        session.commit()
    assert reconcile_crashed_loras(pg_factory, seeded["audio_dir"]) == 1
    with pg_factory() as session:
        return _voice_and_audits(session, seeded["lora_id"])


def _voice_and_audits(session, lora_id: str) -> tuple:
    lora = get_user_lora(session, lora_id)
    audits = [audit.detail for audit in session.query(AuditLog).filter_by(resource_id=lora_id)]
    return lora.status, lora.error_message, audits


def _a_training_run(seeded, pg_factory, target_mode: str = "turbo"):
    return run_lora_training_job(
        "job-1", seeded["lora_id"], seeded["user_id"],
        db_factory=pg_factory, audio_dir=seeded["audio_dir"], redis=MagicMock(),
        target_mode=target_mode, owner=an_owner("o1"),
        training_config=get_settings().lora_training_config,
    )


@pytest.mark.parametrize(
    ("has_previous_adapter", "status_the_owner_pass_leaves"),
    [(False, LoraStatus.FAILED), (True, LoraStatus.READY)],
    ids=["first-training", "retrain"],
)
@pytest.mark.parametrize(
    "trainer_ending",
    [
        "recreates-its-output",
        "recreates-its-output-with-another-mode",
        "reports-an-error",
        "cancelled",
    ],
)
def test_a_training_whose_job_ended_while_it_ran_lands_nothing(
    seeded, pg_factory, tmp_path, has_previous_adapter, status_the_owner_pass_leaves,
    trainer_ending,
) -> None:
    lora_root = seeded["audio_dir"] / USER_LORAS_DIRNAME / seeded["user_id"] / seeded["lora_id"]
    final_dir = lora_root / USER_LORA_OUTPUT_DIRNAME
    temporary_dir = lora_root / USER_LORA_TRAINING_TMP_DIRNAME
    if has_previous_adapter:
        final_dir.mkdir()
        (final_dir / "previous-adapter.txt").write_text("previous")

    left_by_the_owner_pass = None

    async def trainer_that_outlives_its_job(*_args, **_kwargs):
        nonlocal left_by_the_owner_pass
        left_by_the_owner_pass = _fail_the_job_through_the_owner_pass(pg_factory, seeded)
        if trainer_ending == "reports-an-error":
            yield ("error", {"error": "trainer lost its output"})
            return
        if trainer_ending == "cancelled":
            raise asyncio.CancelledError
        mode = "sft" if trainer_ending == "recreates-its-output-with-another-mode" else "turbo"
        yield ("done", {"result": {"mode": mode, "adapter_dir": "", "num_samples": 3}})

    recreates_its_output = trainer_ending.startswith("recreates-its-output")
    trainer_output = temporary_dir if recreates_its_output else tmp_path / "stand-in"
    training = _a_training_run(seeded, pg_factory)
    with patch_worker_calls(str(trainer_output), events=trainer_that_outlives_its_job):
        if trainer_ending == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(training)
        else:
            asyncio.run(training)

    with pg_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        assert lora.status == status_the_owner_pass_leaves
        assert lora.model_mode == MODEL_DEFAULT_MODE
        assert get_job(session, "job-1").status == JobStatus.FAILED
        assert _voice_and_audits(session, seeded["lora_id"]) == left_by_the_owner_pass
    assert not temporary_dir.exists()
    assert not (lora_root / USER_LORA_DATASET_DIRNAME).exists()
    assert final_dir.exists() == has_previous_adapter
    if has_previous_adapter:
        assert (final_dir / "previous-adapter.txt").read_text() == "previous"
        assert list(final_dir.iterdir()) == [final_dir / "previous-adapter.txt"]


def test_a_failed_adapter_replacement_marks_nothing_once_the_row_ended(
    seeded, pg_factory, monkeypatch,
) -> None:
    lora_root = seeded["audio_dir"] / USER_LORAS_DIRNAME / seeded["user_id"] / seeded["lora_id"]
    final_dir = lora_root / USER_LORA_OUTPUT_DIRNAME
    final_dir.mkdir()
    (final_dir / "previous-adapter.txt").write_text("previous")
    left_by_the_owner_pass = None
    original_rmtree = lora_training.shutil.rmtree
    move = fail_the_adapter_move_into_place(monkeypatch)
    owner_pass_pending = True

    def end_the_row_once_the_adapter_is_restored(path, *args, **kwargs) -> None:
        nonlocal owner_pass_pending, left_by_the_owner_pass
        if owner_pass_pending and move.renames_done >= 3:
            owner_pass_pending = False
            left_by_the_owner_pass = _fail_the_job_through_the_owner_pass(pg_factory, seeded)
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(lora_training.shutil, "rmtree", end_the_row_once_the_adapter_is_restored)
    with patch_worker_calls(str(lora_root / USER_LORA_TRAINING_TMP_DIRNAME)):
        asyncio.run(_a_training_run(seeded, pg_factory, target_mode="sft"))

    with pg_factory() as session:
        assert get_job(session, "job-1").status == JobStatus.FAILED
        assert _voice_and_audits(session, seeded["lora_id"]) == left_by_the_owner_pass


def test_a_training_whose_row_ended_while_its_dataset_was_built_marks_nothing(
    seeded, pg_factory, monkeypatch,
) -> None:
    left_by_the_owner_pass = None
    original_symlink = lora_training.os.symlink

    def end_the_row_while_the_dataset_is_built(source, destination, *args, **kwargs) -> None:
        nonlocal left_by_the_owner_pass
        if left_by_the_owner_pass is None:
            left_by_the_owner_pass = _fail_the_job_through_the_owner_pass(pg_factory, seeded)
            Path(destination).parent.mkdir(exist_ok=True)
        original_symlink(source, destination, *args, **kwargs)

    monkeypatch.setattr(lora_training.os, "symlink", end_the_row_while_the_dataset_is_built)
    with patch_worker_calls("unused"):
        asyncio.run(_a_training_run(seeded, pg_factory))

    with pg_factory() as session:
        assert get_job(session, "job-1").status == JobStatus.FAILED
        assert _voice_and_audits(session, seeded["lora_id"]) == left_by_the_owner_pass
    assert left_by_the_owner_pass[0] == LoraStatus.FAILED


@pytest.mark.parametrize("row_ends", [True, False], ids=["row-ended", "row-active"])
def test_a_progress_tier_reaches_the_voice_only_while_the_row_is_active(
    seeded, pg_factory, row_ends,
) -> None:
    left_by_the_owner_pass = None
    voice_after_each_tier = []

    async def trainer_that_reports_its_tiers(*_args, **_kwargs):
        nonlocal left_by_the_owner_pass
        if row_ends:
            left_by_the_owner_pass = _fail_the_job_through_the_owner_pass(pg_factory, seeded)
        for epoch, fraction in ((1, 0.25), (2, 0.95)):
            yield ("progress", {"progress": fraction, "current_epoch": epoch, "train_epochs": 3})
            with pg_factory() as session:
                voice_after_each_tier.append(_voice_and_audits(session, seeded["lora_id"]))
        yield ("error", {"error": "trainer lost its output"})

    with patch_worker_calls("unused", events=trainer_that_reports_its_tiers):
        asyncio.run(_a_training_run(seeded, pg_factory))

    if row_ends:
        assert voice_after_each_tier == [left_by_the_owner_pass] * 2
    else:
        assert [status for status, *_ in voice_after_each_tier] == [
            LoraStatus.TRAINING, LoraStatus.EXPORTING,
        ]

"""A training whose job row ended while its trainer ran lands nothing."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from support.job_owner import an_owner
from support.lora_training_world import patch_worker_calls, seed_queued_lora
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
from songmaker_cli.jobs.lora_training import reconcile_crashed_loras, run_lora_training_job
from songmaker_cli.settings import get_settings
from songmaker_cli.worker_liveness import JobOwnerStamp


@pytest.fixture
def seeded(pg_factory, tmp_path: Path) -> dict:
    return seed_queued_lora(pg_factory, tmp_path)


def _fail_the_job_through_the_owner_pass(pg_factory, audio_dir: Path) -> None:
    """What a web process does once the lease generation of ``an_owner("o1")`` is gone."""
    with pg_factory() as session:
        stamp = JobOwnerStamp("o1", an_owner("o1").generation)
        assert recover_jobs_of_dead_owners(session, {stamp: Liveness.GONE}) == {
            JobType.LORA_TRAINING: 1,
        }
        session.commit()
    assert reconcile_crashed_loras(pg_factory, audio_dir) == 1


def _voice_and_audits(session, lora_id: str) -> tuple:
    lora = get_user_lora(session, lora_id)
    audits = [audit.detail for audit in session.query(AuditLog).filter_by(resource_id=lora_id)]
    return lora.status, lora.error_message, audits


@pytest.mark.parametrize(
    ("has_previous_adapter", "status_the_owner_pass_leaves"),
    [(False, LoraStatus.FAILED), (True, LoraStatus.READY)],
    ids=["first-training", "retrain"],
)
@pytest.mark.parametrize(
    "trainer_ending",
    ["recreates-its-output", "finds-its-output-removed", "reports-an-error"],
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

    left_by_the_owner_pass = {}

    async def trainer_that_outlives_its_job(*_args, **_kwargs):
        _fail_the_job_through_the_owner_pass(pg_factory, seeded["audio_dir"])
        with pg_factory() as session:
            left_by_the_owner_pass.update(
                voice=_voice_and_audits(session, seeded["lora_id"]),
            )
        if trainer_ending == "reports-an-error":
            yield ("error", {"error": "trainer lost its output"})
            return
        reported = str(temporary_dir) if trainer_ending == "finds-its-output-removed" else ""
        yield ("done", {"result": {"mode": "turbo", "adapter_dir": reported, "num_samples": 3}})

    stand_in_output = tmp_path / "stand-in"
    trainer_output = temporary_dir if trainer_ending == "recreates-its-output" else stand_in_output
    with patch_worker_calls(str(trainer_output), events=trainer_that_outlives_its_job):
        asyncio.run(
            run_lora_training_job(
                "job-1", seeded["lora_id"], seeded["user_id"],
                db_factory=pg_factory, audio_dir=seeded["audio_dir"], redis=MagicMock(),
                target_mode="turbo", owner=an_owner("o1"),
                training_config=get_settings().lora_training_config,
            )
        )

    with pg_factory() as session:
        lora = get_user_lora(session, seeded["lora_id"])
        assert lora.status == status_the_owner_pass_leaves
        assert lora.model_mode == MODEL_DEFAULT_MODE
        assert get_job(session, "job-1").status == JobStatus.FAILED
        assert _voice_and_audits(session, seeded["lora_id"]) == left_by_the_owner_pass["voice"]
    assert not temporary_dir.exists()
    assert not (lora_root / USER_LORA_DATASET_DIRNAME).exists()
    assert final_dir.exists() == has_previous_adapter
    if has_previous_adapter:
        assert (final_dir / "previous-adapter.txt").read_text() == "previous"
        assert list(final_dir.iterdir()) == [final_dir / "previous-adapter.txt"]

"""Startup orphan audit and failed-cleanup audit of LoRA training work directories."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
from support.lora_training_world import seed_queued_lora

from songmaker_cli.constants import (
    USER_LORA_DATASET_DIRNAME,
    USER_LORAS_DIRNAME,
)
from songmaker_cli.jobs.lora_training import (
    cleanup_failed_lora_with_factory,
    log_orphaned_lora_work_dirs,
)

ORPHAN_WARNING = "orphaned LoRA work dir"


@pytest.fixture
def seeded(pg_factory, tmp_path: Path) -> dict:
    return seed_queued_lora(pg_factory, tmp_path)


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def test_orphan_audit_is_silent_without_a_loras_root(pg_factory, tmp_path, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        log_orphaned_lora_work_dirs(pg_factory, tmp_path)

    assert _warnings(caplog) == []


def test_orphan_audit_is_silent_when_every_work_dir_belongs_to_an_active_lora(
    seeded, pg_factory, caplog,
) -> None:
    lora_root = seeded["audio_dir"] / USER_LORAS_DIRNAME / seeded["user_id"] / seeded["lora_id"]
    (lora_root / USER_LORA_DATASET_DIRNAME).mkdir()

    with caplog.at_level(logging.WARNING):
        log_orphaned_lora_work_dirs(pg_factory, seeded["audio_dir"])

    assert _warnings(caplog) == []


def test_orphan_audit_names_work_dirs_of_missing_loras_and_skips_loose_files(
    seeded, pg_factory, caplog,
) -> None:
    loras_root = seeded["audio_dir"] / USER_LORAS_DIRNAME
    (loras_root / "stray.txt").write_text("x")
    orphan_dataset = loras_root / seeded["user_id"] / "gone-lora" / USER_LORA_DATASET_DIRNAME
    orphan_dataset.mkdir(parents=True)

    with caplog.at_level(logging.WARNING):
        log_orphaned_lora_work_dirs(pg_factory, seeded["audio_dir"])

    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert ORPHAN_WARNING in warnings[0]
    assert str(orphan_dataset) in warnings[0]


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_failed_cleanup_audits_the_work_dirs_it_could_not_remove(
    seeded, pg_factory, caplog,
) -> None:
    lora_root = seeded["audio_dir"] / USER_LORAS_DIRNAME / seeded["user_id"] / seeded["lora_id"]
    dataset_dir = lora_root / USER_LORA_DATASET_DIRNAME
    dataset_dir.mkdir()
    (dataset_dir / "stub.txt").write_text("x")
    dataset_dir.chmod(0o500)
    try:
        with caplog.at_level(logging.WARNING):
            cleanup_failed_lora_with_factory(
                lora_id=seeded["lora_id"],
                user_id=seeded["user_id"],
                audio_dir=seeded["audio_dir"],
                db_factory=pg_factory,
                error_message="testing",
            )
    finally:
        dataset_dir.chmod(0o700)

    assert any(ORPHAN_WARNING in m and str(dataset_dir) in m for m in _warnings(caplog))

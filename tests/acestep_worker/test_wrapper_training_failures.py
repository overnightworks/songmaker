"""Failure and edge paths of the ACE-Step worker's LoRA training runner and hold reservation."""

from __future__ import annotations

import asyncio
import shutil
import threading
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from support.wrapper_deps import INTERNAL_HEADERS

from acestep_engine.training_client import (
    ExportResult,
    PreprocessStatus,
    PreprocessTaskHandle,
    ScanDatasetResult,
    TrainingStartedHandle,
    TrainingStatus,
)
from acestep_worker.models import TrainLoraRequest
from acestep_worker.task_store import TaskSnapshot, TaskStore
from acestep_worker.wrapper import create_app, default_train_lora_runner

_CLIENT = "acestep_engine.training_client.AceStepTrainingClient"
_WORKSPACE_PARENT = Path("safe-root") / "training"


def _request(
    tmp_path: Path, train_body: Callable[..., dict[str, object]]
) -> TrainLoraRequest:
    dataset_dir = tmp_path / "source"
    dataset_dir.mkdir(exist_ok=True)
    return TrainLoraRequest(
        mode="sft",
        dataset_dir=str(dataset_dir),
        output_dir=str(tmp_path / "out"),
        hold_token="test-token",
        **train_body(train_epochs=1, poll_interval_seconds=0.001),
    )


def _export_final_adapter(source: str, destination: str) -> ExportResult:
    final_dir = Path(source) / "final"
    final_dir.mkdir(parents=True)
    (final_dir / "lokr_weights.safetensors").write_bytes(b"weights")
    shutil.copytree(final_dir, destination)
    return ExportResult(export_path=destination, source=str(final_dir))


@contextmanager
def _training_fork(**overrides: Any) -> Iterator[None]:
    """Patch the training child's client; `overrides` replace one method's behaviour."""
    behaviour: dict[str, Any] = {
        "initialize_model": lambda mode: None,
        "scan_dataset": lambda path: ScanDatasetResult(num_samples=3),
        "start_preprocess": lambda path: PreprocessTaskHandle(task_id="pre", total=2),
        "poll_preprocess": lambda task_id: PreprocessStatus(
            task_id="pre", status="completed", current=2, total=2
        ),
        "start_lokr": lambda config: TrainingStartedHandle(tensor_dir="t", output_dir="o"),
        "poll_training": lambda: TrainingStatus(is_training=False, current_epoch=1),
        "export_training": _export_final_adapter,
        "stop_training": lambda: None,
        **overrides,
    }
    with ExitStack() as stack:
        for method, side_effect in behaviour.items():
            stack.enter_context(patch(f"{_CLIENT}.{method}", side_effect=side_effect))
        yield


def _run_runner(
    tmp_path: Path, train_body: Callable[..., dict[str, object]], **overrides: Any
) -> tuple[TaskSnapshot, Path]:
    async def scenario() -> tuple[TaskSnapshot, Path]:
        task_store = TaskStore()
        task_id = await task_store.create("train_lora", train_epochs=1)
        with _training_fork(**overrides):
            await default_train_lora_runner(
                task_store,
                task_id,
                request=_request(tmp_path, train_body),
                port=8001,
                checkpoint_dir=tmp_path / "safe-root",
                training_workspace_dirname="training",
            )
        snapshot = await task_store.get(task_id)
        assert snapshot is not None
        return snapshot, tmp_path / _WORKSPACE_PARENT / task_id

    return asyncio.run(scenario())


def _failing(message: str) -> Callable[..., Any]:
    def fail(*_args: Any) -> Any:
        raise RuntimeError(message)

    return fail


def test_a_held_worker_refuses_a_second_reservation(tmp_path: Path, train_lora_deps) -> None:
    app = create_app(train_lora_deps(tmp_path))
    with TestClient(app) as client:
        first = client.post("/gpu_hold/reserve", headers=INTERNAL_HEADERS)
        second = client.post("/gpu_hold/reserve", headers=INTERNAL_HEADERS)

    assert first.status_code == 200
    assert second.status_code == 409


def test_a_preprocess_poll_without_a_total_does_not_fail_the_training(
    tmp_path: Path, train_body
) -> None:
    polls = iter(
        [
            PreprocessStatus(task_id="pre", status="running"),
            PreprocessStatus(task_id="pre", status="completed", current=2, total=2),
        ]
    )

    snapshot, workspace = _run_runner(
        tmp_path, train_body, poll_preprocess=lambda task_id: next(polls)
    )

    assert snapshot.state == "done"
    assert not workspace.exists()


def test_a_training_error_from_the_fork_fails_the_task_and_removes_the_workspace(
    tmp_path: Path,
    train_body,
) -> None:
    snapshot, workspace = _run_runner(
        tmp_path,
        train_body,
        poll_training=lambda: TrainingStatus(is_training=False, error="out of memory"),
    )

    assert snapshot.state == "error"
    assert "Training failed: out of memory" in (snapshot.error or "")
    assert not workspace.exists()


@pytest.mark.parametrize(
    ("export", "expected_error"),
    [
        pytest.param(
            lambda source, destination: ExportResult(export_path=destination, source="/elsewhere"),
            "unexpected source",
            id="source",
        ),
        pytest.param(
            lambda source, destination: ExportResult(
                export_path="/elsewhere", source=str(Path(source) / "final")
            ),
            "unexpected path",
            id="path",
        ),
        pytest.param(
            lambda source, destination: ExportResult(
                export_path=destination, source=str(Path(source) / "final")
            ),
            "export is missing",
            id="directory",
        ),
    ],
)
def test_an_export_that_breaks_the_forks_contract_fails_the_task(
    tmp_path: Path,
    train_body,
    export: Callable[[str, str], ExportResult],
    expected_error: str,
) -> None:
    snapshot, workspace = _run_runner(tmp_path, train_body, export_training=export)

    assert snapshot.state == "error"
    assert expected_error in (snapshot.error or "")
    assert not (tmp_path / "out").exists()
    assert not workspace.exists()


def test_a_failed_training_still_ends_when_the_child_cannot_be_stopped(
    tmp_path: Path, train_body
) -> None:
    snapshot, workspace = _run_runner(
        tmp_path,
        train_body,
        poll_training=lambda: TrainingStatus(is_training=False, error="boom"),
        stop_training=_failing("child is gone"),
    )

    assert snapshot.state == "error"
    assert "Training failed: boom" in (snapshot.error or "")
    assert not workspace.exists()


def test_a_cancelled_training_still_ends_when_the_child_cannot_be_stopped(
    tmp_path: Path, train_body
) -> None:
    training_polled = threading.Event()

    def keep_training() -> TrainingStatus:
        training_polled.set()
        return TrainingStatus(is_training=True, current_epoch=0)

    async def scenario() -> tuple[TaskSnapshot, Path]:
        task_store = TaskStore()
        task_id = await task_store.create("train_lora", train_epochs=1)
        with _training_fork(poll_training=keep_training, stop_training=_failing("child is gone")):
            runner = asyncio.create_task(
                default_train_lora_runner(
                    task_store,
                    task_id,
                    request=_request(tmp_path, train_body),
                    port=8001,
                    checkpoint_dir=tmp_path / "safe-root",
                    training_workspace_dirname="training",
                )
            )
            await asyncio.to_thread(training_polled.wait)
            runner.cancel()
            with pytest.raises(asyncio.CancelledError):
                await runner
        snapshot = await task_store.get(task_id)
        assert snapshot is not None
        return snapshot, tmp_path / _WORKSPACE_PARENT / task_id

    snapshot, workspace = asyncio.run(scenario())

    assert snapshot.state == "error"
    assert snapshot.error == "cancelled"
    assert not workspace.exists()


@pytest.mark.parametrize(
    ("removal_error", "is_reported"),
    [(FileNotFoundError("no workspace"), False), (PermissionError("tree is busy"), True)],
    ids=["missing", "busy"],
)
def test_a_workspace_that_cannot_be_removed_does_not_hide_the_failed_task(
    tmp_path: Path,
    train_body,
    caplog: pytest.LogCaptureFixture,
    removal_error: OSError,
    is_reported: bool,
) -> None:
    real_rmtree = shutil.rmtree

    def rmtree(path: Path, **kwargs: Any) -> None:
        if kwargs.get("ignore_errors"):
            real_rmtree(path, **kwargs)
            return
        raise removal_error

    with patch("acestep_worker.wrapper.shutil.rmtree", side_effect=rmtree):
        snapshot, _ = _run_runner(
            tmp_path,
            train_body,
            scan_dataset=lambda path: ScanDatasetResult(num_samples=0),
        )

    assert snapshot.state == "error"
    assert ("Failed to remove LoRA training workspace" in caplog.text) is is_reported

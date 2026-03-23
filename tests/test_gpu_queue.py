"""Tests for the GPU job queue."""

from __future__ import annotations

import threading
import time

from songmaker_cli.gpu_queue import GpuQueue


def test_queue_executes_jobs_sequentially() -> None:
    queue = GpuQueue()
    queue.start()
    results: list[str] = []
    lock = threading.Lock()

    def job(name: str) -> None:
        with lock:
            results.append(f"start:{name}")
        time.sleep(0.05)
        with lock:
            results.append(f"end:{name}")

    queue.submit("j1", "generate", job, args=("a",))
    queue.submit("j2", "generate", job, args=("b",))
    queue.submit("j3", "score", job, args=("c",))

    time.sleep(0.5)
    queue.shutdown()

    assert results == [
        "start:a", "end:a",
        "start:b", "end:b",
        "start:c", "end:c",
    ]


def test_queue_mode_switch_calls_clear() -> None:
    queue = GpuQueue()
    queue.start()
    cleared: list[str] = []

    original_clear = queue._clear_models

    def mock_clear(mode: str) -> None:
        cleared.append(mode)
        original_clear(mode)

    queue._clear_models = mock_clear  # type: ignore[method-assign]

    def noop() -> None:
        pass

    queue.submit("j1", "generate", noop)
    queue.submit("j2", "score", noop)
    queue.submit("j3", "generate", noop)

    time.sleep(0.3)
    queue.shutdown()

    assert cleared == ["generate", "score"]


def test_queue_handles_job_exception() -> None:
    queue = GpuQueue()
    queue.start()
    results: list[str] = []

    def failing_job() -> None:
        raise RuntimeError("boom")

    def ok_job() -> None:
        results.append("ok")

    queue.submit("j1", "generate", failing_job)
    queue.submit("j2", "generate", ok_job)

    time.sleep(0.3)
    queue.shutdown()

    assert results == ["ok"]


def test_queue_shutdown() -> None:
    queue = GpuQueue()
    queue.start()
    queue.shutdown()
    assert not queue._running

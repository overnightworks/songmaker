"""Tests for the GPU job queue."""

from __future__ import annotations

import signal
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from songmaker_cli.gpu_queue import (
    SHUTDOWN_TIMEOUT_SECONDS,
    GpuJob,
    GpuQueue,
)


def _make_queue() -> GpuQueue:
    """Create a queue with _prepare_mode stubbed out (no real GPU ops)."""
    queue = GpuQueue(MagicMock())
    queue._prepare_mode = lambda mode: None  # type: ignore[method-assign]
    return queue


def test_queue_executes_jobs_sequentially() -> None:
    queue = _make_queue()
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


def test_queue_mode_switch_calls_prepare() -> None:
    queue = GpuQueue(MagicMock())
    queue.start()
    prepared: list[str] = []

    queue._prepare_mode = lambda mode: prepared.append(mode)  # type: ignore[method-assign]

    def noop() -> None:
        pass

    queue.submit("j1", "generate", noop)
    queue.submit("j2", "score", noop)
    queue.submit("j3", "generate", noop)

    time.sleep(0.3)
    queue.shutdown()

    assert prepared == ["generate", "score", "generate"]


def test_queue_handles_job_exception() -> None:
    queue = _make_queue()
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
    queue = _make_queue()
    queue.start()
    queue.shutdown()
    assert not queue._running


def test_queue_start_idempotent() -> None:
    queue = _make_queue()
    queue.start()
    worker1 = queue._worker
    queue.start()
    assert queue._worker is worker1
    queue.shutdown()


# ── _clear_scoring_models ───────────────────────────────────────────


def test_clear_scoring_models_calls_clear_cache() -> None:
    queue = GpuQueue(MagicMock())
    with (
        patch("songmaker_cli.scoring.text_accuracy.clear_cache") as mock_whisper,
        patch("songmaker_cli.scoring.audiobox_aesthetics.clear_cache") as mock_audiobox,
        patch.object(queue, "_gc_gpu"),
    ):
        queue._clear_scoring_models()

    mock_whisper.assert_called_once()
    mock_audiobox.assert_called_once()


def test_clear_scoring_models_handles_import_error() -> None:
    queue = GpuQueue(MagicMock())
    with (
        patch(
            "songmaker_cli.gpu_queue.GpuQueue._clear_scoring_models",
            wraps=queue._clear_scoring_models,
        ),
        patch.object(queue, "_gc_gpu"),
    ):
        queue._clear_scoring_models()


# ── _verify_vram_freed ──────────────────────────────────────────────


def test_verify_vram_freed_no_torch() -> None:
    queue = GpuQueue(MagicMock())
    with patch.dict("sys.modules", {"torch": None}):
        queue._verify_vram_freed()


def test_verify_vram_freed_no_cuda() -> None:
    queue = GpuQueue(MagicMock())
    mock_torch = MagicMock()
    mock_torch.cuda.is_available.return_value = False
    with patch.dict("sys.modules", {"torch": mock_torch}):
        queue._verify_vram_freed()


def test_verify_vram_freed_immediate() -> None:
    queue = GpuQueue(MagicMock())
    mock_torch = MagicMock()
    mock_torch.cuda.is_available.return_value = True
    mock_torch.cuda.memory_allocated.return_value = 10 * 1024 * 1024  # 10 MB
    with patch.dict("sys.modules", {"torch": mock_torch}):
        queue._verify_vram_freed(max_wait=1)


def test_verify_vram_freed_timeout() -> None:
    queue = GpuQueue(MagicMock())
    mock_torch = MagicMock()
    mock_torch.cuda.is_available.return_value = True
    mock_torch.cuda.memory_allocated.return_value = 500 * 1024 * 1024  # 500 MB
    with (
        patch.dict("sys.modules", {"torch": mock_torch}),
        patch("time.sleep"),
    ):
        queue._verify_vram_freed(max_wait=2)


# ── ACE-Step lifecycle ──────────────────────────────────────────────


def test_ensure_acestep_already_healthy() -> None:
    queue = GpuQueue(MagicMock())
    with patch.object(queue, "_is_acestep_healthy", return_value=True):
        queue._ensure_acestep()


def test_ensure_acestep_starts_and_waits() -> None:
    queue = GpuQueue(MagicMock())
    with (
        patch.object(queue, "_is_acestep_healthy", return_value=False),
        patch.object(queue, "_start_acestep"),
        patch.object(queue, "_wait_for_acestep"),
    ):
        queue._ensure_acestep()


def test_is_acestep_healthy_success() -> None:
    queue = GpuQueue(MagicMock())
    mock_response = MagicMock()
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    with patch("songmaker_cli.gpu_queue.urlopen", return_value=mock_response):
        assert queue._is_acestep_healthy() is True


def test_is_acestep_healthy_failure() -> None:
    queue = GpuQueue(MagicMock())
    with patch("songmaker_cli.gpu_queue.urlopen", side_effect=ConnectionError):
        assert queue._is_acestep_healthy() is False


def test_start_acestep() -> None:
    queue = GpuQueue(MagicMock())
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    with (
        patch.object(queue, "_find_uv", return_value=["uv"]),
        patch("subprocess.Popen", return_value=mock_proc),
    ):
        queue._start_acestep()
    assert queue._acestep_process is mock_proc


def test_start_acestep_no_uv() -> None:
    queue = GpuQueue(MagicMock())
    with patch.object(queue, "_find_uv", return_value=None):
        with pytest.raises(RuntimeError, match="uv not found"):
            queue._start_acestep()


def test_wait_for_acestep_success() -> None:
    queue = GpuQueue(MagicMock())
    queue._acestep_process = MagicMock()
    queue._acestep_process.poll.return_value = None

    calls = [False, True]
    with (
        patch.object(queue, "_is_acestep_healthy", side_effect=calls),
        patch("time.sleep"),
    ):
        queue._wait_for_acestep()


def test_wait_for_acestep_process_exits() -> None:
    queue = GpuQueue(MagicMock())
    stderr_mock = MagicMock()
    stderr_mock.read.return_value = b"fatal error"
    queue._acestep_process = MagicMock()
    queue._acestep_process.poll.return_value = 1
    queue._acestep_process.stderr = stderr_mock

    with (
        patch.object(queue, "_is_acestep_healthy", return_value=False),
        patch("time.sleep"),
    ):
        with pytest.raises(RuntimeError, match="ACE-Step server exited"):
            queue._wait_for_acestep()


def test_wait_for_acestep_timeout() -> None:
    queue = GpuQueue(MagicMock())
    queue._acestep_process = MagicMock()
    queue._acestep_process.poll.return_value = None

    with (
        patch.object(queue, "_is_acestep_healthy", return_value=False),
        patch("time.sleep"),
        patch("time.time", side_effect=[0, 0, 999]),
    ):
        with pytest.raises(RuntimeError, match="did not start"):
            queue._wait_for_acestep()


# ── _stop_acestep ───────────────────────────────────────────────────


def test_stop_acestep_no_process() -> None:
    queue = GpuQueue(MagicMock())
    queue._acestep_process = None
    queue._stop_acestep()


def test_stop_acestep_already_exited() -> None:
    queue = GpuQueue(MagicMock())
    proc = MagicMock()
    proc.poll.return_value = 0
    queue._acestep_process = proc
    queue._stop_acestep()
    assert queue._acestep_process is None


def test_stop_acestep_graceful() -> None:
    queue = GpuQueue(MagicMock())
    proc = MagicMock()
    proc.poll.return_value = None
    proc.wait.return_value = 0
    queue._acestep_process = proc

    with patch.object(queue, "_gc_gpu"):
        queue._stop_acestep()

    proc.send_signal.assert_called_once_with(signal.SIGTERM)
    assert queue._acestep_process is None


def test_stop_acestep_force_kill() -> None:
    import subprocess

    queue = GpuQueue(MagicMock())
    proc = MagicMock()
    proc.poll.return_value = None
    proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="acestep", timeout=15), None]
    queue._acestep_process = proc

    with patch.object(queue, "_gc_gpu"):
        queue._stop_acestep()

    proc.kill.assert_called_once()
    assert queue._acestep_process is None


# ── _find_uv ────────────────────────────────────────────────────────


def test_find_uv_found() -> None:
    queue = GpuQueue(MagicMock())
    with patch("subprocess.run"):
        result = queue._find_uv()
    assert result is not None


def test_find_uv_not_found() -> None:
    queue = GpuQueue(MagicMock())
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = queue._find_uv()
    assert result is None


# ── _gc_gpu ─────────────────────────────────────────────────────────


def test_gc_gpu_with_cuda() -> None:
    queue = GpuQueue(MagicMock())
    mock_torch = MagicMock()
    mock_torch.cuda.is_available.return_value = True
    with patch.dict("sys.modules", {"torch": mock_torch}):
        queue._gc_gpu()
    mock_torch.cuda.empty_cache.assert_called_once()


def test_gc_gpu_no_torch() -> None:
    queue = GpuQueue(MagicMock())
    with patch.dict("sys.modules", {"torch": None}):
        queue._gc_gpu()


# ── _prepare_mode ───────────────────────────────────────────────────


def test_prepare_mode_generate() -> None:
    queue = GpuQueue(MagicMock())
    with (
        patch.object(queue, "_clear_scoring_models"),
        patch.object(queue, "_verify_vram_freed"),
        patch.object(queue, "_ensure_acestep"),
    ):
        queue._prepare_mode("generate")


def test_prepare_mode_score() -> None:
    queue = GpuQueue(MagicMock())
    with (
        patch.object(queue, "_stop_acestep"),
        patch.object(queue, "_gc_gpu"),
        patch.object(queue, "_verify_vram_freed"),
    ):
        queue._prepare_mode("score")


def test_prepare_mode_exception_propagates() -> None:
    queue = GpuQueue(MagicMock())
    with patch.object(queue, "_stop_acestep", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            queue._prepare_mode("score")


def test_execute_skips_job_on_mode_failure() -> None:
    queue = GpuQueue(MagicMock())
    results: list[str] = []

    with (
        patch.object(queue, "_prepare_mode", side_effect=RuntimeError("gpu fail")),
        patch.object(queue, "_fail_job") as mock_fail,
    ):
        queue._execute(GpuJob(job_id="j1", job_type="generate", fn=lambda: results.append("ran")))

    assert results == []
    assert queue._current_mode is None
    mock_fail.assert_called_once_with("j1", "GPU mode preparation failed")


# ── _recover_stale_jobs ─────────────────────────────────────────────


def test_recover_stale_jobs_success() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)
    queue = GpuQueue(mock_factory)

    with (
        patch("songmaker_cli.db.queries.recover_stale_jobs"),
        patch("songmaker_cli.db.queries.delete_expired_sessions", return_value=3),
    ):
        queue._recover_stale_jobs()

    mock_session.commit.assert_called_once()


def test_recover_stale_jobs_no_expired_sessions() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)
    queue = GpuQueue(mock_factory)

    with (
        patch("songmaker_cli.db.queries.recover_stale_jobs"),
        patch("songmaker_cli.db.queries.delete_expired_sessions", return_value=0),
    ):
        queue._recover_stale_jobs()

    mock_session.commit.assert_called_once()


def test_recover_stale_jobs_ignores_runtime_error() -> None:
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(
        side_effect=RuntimeError("DB not initialized"),
    )
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)
    queue = GpuQueue(mock_factory)
    queue._recover_stale_jobs()


# ── _clear_scoring_models import errors ─────────────────────────────


def test_clear_scoring_models_whisper_import_error() -> None:
    queue = GpuQueue(MagicMock())
    with (
        patch.dict("sys.modules", {"songmaker_cli.scoring.text_accuracy": None}),
        patch.object(queue, "_gc_gpu"),
    ):
        queue._clear_scoring_models()


def test_clear_scoring_models_audiobox_import_error() -> None:
    queue = GpuQueue(MagicMock())

    def raise_on_clear_whisper():
        raise ImportError

    with (
        patch(
            "songmaker_cli.scoring.text_accuracy.clear_cache",
            side_effect=ImportError,
        ),
        patch.dict("sys.modules", {"songmaker_cli.scoring.audiobox_aesthetics": None}),
        patch.object(queue, "_gc_gpu"),
    ):
        queue._clear_scoring_models()


# ── _fail_job ──────────────────────────────────────────────────────


def test_fail_job_updates_db() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock(
        return_value=MagicMock(
            __enter__=MagicMock(return_value=mock_session),
            __exit__=MagicMock(return_value=False),
        ),
    )
    queue = GpuQueue(mock_factory)

    with patch("songmaker_cli.db.queries.update_job_status") as mock_update:
        queue._fail_job("j1", "something broke")

    mock_update.assert_called_once_with(
        mock_session, "j1", "failed", error="something broke", error_type="gpu_error",
    )
    mock_session.commit.assert_called_once()


def test_fail_job_handles_db_error() -> None:
    mock_factory = MagicMock(
        return_value=MagicMock(
            __enter__=MagicMock(side_effect=RuntimeError("no db")),
            __exit__=MagicMock(return_value=False),
        ),
    )
    queue = GpuQueue(mock_factory)
    queue._fail_job("j1", "error")


# ── _periodic_cleanup ──────────────────────────────────────────────


def test_periodic_cleanup_runs_recovery() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock(
        return_value=MagicMock(
            __enter__=MagicMock(return_value=mock_session),
            __exit__=MagicMock(return_value=False),
        ),
    )
    queue = GpuQueue(mock_factory)
    queue._running = True
    cleanup_called = threading.Event()

    with (
        patch("songmaker_cli.gpu_queue.CLEANUP_INTERVAL_SECONDS", 1),
        patch("songmaker_cli.db.queries.recover_stale_jobs_by_age") as mock_recover,
    ):
        mock_recover.side_effect = lambda s: cleanup_called.set() or 0

        t = threading.Thread(target=queue._periodic_cleanup, daemon=True)
        t.start()
        cleanup_called.wait(timeout=5)
        queue._running = False
        t.join(timeout=3)

    mock_recover.assert_called()
    mock_session.commit.assert_called()


def test_periodic_cleanup_stops_when_not_running() -> None:
    queue = GpuQueue(MagicMock())
    queue._running = False

    with patch("songmaker_cli.gpu_queue.CLEANUP_INTERVAL_SECONDS", 1):
        queue._periodic_cleanup()


def test_periodic_cleanup_handles_exception() -> None:
    mock_factory = MagicMock(
        return_value=MagicMock(
            __enter__=MagicMock(side_effect=RuntimeError("no db")),
            __exit__=MagicMock(return_value=False),
        ),
    )
    queue = GpuQueue(mock_factory)
    queue._running = True

    with patch("songmaker_cli.gpu_queue.CLEANUP_INTERVAL_SECONDS", 1):
        t = threading.Thread(target=queue._periodic_cleanup, daemon=True)
        t.start()
        time.sleep(2)
        queue._running = False
        t.join(timeout=3)


# ── shutdown timeout ───────────────────────────────────────────────


def test_shutdown_default_timeout() -> None:
    assert SHUTDOWN_TIMEOUT_SECONDS == 120


def test_shutdown_joins_cleanup_thread() -> None:
    queue = _make_queue()
    queue.start()
    time.sleep(0.1)
    mock_cleanup = MagicMock()
    queue._cleanup_thread = mock_cleanup
    queue.shutdown(timeout=1)
    mock_cleanup.join.assert_called_once_with(timeout=5)


# ── start with cleanup thread ─────────────────────────────────────


def test_start_creates_cleanup_thread() -> None:
    queue = _make_queue()
    with patch("songmaker_cli.gpu_queue.CLEANUP_INTERVAL_SECONDS", 900):
        queue.start()
    assert queue._cleanup_thread is not None
    assert queue._cleanup_thread.name == "job-cleanup"
    queue.shutdown(timeout=1)


def test_start_skips_cleanup_when_disabled() -> None:
    queue = _make_queue()
    with patch("songmaker_cli.gpu_queue.CLEANUP_INTERVAL_SECONDS", 0):
        queue.start()
    assert queue._cleanup_thread is None
    queue.shutdown(timeout=1)

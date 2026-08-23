"""Tests for the scorer subprocess runner."""

from __future__ import annotations

import multiprocessing
import os
import signal
from pathlib import Path

import pytest

from songmaker_cli.constants import SECRET_ENV_KEYS
from songmaker_cli.scoring.models import SongScores
from songmaker_cli.scoring.subprocess_runner import (
    EnvProbeRequest,
    EnvProbeResponse,
    ReleaseGpuRequest,
    ReleaseGpuResponse,
    ScoreRequest,
    ScoreResponse,
    ScorerProcess,
    ShutdownRequest,
    _child_main,
    get_scorer_process,
    set_scorer_process,
)

_ctx = multiprocessing.get_context("spawn")


# ── Message pickling ─────────────────────────────────────────────


def test_score_request_pickles() -> None:
    import pickle

    from songmaker_cli.parser import SongMeta
    from songmaker_cli.scoring.pipeline import PipelineConfig

    req = ScoreRequest(
        mp3_path=Path("/tmp/test.mp3"),
        meta=SongMeta(title="Test"),
        scorers=["silence"],
        config=PipelineConfig(device="cpu"),
        job_id="j1",
    )
    restored = pickle.loads(pickle.dumps(req))
    assert restored.mp3_path == req.mp3_path
    assert restored.job_id == "j1"


def test_score_response_pickles() -> None:
    import pickle

    resp = ScoreResponse(scores=SongScores(), error=None)
    restored = pickle.loads(pickle.dumps(resp))
    assert restored.scores is not None
    assert restored.error is None


def test_error_response_pickles() -> None:
    import pickle

    resp = ScoreResponse(scores=None, error="boom")
    restored = pickle.loads(pickle.dumps(resp))
    assert restored.error == "boom"


# ── Child main loop ──────────────────────────────────────────────


def _run_child_with_messages(messages: list, timeout: float = 10.0) -> list:
    parent_conn, child_conn = _ctx.Pipe()
    proc = _ctx.Process(target=_child_main, args=(child_conn,))
    proc.start()
    child_conn.close()

    responses = []
    for msg in messages:
        parent_conn.send(msg)
        if isinstance(msg, ShutdownRequest):
            break
        while parent_conn.poll(timeout=timeout):
            resp = parent_conn.recv()
            responses.append(resp)
            if isinstance(resp, (ScoreResponse, ReleaseGpuResponse, EnvProbeResponse)):
                break

    proc.join(timeout=5)
    parent_conn.close()
    return responses


def test_child_handles_shutdown() -> None:
    parent_conn, child_conn = _ctx.Pipe()
    proc = _ctx.Process(target=_child_main, args=(child_conn,))
    proc.start()
    child_conn.close()

    parent_conn.send(ShutdownRequest())
    proc.join(timeout=10)
    assert not proc.is_alive()
    parent_conn.close()


def test_child_handles_release_gpu() -> None:
    responses = _run_child_with_messages([
        ReleaseGpuRequest(),
        ShutdownRequest(),
    ])
    assert len(responses) == 1
    assert isinstance(responses[0], ReleaseGpuResponse)
    assert responses[0].success is True


def test_child_handles_score_request(tmp_path: Path) -> None:
    from songmaker_cli.scoring.pipeline import PipelineConfig

    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"fake")

    responses = _run_child_with_messages([
        ScoreRequest(
            mp3_path=mp3,
            meta=None,
            scorers=[],
            config=PipelineConfig(device="cpu"),
        ),
        ShutdownRequest(),
    ])
    assert len(responses) == 1
    resp = responses[0]
    assert isinstance(resp, ScoreResponse)
    assert resp.scores is not None
    assert resp.error is None


def test_child_handles_score_error(tmp_path: Path) -> None:
    from songmaker_cli.scoring.pipeline import PipelineConfig

    missing = tmp_path / "nonexistent.mp3"

    responses = _run_child_with_messages([
        ScoreRequest(
            mp3_path=missing,
            meta=None,
            scorers=["text_accuracy"],
            config=PipelineConfig(device="cpu"),
        ),
        ShutdownRequest(),
    ])
    score_responses = [r for r in responses if isinstance(r, ScoreResponse)]
    assert len(score_responses) == 1
    resp = score_responses[0]
    assert resp.error is not None or (
        resp.scores is not None and resp.scores.text_accuracy is None
    )


# ── Secret env scrubbing ─────────────────────────────────────────

_TEST_MARKER_KEY = "SONGMAKER_TEST_NON_SECRET_MARKER"


def test_scorer_child_drops_secret_env_keys_at_spawn() -> None:
    """The scorer child inherits the full parent env at spawn (multiprocessing
    has no env= parameter), so _child_main must scrub secrets itself, first
    thing. Drives the real _child_main (via _run_child_with_messages) rather
    than a test-only stand-in, so deleting the scrub call site fails this.
    """
    probed_keys = (*SECRET_ENV_KEYS, _TEST_MARKER_KEY)
    previous = {key: os.environ.get(key) for key in probed_keys}
    for key in SECRET_ENV_KEYS:
        os.environ[key] = "leaked-secret-value"
    os.environ[_TEST_MARKER_KEY] = "visible-non-secret"
    try:
        responses = _run_child_with_messages([
            EnvProbeRequest(keys=probed_keys),
            ShutdownRequest(),
        ])
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    probe_responses = [r for r in responses if isinstance(r, EnvProbeResponse)]
    assert len(probe_responses) == 1
    present = probe_responses[0].present
    for key in SECRET_ENV_KEYS:
        assert key not in present, f"{key} leaked into the scorer child's environment"
    assert _TEST_MARKER_KEY in present


# ── ScorerProcess class ──────────────────────────────────────────


def test_scorer_process_starts_and_shuts_down() -> None:
    sp = ScorerProcess()
    assert not sp.alive
    sp._ensure_started()
    assert sp.alive
    sp.shutdown()
    assert not sp.alive


def test_scorer_process_score_empty_scorers(tmp_path: Path) -> None:
    from songmaker_cli.scoring.pipeline import PipelineConfig

    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"fake")

    sp = ScorerProcess()
    try:
        result = sp.score(
            mp3, scorers=[], config=PipelineConfig(device="cpu"),
        )
        assert isinstance(result, SongScores)
    finally:
        sp.shutdown()


def test_scorer_process_release_gpu() -> None:
    sp = ScorerProcess()
    sp._ensure_started()
    try:
        sp.release_gpu(timeout=10)
    finally:
        sp.shutdown()


def test_scorer_process_release_gpu_noop_when_dead() -> None:
    sp = ScorerProcess()
    sp.release_gpu()


def _slow_child_main(conn):
    import time
    while True:
        try:
            conn.recv()
        except EOFError:
            break
        time.sleep(60)


def test_scorer_process_timeout_kills_child(tmp_path: Path) -> None:
    from songmaker_cli.scoring.pipeline import PipelineConfig

    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"fake")

    sp = ScorerProcess()
    parent_conn, child_conn = _ctx.Pipe()
    sp._process = _ctx.Process(target=_slow_child_main, args=(child_conn,), daemon=True)
    sp._process.start()
    child_conn.close()
    sp._conn = parent_conn
    pid = sp._process.pid

    with pytest.raises(TimeoutError):
        sp.score(
            mp3, scorers=[],
            config=PipelineConfig(device="cpu", pipeline_timeout=1),
        )

    assert not sp.alive
    try:
        os.kill(pid, 0)
        pytest.fail("Child process should not exist")
    except OSError:
        pass


def test_scorer_process_restarts_after_kill(tmp_path: Path) -> None:
    from songmaker_cli.scoring.pipeline import PipelineConfig

    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"fake")

    sp = ScorerProcess()
    sp._ensure_started()
    old_pid = sp._process.pid

    sp._kill()
    assert not sp.alive

    result = sp.score(
        mp3, scorers=[], config=PipelineConfig(device="cpu"),
    )
    assert isinstance(result, SongScores)
    assert sp.alive
    assert sp._process.pid != old_pid
    sp.shutdown()


def test_scorer_process_handles_child_crash(tmp_path: Path) -> None:
    from songmaker_cli.scoring.pipeline import PipelineConfig

    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"fake")

    sp = ScorerProcess()
    sp._ensure_started()
    os.kill(sp._process.pid, signal.SIGKILL)
    sp._process.join(timeout=5)

    result = sp.score(
        mp3, scorers=[], config=PipelineConfig(device="cpu"),
    )
    assert isinstance(result, SongScores)
    sp.shutdown()


# ── Module-level accessor ────────────────────────────────────────


def test_concurrent_score_calls_are_serialized(tmp_path: Path) -> None:
    """Two threads calling .score() concurrently must both succeed.

    The Pipe is not thread-safe; without the per-instance lock the two
    sends/receives would interleave and corrupt at least one response.
    """
    import threading

    from songmaker_cli.scoring.pipeline import PipelineConfig

    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"fake")

    sp = ScorerProcess()
    results: list[SongScores | Exception] = []
    results_lock = threading.Lock()

    def worker() -> None:
        try:
            r = sp.score(mp3, scorers=[], config=PipelineConfig(device="cpu"))
            with results_lock:
                results.append(r)
        except Exception as exc:  # noqa: BLE001
            with results_lock:
                results.append(exc)

    try:
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
            assert not t.is_alive(), "scorer thread hung"
        assert len(results) == 2
        for r in results:
            assert isinstance(r, SongScores), f"got {type(r).__name__}: {r}"
    finally:
        sp.shutdown()


def test_get_scorer_process_raises_when_unset() -> None:
    original = None
    import songmaker_cli.scoring.subprocess_runner as mod
    original = mod._scorer_process
    mod._scorer_process = None
    try:
        with pytest.raises(RuntimeError, match="not initialized"):
            get_scorer_process()
    finally:
        mod._scorer_process = original


def test_set_and_get_scorer_process() -> None:
    import songmaker_cli.scoring.subprocess_runner as mod
    original = mod._scorer_process
    try:
        sp = ScorerProcess()
        set_scorer_process(sp)
        assert get_scorer_process() is sp
    finally:
        mod._scorer_process = original

"""Tests for the scorer subprocess runner."""

from __future__ import annotations

import multiprocessing
import os
import signal
from pathlib import Path

import pytest

from songmaker_cli.scoring.models import SongScores
from songmaker_cli.scoring.subprocess_runner import (
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
        if parent_conn.poll(timeout=timeout):
            responses.append(parent_conn.recv())

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
    assert len(responses) == 1
    resp = responses[0]
    assert isinstance(resp, ScoreResponse)
    assert resp.error is not None or (
        resp.scores is not None and resp.scores.text_accuracy is None
    )


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

"""Tests for the scorer subprocess runner."""

from __future__ import annotations

import multiprocessing
import os
import signal
from pathlib import Path
from unittest.mock import patch

import pytest

from songmaker_cli.constants import SECRET_ENV_KEYS
from songmaker_cli.scoring.models import ScorerOutcome, ScorerRun, SongScores
from songmaker_cli.scoring.subprocess_runner import (
    EnvProbeRequest,
    EnvProbeResponse,
    ScoreProgressUpdate,
    ScoreRequest,
    ScoreResponse,
    ScorerProcess,
    ShutdownRequest,
    _child_main,
    get_scorer_process,
    set_scorer_process,
)

_ctx = multiprocessing.get_context("spawn")


class _FakeConnection:
    def __init__(
        self,
        *,
        incoming: list[object] | None = None,
        send_error: BaseException | None = None,
    ) -> None:
        self._incoming = list(incoming or [])
        self._send_error = send_error
        self.sent: list[object] = []
        self.closed = False

    def send(self, message: object) -> None:
        self.sent.append(message)
        if self._send_error is not None:
            raise self._send_error

    def recv(self) -> object:
        if not self._incoming:
            raise EOFError
        return self._incoming.pop(0)

    def poll(self, timeout: float) -> bool:
        return bool(self._incoming)

    def close(self) -> None:
        self.closed = True


class _FakeProcess:
    def __init__(self, *, pid: int, exits_after_joins: int) -> None:
        self.pid = pid
        self._exits_after_joins = exits_after_joins
        self._join_count = 0

    def is_alive(self) -> bool:
        return self._join_count < self._exits_after_joins

    def join(self, timeout: float) -> None:
        self._join_count += 1


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
            if isinstance(resp, (ScoreResponse, EnvProbeResponse)):
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


def test_child_reports_a_missing_audio_file_as_an_error(tmp_path: Path) -> None:
    """The child answers a request it cannot fulfil with ScoreResponse.error,
    rather than crashing, hanging, or reporting empty scores as success.

    The rejection happens before any scorer is dispatched, so the outcome does
    not depend on which optional scoring dependencies are installed. It used
    to: naming ``text_accuracy`` reached a ~6s Whisper load that starved the
    poll budget (issue #184), and naming ``silence`` reached no scorer at all
    where librosa is absent — as in CI — which made the request succeed with
    every scorer skipped (issue #186).
    """
    from songmaker_cli.scoring.pipeline import PipelineConfig

    missing = tmp_path / "nonexistent.mp3"

    responses = _run_child_with_messages([
        ScoreRequest(
            mp3_path=missing,
            meta=None,
            scorers=["silence"],
            config=PipelineConfig(device="cpu"),
        ),
        ShutdownRequest(),
    ])
    score_responses = [r for r in responses if isinstance(r, ScoreResponse)]
    assert len(score_responses) == 1
    resp = score_responses[0]
    assert resp.scores is None
    assert resp.error is not None
    assert str(missing) in resp.error


@pytest.mark.parametrize(
    ("pipeline_result", "expected_error"),
    (
        (SongScores(), None),
        (RuntimeError("scorer failed"), "scorer failed"),
    ),
)
def test_child_publishes_progress_and_a_terminal_pipeline_result(
    monkeypatch: pytest.MonkeyPatch,
    pipeline_result: SongScores | RuntimeError,
    expected_error: str | None,
) -> None:
    from songmaker_cli.scoring import pipeline
    from songmaker_cli.scoring.pipeline import PipelineConfig

    request = ScoreRequest(
        mp3_path=Path("song.mp3"),
        meta=None,
        scorers=["silence"],
        config=PipelineConfig(device="cpu"),
        job_id="score-42",
    )
    conn = _FakeConnection(incoming=[request, ShutdownRequest()])
    progress_callbacks: list[tuple[int, int, str]] = []

    def run_pipeline(*_args, on_progress, **_kwargs) -> SongScores:
        on_progress(1, 1, "silence")
        progress_callbacks.append((1, 1, "silence"))
        if isinstance(pipeline_result, Exception):
            raise pipeline_result
        return pipeline_result

    monkeypatch.setattr(pipeline.default_registry, "ensure_loaded", lambda: None)
    monkeypatch.setattr(pipeline, "run_scoring_pipeline", run_pipeline)
    monkeypatch.setattr("songmaker_cli.scoring.subprocess_runner.signal.signal", lambda *_: None)

    _child_main(conn)  # type: ignore[arg-type]

    assert progress_callbacks == [(1, 1, "silence")]
    assert conn.closed is True
    assert conn.sent[0] == ScoreProgressUpdate(completed=1, total=1, scorer_name="silence")
    response = conn.sent[1]
    assert isinstance(response, ScoreResponse)
    assert response.scores is (None if expected_error else pipeline_result)
    assert response.error == expected_error


def test_child_confirms_that_it_scrubbed_the_inherited_secret_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from songmaker_cli.scoring import pipeline

    secret_key = SECRET_ENV_KEYS[0]
    monkeypatch.setenv(secret_key, "secret")
    conn = _FakeConnection(incoming=[
        EnvProbeRequest(keys=(secret_key, _TEST_MARKER_KEY)),
        ShutdownRequest(),
    ])
    monkeypatch.setenv(_TEST_MARKER_KEY, "visible")
    monkeypatch.setattr(pipeline.default_registry, "ensure_loaded", lambda: None)
    monkeypatch.setattr("songmaker_cli.scoring.subprocess_runner.signal.signal", lambda *_: None)

    _child_main(conn)  # type: ignore[arg-type]

    assert conn.sent == [EnvProbeResponse(present=frozenset({_TEST_MARKER_KEY}))]
    assert conn.closed is True


def test_child_stops_cleanly_when_its_parent_connection_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from songmaker_cli.scoring import pipeline

    conn = _FakeConnection()
    monkeypatch.setattr(pipeline.default_registry, "ensure_loaded", lambda: None)
    monkeypatch.setattr("songmaker_cli.scoring.subprocess_runner.signal.signal", lambda *_: None)

    _child_main(conn)  # type: ignore[arg-type]

    assert conn.sent == []
    assert conn.closed is False


# ── Secret env scrubbing ─────────────────────────────────────────

_TEST_MARKER_KEY = "SONGMAKER_TEST_NON_SECRET_MARKER"


def test_scorer_child_drops_secret_env_keys_at_spawn(monkeypatch) -> None:
    """The scorer child inherits the full parent env at spawn (multiprocessing
    has no env= parameter), so _child_main must scrub secrets itself, first
    thing. Drives the real _child_main (via _run_child_with_messages) rather
    than a test-only stand-in, so deleting the scrub call site fails this.
    """
    probed_keys = (*SECRET_ENV_KEYS, _TEST_MARKER_KEY)
    for key in SECRET_ENV_KEYS:
        monkeypatch.setenv(key, "leaked-secret-value")
    monkeypatch.setenv(_TEST_MARKER_KEY, "visible-non-secret")
    responses = _run_child_with_messages([
        EnvProbeRequest(keys=probed_keys),
        ShutdownRequest(),
    ])

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

    config = PipelineConfig(device="cpu", pipeline_timeout=1)
    with pytest.raises(TimeoutError):
        sp.score(
            mp3, scorers=[],
            config=config,
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


def _empty_config():
    from songmaker_cli.scoring.pipeline import PipelineConfig

    return PipelineConfig(device="cpu")


def _run_returning(result: SongScores, sp: ScorerProcess, mp3: Path) -> None:
    """Drive one real request whose result is canned, so a test can pin what
    the reported outcomes do to the child without running a real scorer."""
    from unittest.mock import patch

    with patch.object(ScorerProcess, "_poll_response", return_value=result):
        sp.score(mp3, scorers=[], config=_empty_config())


def test_a_child_that_timed_out_a_scorer_is_not_reused_by_the_next_request(
    tmp_path: Path,
) -> None:
    """The scorer was abandoned, not stopped, so it still runs in that child.
    The next request gets a fresh one even if nobody recycled it — a job
    cancelled before it could is exactly that case."""
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"fake")
    timed_out = SongScores(
        runs=(ScorerRun(scorer="text_accuracy", outcome=ScorerOutcome.TIMED_OUT),),
    )

    sp = ScorerProcess()
    _run_returning(timed_out, sp, mp3)
    tainted_pid = sp._process.pid

    result = sp.score(mp3, scorers=[], config=_empty_config())

    assert isinstance(result, SongScores)
    assert sp._process.pid != tainted_pid
    sp.shutdown()


def test_a_child_that_kept_every_scorer_in_budget_serves_the_next_request(
    tmp_path: Path,
) -> None:
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"fake")
    clean = SongScores(
        runs=(ScorerRun(scorer="text_accuracy", outcome=ScorerOutcome.OK),),
    )

    sp = ScorerProcess()
    _run_returning(clean, sp, mp3)
    first_pid = sp._process.pid

    sp.score(mp3, scorers=[], config=_empty_config())

    assert sp._process.pid == first_pid
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


def test_scorer_process_retries_a_crashed_request_with_a_fresh_connection() -> None:
    from songmaker_cli.scoring.pipeline import PipelineConfig

    expected = SongScores()
    crashed = _FakeConnection(send_error=BrokenPipeError())
    recovered = _FakeConnection(incoming=[ScoreResponse(scores=expected, error=None)])
    sp = ScorerProcess()
    connections = iter((crashed, recovered))
    with patch.object(sp, "_ensure_started", side_effect=lambda: next(connections)):
        result = sp.score(Path("song.mp3"), scorers=[], config=PipelineConfig(device="cpu"))

    assert result is expected
    assert len(crashed.sent) == 1
    assert len(recovered.sent) == 1


def test_scorer_process_stops_after_the_replacement_child_also_crashes() -> None:
    from songmaker_cli.scoring.pipeline import PipelineConfig

    sp = ScorerProcess()
    connections = iter((
        _FakeConnection(send_error=BrokenPipeError()),
        _FakeConnection(send_error=BrokenPipeError()),
    ))
    with (
        patch.object(sp, "_ensure_started", side_effect=lambda: next(connections)),
        pytest.raises(RuntimeError, match="crashed twice"),
    ):
        sp.score(Path("song.mp3"), scorers=[], config=PipelineConfig(device="cpu"))


def test_scorer_process_propagates_a_child_pipeline_error() -> None:
    from songmaker_cli.scoring.pipeline import PipelineConfig

    conn = _FakeConnection(incoming=[ScoreResponse(scores=None, error="scorer failed")])
    sp = ScorerProcess()
    with (
        patch.object(sp, "_ensure_started", return_value=conn),
        pytest.raises(RuntimeError, match="scorer failed"),
    ):
        sp.score(Path("song.mp3"), scorers=[], config=PipelineConfig(device="cpu"))


def test_scorer_process_delivers_progress_before_its_final_scores() -> None:
    from songmaker_cli.scoring.pipeline import PipelineConfig

    expected = SongScores()
    conn = _FakeConnection(incoming=[
        ScoreProgressUpdate(completed=1, total=2, scorer_name="silence"),
        ScoreResponse(scores=expected, error=None),
    ])
    progress: list[tuple[int, int, str]] = []

    def record_progress(completed: int, total: int, scorer: str) -> None:
        progress.append((completed, total, scorer))

    sp = ScorerProcess()
    with patch.object(sp, "_ensure_started", return_value=conn):
        result = sp.score(
            Path("song.mp3"),
            scorers=["silence"],
            config=PipelineConfig(device="cpu"),
            on_progress=record_progress,
        )

    assert result is expected
    assert progress == [(1, 2, "silence")]


def test_scorer_process_times_out_before_waiting_for_a_child_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from songmaker_cli.scoring import subprocess_runner
    from songmaker_cli.scoring.pipeline import PipelineConfig

    conn = _FakeConnection()
    sp = ScorerProcess()
    monotonic_values = iter((10.0, 11.0))
    monkeypatch.setattr(subprocess_runner.time, "monotonic", lambda: next(monotonic_values))
    with (
        patch.object(sp, "_ensure_started", return_value=conn),
        patch.object(sp, "_kill") as kill,
        pytest.raises(TimeoutError, match="1s"),
    ):
        sp.score(
            Path("song.mp3"),
            scorers=["silence"],
            config=PipelineConfig(device="cpu", pipeline_timeout=1),
        )

    assert conn.sent
    kill.assert_called_once()


def test_scorer_process_recycles_a_live_child_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sp = ScorerProcess()
    process = _FakeProcess(pid=7122, exits_after_joins=1)
    conn = _FakeConnection()
    signals: list[signal.Signals] = []
    sp._process = process  # type: ignore[assignment]
    sp._conn = conn  # type: ignore[assignment]
    monkeypatch.setattr(
        "songmaker_cli.scoring.subprocess_runner.os.kill",
        lambda _pid, signal_number: signals.append(signal_number),
    )

    sp.recycle()

    assert signals == [signal.SIGTERM]
    assert conn.closed is True
    assert not sp.alive


def test_scorer_process_shutdown_releases_an_already_dead_connection() -> None:
    sp = ScorerProcess()
    conn = _FakeConnection()
    sp._conn = conn  # type: ignore[assignment]

    sp.shutdown()

    assert conn.closed is True


def test_scorer_process_shutdown_escalates_for_a_child_that_ignores_its_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sp = ScorerProcess()
    process = _FakeProcess(pid=7123, exits_after_joins=3)
    conn = _FakeConnection()
    signals: list[signal.Signals] = []
    sp._process = process  # type: ignore[assignment]
    sp._conn = conn  # type: ignore[assignment]
    monkeypatch.setattr(
        "songmaker_cli.scoring.subprocess_runner.os.kill",
        lambda _pid, signal_number: signals.append(signal_number),
    )

    sp.shutdown()

    assert conn.sent == [ShutdownRequest()]
    assert conn.closed is True
    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert not sp.alive


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

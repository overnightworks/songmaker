"""Long-lived scorer subprocess with graceful timeout.

Spawns a persistent child process that loads scorer models once and receives
scoring tasks via multiprocessing.Pipe. On timeout the parent sends SIGTERM
(allowing GPU memory cleanup), then SIGKILL after a 5-second grace period.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.connection import Connection
from pathlib import Path

from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import SongScores
from songmaker_cli.scoring.pipeline import PipelineConfig

log = logging.getLogger(__name__)

_ctx = multiprocessing.get_context("spawn")


@dataclass(frozen=True)
class ScoreRequest:
    mp3_path: Path
    meta: SongMeta | None
    scorers: list[str] | None
    config: PipelineConfig
    job_id: str | None = None


@dataclass(frozen=True)
class ScoreResponse:
    scores: SongScores | None
    error: str | None


@dataclass(frozen=True)
class ReleaseGpuRequest:
    pass


@dataclass(frozen=True)
class ReleaseGpuResponse:
    success: bool


@dataclass(frozen=True)
class ScoreProgressUpdate:
    completed: int
    total: int
    scorer_name: str


@dataclass(frozen=True)
class ShutdownRequest:
    pass


def _cleanup_gpu_and_exit(_signum: int, _frame: object) -> None:
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    raise SystemExit(0)


def _release_scorer_models() -> None:
    import gc

    try:
        from songmaker_cli.scoring.text_accuracy import clear_cache as clear_whisper
        clear_whisper()
    except ImportError:
        pass

    try:
        from songmaker_cli.scoring.audiobox_aesthetics import clear_cache as clear_audiobox
        clear_audiobox()
    except ImportError:
        pass

    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _child_main(conn: Connection) -> None:
    from songmaker_cli.scoring.pipeline import default_registry, run_scoring_pipeline

    signal.signal(signal.SIGTERM, _cleanup_gpu_and_exit)
    default_registry.ensure_loaded()

    while True:
        try:
            request = conn.recv()
        except EOFError:
            break

        if isinstance(request, ShutdownRequest):
            conn.close()
            break

        if isinstance(request, ReleaseGpuRequest):
            _release_scorer_models()
            conn.send(ReleaseGpuResponse(success=True))
            continue

        if isinstance(request, ScoreRequest):
            if request.job_id:
                import structlog
                structlog.contextvars.bind_contextvars(
                    job_id=request.job_id, process="scorer",
                )

            def _progress_cb(completed: int, total: int, name: str) -> None:
                conn.send(ScoreProgressUpdate(completed=completed, total=total, scorer_name=name))

            try:
                scores = run_scoring_pipeline(
                    request.mp3_path,
                    meta=request.meta,
                    scorers=request.scorers,
                    config=request.config,
                    on_progress=_progress_cb,
                )
                conn.send(ScoreResponse(scores=scores, error=None))
            except Exception as exc:
                conn.send(ScoreResponse(scores=None, error=str(exc)))
            continue


class ScorerProcess:

    def __init__(self) -> None:
        self._process: multiprocessing.Process | None = None
        self._conn: Connection | None = None
        self._pipe_lock = threading.Lock()

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.is_alive()

    def _ensure_started(self) -> Connection:
        if self.alive and self._conn is not None:
            return self._conn
        self._cleanup_dead()
        parent_conn, child_conn = _ctx.Pipe()
        self._process = _ctx.Process(target=_child_main, args=(child_conn,), daemon=True)
        self._process.start()
        child_conn.close()
        self._conn = parent_conn
        log.info("Scorer subprocess started (PID %d)", self._process.pid)
        return parent_conn

    def score(
        self,
        mp3_path: Path,
        meta: SongMeta | None = None,
        scorers: list[str] | None = None,
        config: PipelineConfig | None = None,
        job_id: str | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> SongScores:
        effective_config = config or PipelineConfig()
        return self._score_with_retry(
            mp3_path, meta, scorers, effective_config, job_id, on_progress,
        )

    def _score_with_retry(
        self,
        mp3_path: Path,
        meta: SongMeta | None,
        scorers: list[str] | None,
        config: PipelineConfig,
        job_id: str | None,
        on_progress: Callable[[int, int, str], None] | None,
    ) -> SongScores:
        # Lock held across send + poll so concurrent score() calls (when
        # SCORING_MAX_JOBS > 1) cannot interleave Pipe writes/reads on the
        # single shared subprocess. multiprocessing.Pipe is not thread-safe.
        with self._pipe_lock:
            for attempt in (1, 2):
                conn = self._ensure_started()
                request = ScoreRequest(
                    mp3_path=mp3_path, meta=meta, scorers=scorers,
                    config=config, job_id=job_id,
                )
                try:
                    conn.send(request)
                    return self._poll_response(conn, scorers, config, on_progress)
                except (BrokenPipeError, EOFError, ConnectionResetError):
                    if attempt == 2:
                        raise RuntimeError("Scorer subprocess crashed twice — aborting")
                    log.warning("Scorer subprocess died mid-scoring — respawning and retrying")
                    self._cleanup_dead()
            raise RuntimeError("unreachable")

    def _poll_response(
        self,
        conn: Connection,
        scorers: list[str] | None,
        config: PipelineConfig,
        on_progress: Callable[[int, int, str], None] | None,
    ) -> SongScores:
        deadline = time.monotonic() + config.pipeline_timeout

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            if not conn.poll(timeout=remaining):
                break

            msg = conn.recv()
            if isinstance(msg, ScoreResponse):
                if msg.error:
                    raise RuntimeError(msg.error)
                assert msg.scores is not None
                return msg.scores
            if isinstance(msg, ScoreProgressUpdate) and on_progress:
                on_progress(msg.completed, msg.total, msg.scorer_name)

        scorer_desc = ", ".join(scorers) if scorers else "all"
        log.error(
            "Scorer subprocess timed out after %ds — killing (requested scorers: %s)",
            config.pipeline_timeout, scorer_desc,
        )
        self._kill()
        raise TimeoutError(f"Scoring timed out after {config.pipeline_timeout}s")

    def release_gpu(self, timeout: int = 30) -> None:
        if not self.alive:
            return
        assert self._conn is not None
        self._conn.send(ReleaseGpuRequest())
        if self._conn.poll(timeout=timeout):
            self._conn.recv()
        else:
            log.warning("release_gpu timed out — killing subprocess")
            self._kill()

    def shutdown(self) -> None:
        if not self.alive:
            self._cleanup_dead()
            return
        try:
            if self._conn:
                self._conn.send(ShutdownRequest())
                self._process.join(timeout=5)
        except (OSError, BrokenPipeError, EOFError):
            log.debug("Shutdown send failed — subprocess may have already exited", exc_info=True)
        if self.alive:
            self._kill()
        self._cleanup_dead()

    def _kill(self) -> None:
        if self._process and self._process.is_alive():
            os.kill(self._process.pid, signal.SIGTERM)
            self._process.join(timeout=5)
            if self._process.is_alive():
                log.warning("Scorer subprocess did not exit after SIGTERM — sending SIGKILL")
                os.kill(self._process.pid, signal.SIGKILL)
                self._process.join(timeout=5)
        self._cleanup_dead()

    def _cleanup_dead(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except (OSError, BrokenPipeError):
                log.debug("Failed to close scorer connection during cleanup", exc_info=True)
        self._conn = None
        self._process = None


_scorer_process: ScorerProcess | None = None
_scorer_process_lock = threading.Lock()


def set_scorer_process(process: ScorerProcess) -> None:
    global _scorer_process
    with _scorer_process_lock:
        _scorer_process = process


def get_scorer_process() -> ScorerProcess:
    with _scorer_process_lock:
        proc = _scorer_process
    if proc is None:
        raise RuntimeError("ScorerProcess not initialized — worker startup may have failed")
    return proc

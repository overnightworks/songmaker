"""Long-lived scorer subprocess with kill-based timeout.

Spawns a persistent child process that loads scorer models once and receives
scoring tasks via multiprocessing.Pipe. On timeout the parent kills the child
with SIGKILL, freeing all GPU memory and resources immediately.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import signal
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


def _child_main(conn: Connection) -> None:
    from songmaker_cli.scoring.pipeline import default_registry, run_scoring_pipeline

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
            from songmaker_cli.acestep_manager import clear_scoring_models
            clear_scoring_models()
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
        conn = self._ensure_started()

        conn.send(ScoreRequest(
            mp3_path=mp3_path, meta=meta, scorers=scorers,
            config=effective_config, job_id=job_id,
        ))

        timeout = effective_config.pipeline_timeout
        deadline = time.monotonic() + timeout

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

        log.error("Scorer subprocess timed out after %ds — killing", timeout)
        self._kill()
        raise TimeoutError(f"Scoring timed out after {timeout}s")

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
        except Exception:
            pass
        if self.alive:
            self._kill()
        self._cleanup_dead()

    def _kill(self) -> None:
        if self._process and self._process.is_alive():
            os.kill(self._process.pid, signal.SIGKILL)
            self._process.join(timeout=5)
        self._cleanup_dead()

    def _cleanup_dead(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = None
        self._process = None


_scorer_process: ScorerProcess | None = None


def set_scorer_process(process: ScorerProcess) -> None:
    global _scorer_process
    _scorer_process = process


def get_scorer_process() -> ScorerProcess:
    if _scorer_process is None:
        raise RuntimeError("ScorerProcess not initialized — worker startup may have failed")
    return _scorer_process

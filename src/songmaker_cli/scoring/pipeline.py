"""Scoring pipeline — registry, runner, and orchestration."""

from __future__ import annotations

import logging
import os
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import numpy as np

from songmaker_cli.constants import (
    SCORER_TIMEOUT_SECONDS,
    SCORING_PIPELINE_TIMEOUT_HEADROOM_SECONDS,
    SCORING_PIPELINE_TIMEOUT_SECONDS,
    TEXT_ACCURACY_TIMEOUT_SECONDS,
)
from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import (
    SCORE_TYPES,
    ScorerExecution,
    ScorerOutcome,
    ScorerRun,
    SongScores,
)
from songmaker_cli.scoring.registry import (
    CHILD_SCORER_NAMES,
    DEVICE_CPU,
    DEVICE_GPU,
    SCORERS,
    TEXT_ACCURACY_SCORER,
    VALID_SCORER_NAMES,
)

log = logging.getLogger(__name__)

__all__ = [
    "DEVICE_CPU",
    "DEVICE_GPU",
    "SCORERS",
    "VALID_SCORER_NAMES",
    "ScorerDependencyUnavailable",
]


@dataclass(frozen=True)
class AudioData:
    """Pre-loaded audio shared across scorers to avoid redundant decoding."""

    audio: np.ndarray
    sr: int


@dataclass(frozen=True)
class PipelineConfig:
    """Configuration passed to all scorers in the scorer child.

    Deliberately self-contained: every scorer reads its configuration from
    this object, never from ``get_settings()``. The parent process resolves
    Settings and fills these fields before sending a ``ScoreRequest`` across
    the pipe to the child, whose own ``os.environ`` has had
    ``SECRET_ENV_KEYS`` scrubbed at spawn. No field here is a secret — every
    scorer that needs one runs in the parent (see ``ScorerHost``).
    """

    whisper_model: str = "large-v3"  # turbo is faster but hallucinates on ~5% of songs
    whisper_device: str = ""
    device: str = "cpu"
    scorer_timeout: int = SCORER_TIMEOUT_SECONDS
    text_accuracy_timeout: int = TEXT_ACCURACY_TIMEOUT_SECONDS
    pipeline_timeout: int = 0

    def __post_init__(self) -> None:
        if self.pipeline_timeout <= 0:
            object.__setattr__(self, "pipeline_timeout", self._watchdog_timeout())

    def timeout_for(self, scorer: str) -> int:
        """Time budget for one scorer. text_accuracy has its own because a
        cold Whisper model load counts against it."""
        if scorer == TEXT_ACCURACY_SCORER:
            return self.text_accuracy_timeout
        return self.scorer_timeout

    def _watchdog_timeout(self) -> int:
        """Outer budget for the whole child run.

        The child runs its scorers concurrently, so the run is bounded by its
        slowest one. The watchdog must outlive that plus audio load and thread
        joins — if it fires first the subprocess is killed and even the values
        this run did produce are lost.
        """
        slowest_scorer = max(self.scorer_timeout, self.text_accuracy_timeout)
        return max(
            SCORING_PIPELINE_TIMEOUT_SECONDS,
            slowest_scorer + SCORING_PIPELINE_TIMEOUT_HEADROOM_SECONDS,
        )


ScorerFunc = Callable[
    [Path, SongMeta | None, AudioData | None, PipelineConfig], object,
]


class ScorerRegistry:
    """Registry of the scorer functions this child runs. Supports lazy
    loading and test isolation.

    Metadata (needs_audio, device, host, output_keys) lives in the SCORERS
    table in scoring/registry.py — this class only holds the function refs
    populated at module-import time by @register.
    """

    def __init__(self, *, autoload: bool = False) -> None:
        self._scorers: dict[str, ScorerFunc] = {}
        self._loaded: bool = False
        self._autoload: bool = autoload

    def register(self, name: str) -> Callable[[ScorerFunc], ScorerFunc]:
        """Decorator to register a scorer function.

        The name must be a child-hosted scorer in SCORERS
        (scoring/registry.py) — a parent-hosted one never runs here.
        """

        def decorator(func: ScorerFunc) -> ScorerFunc:
            if name not in CHILD_SCORER_NAMES:
                raise ValueError(
                    f"Scorer name '{name}' is not a scorer this process runs. "
                    f"Valid names: {sorted(CHILD_SCORER_NAMES)}"
                )
            self._scorers[name] = func
            return func

        return decorator

    def available(self) -> list[str]:
        self.ensure_loaded()
        return list(self._scorers.keys())

    def get(self, name: str) -> ScorerFunc | None:
        return self._scorers.get(name)

    def scorer_needs_audio(self, name: str) -> bool:
        spec = SCORERS.get(name)
        return spec.needs_audio if spec else True

    def scorer_uses_gpu(self, name: str) -> bool:
        spec = SCORERS.get(name)
        return spec.device == DEVICE_GPU if spec else False

    def all_names(self) -> list[str]:
        return list(self._scorers.keys())

    _SCORER_MODULES = (
        "songmaker_cli.scoring.audiobox_aesthetics",
        "songmaker_cli.scoring.bpm_accuracy",
        "songmaker_cli.scoring.emotional_dynamics",
        "songmaker_cli.scoring.silence_detection",
        "songmaker_cli.scoring.spectral_quality",
        "songmaker_cli.scoring.text_accuracy",
    )

    def ensure_loaded(self) -> None:
        """Lazily import scorer modules to trigger @register decorators.

        Only runs on registries created with autoload=True (i.e. the
        default_registry). Test registries skip this entirely.
        Modules with missing dependencies are skipped gracefully.
        """
        if self._loaded or not self._autoload:
            return
        self._loaded = True
        import importlib
        for mod_name in self._SCORER_MODULES:
            try:
                importlib.import_module(mod_name)
            except ImportError:
                log.debug("Scorer module %s unavailable (missing dependency)", mod_name)

    def reset_for_testing(self) -> None:
        """Clear all scorers for test isolation."""
        self._scorers.clear()
        self._loaded = False


default_registry = ScorerRegistry(autoload=True)
register = default_registry.register


def available_scorers() -> list[str]:
    """Return names of all registered scorers."""
    return default_registry.available()


def load_audio(mp3_path: Path) -> AudioData:
    """Load and resample audio once for all scorers."""
    import librosa

    from songmaker_cli.constants import SCORING_SAMPLE_RATE

    audio, sr = librosa.load(mp3_path, sr=SCORING_SAMPLE_RATE, mono=True)
    return AudioData(audio=audio, sr=sr)


class _ScorerTimeout(Exception):
    """Raised when a scorer exceeds its time limit."""


class ScorerDependencyUnavailable(Exception):
    """Raised by a scorer whose input another scorer did not produce.

    Not a failure: the scorer is reported as skipped with this reason, and
    whatever the generation already scored for it stays untouched.
    """


def _call_with_timeout(call: Callable[[], object], timeout: int, name: str) -> object:
    """Run a scorer call with a thread-based timeout.

    Uses ThreadPoolExecutor instead of SIGALRM because SIGALRM is unsafe
    with C extensions (numpy, torch, librosa) that hold the GIL. A thread
    cannot be killed, so a scorer over budget is abandoned, not stopped.
    """
    if timeout <= 0:
        return call()

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(call).result(timeout=timeout)
    except FuturesTimeout:
        raise _ScorerTimeout(f"Scorer '{name}' timed out after {timeout}s")
    finally:
        # wait=False: the budget is a ceiling. Joining here would hand the
        # scorer that blew it exactly the time the timeout just denied it.
        pool.shutdown(wait=False)


def _ended(name: str, outcome: ScorerOutcome, detail: str) -> ScorerExecution:
    return ScorerExecution(run=ScorerRun(scorer=name, outcome=outcome, detail=detail))


def run_scorer(name: str, call: Callable[[], object], timeout: int) -> ScorerExecution:
    """Run one scorer under its own time budget and classify how it ended.

    Never raises — a scorer's fate is data, so one scorer cannot abort the
    run and only a successful one may overwrite a stored score. Used for
    both the child's own scorers and the parent-hosted ones.
    """
    log.info("Running scorer: %s (budget %ds)", name, timeout)
    try:
        value = _call_with_timeout(call, timeout, name)
    except _ScorerTimeout as exc:
        log.error("Scorer '%s' timed out after %ds — keeping its stored score", name, timeout)
        return _ended(name, ScorerOutcome.TIMED_OUT, str(exc))
    except ScorerDependencyUnavailable as exc:
        log.info("Scorer '%s' skipped: %s", name, exc)
        return _ended(name, ScorerOutcome.SKIPPED, str(exc))
    except Exception as exc:  # noqa: BLE001 — scorer failures must not block others
        log.exception("Scorer '%s' failed", name)
        return _ended(name, ScorerOutcome.FAILED, str(exc))

    expected_type = SCORE_TYPES[name]
    if not isinstance(value, expected_type):
        log.warning(
            "Scorer '%s' returned %s, expected %s",
            name, type(value).__name__, expected_type.__name__,
        )
        return _ended(
            name, ScorerOutcome.FAILED,
            f"returned {type(value).__name__}, expected {expected_type.__name__}",
        )
    return ScorerExecution(run=ScorerRun(scorer=name, outcome=ScorerOutcome.OK), value=value)


def _unrunnable(name: str, reg: ScorerRegistry) -> ScorerExecution | None:
    """Classify a requested scorer that has no registered function.

    A child scorer whose module could not be imported is skipped; a name this
    process does not run at all is a caller mistake and only warns.
    """
    if name in CHILD_SCORER_NAMES:
        log.warning("Scorer '%s' is not registered — skipping", name)
        return _ended(name, ScorerOutcome.SKIPPED, "scorer not registered")
    log.warning("Unknown scorer: %s (available: %s)", name, ", ".join(reg.all_names()))
    return None


def _scorer_call(
    name: str,
    reg: ScorerRegistry,
    mp3_path: Path,
    meta: SongMeta | None,
    audio_data: AudioData | None,
    config: PipelineConfig,
) -> Callable[[], object]:
    func = reg.get(name)
    return lambda: func(mp3_path, meta, audio_data, config)


def _submit_scorers(
    pool: ThreadPoolExecutor,
    names: list[str],
    reg: ScorerRegistry,
    mp3_path: Path,
    meta: SongMeta | None,
    audio_data: AudioData | None,
    config: PipelineConfig,
) -> list[Future[ScorerExecution]]:
    return [
        pool.submit(
            run_scorer,
            name,
            _scorer_call(name, reg, mp3_path, meta, audio_data, config),
            config.timeout_for(name),
        )
        for name in names
    ]


def _collect_futures(
    futures: list[Future[ScorerExecution]],
    on_scorer_done: Callable[[str], None],
) -> list[ScorerExecution]:
    executions = []
    for future in as_completed(futures):
        execution = future.result()
        executions.append(execution)
        on_scorer_done(execution.run.scorer)
    return executions


def _aggregate(
    executions: list[ScorerExecution], requested_order: list[str],
) -> SongScores:
    """Build the run's SongScores, with runs ordered as the caller asked."""
    by_scorer = {execution.run.scorer: execution for execution in executions}
    values = {
        name: execution.value
        for name, execution in by_scorer.items()
        if execution.run.produced_value
    }
    runs = tuple(
        by_scorer[name].run for name in requested_order if name in by_scorer
    )
    return SongScores(runs=runs, **values)


def run_scoring_pipeline(
    mp3_path: Path,
    meta: SongMeta | None = None,
    scorers: list[str] | None = None,
    config: PipelineConfig | None = None,
    registry: ScorerRegistry | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> SongScores:
    """Run all (or selected) child scorers on an MP3 and return aggregated scores.

    Audio is loaded once and shared across all scorers. Every scorer reports
    its own outcome (ok / failed / skipped / timed out) in ``SongScores.runs``;
    one scorer's fate never blocks or invalidates another's.

    Execution strategy for parallelism:
    1. Independent CPU scorers run concurrently in a thread pool
    2. GPU scorers run sequentially in the main thread (VRAM contention)
    CPU and GPU phases overlap — CPU scorers execute during GPU inference.

    Raises FileNotFoundError if there is no audio file to score. Without that
    check the outcome depends on which scorer modules happened to import: a
    request naming only unregistered scorers never reaches ``load_audio``, so
    an unreadable generation would come back as a clean, empty success.
    """
    if not mp3_path.is_file():
        raise FileNotFoundError(f"No audio file to score at {mp3_path}")

    reg = registry or default_registry
    reg.ensure_loaded()
    if scorers is None:
        scorers = reg.all_names()
    if config is None:
        config = PipelineConfig()

    executions: list[ScorerExecution] = []
    runnable: list[str] = []
    for name in scorers:
        if reg.get(name) is not None:
            runnable.append(name)
            continue
        unrunnable = _unrunnable(name, reg)
        if unrunnable is not None:
            executions.append(unrunnable)

    any_needs_audio = any(reg.scorer_needs_audio(name) for name in runnable)
    audio_data = load_audio(mp3_path) if any_needs_audio else None

    gpu_names = [n for n in runnable if reg.scorer_uses_gpu(n)]
    cpu_names = [n for n in runnable if n not in gpu_names]

    completed_count = 0

    def _on_scorer_done(name: str) -> None:
        nonlocal completed_count
        completed_count += 1
        if on_progress:
            on_progress(completed_count, len(runnable), name)

    with ThreadPoolExecutor(max_workers=min(max(len(cpu_names), 1), os.cpu_count() or 4)) as pool:
        cpu_futures = _submit_scorers(
            pool, cpu_names, reg, mp3_path, meta, audio_data, config,
        )

        for name in gpu_names:
            executions.append(run_scorer(
                name,
                _scorer_call(name, reg, mp3_path, meta, audio_data, config),
                config.timeout_for(name),
            ))
            _on_scorer_done(name)

        executions.extend(_collect_futures(cpu_futures, _on_scorer_done))

    return _aggregate(executions, scorers)

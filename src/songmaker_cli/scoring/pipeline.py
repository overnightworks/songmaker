"""Scoring pipeline — registry, runner, and orchestration."""

from __future__ import annotations

import logging
import os
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, fields
from pathlib import Path
from typing import TYPE_CHECKING, Callable, TypeVar

if TYPE_CHECKING:
    import numpy as np

from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import (
    AudioBoxScore,
    BpmAccuracyScore,
    EmotionalDynamicsScore,
    LyricalCoherenceScore,
    SilenceScore,
    SongScores,
    SpectralQualityScore,
    TextAccuracyScore,
)

log = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class AudioData:
    """Pre-loaded audio shared across scorers to avoid redundant decoding."""

    audio: np.ndarray
    sr: int


SCORER_TIMEOUT_SECONDS = 300
DEVICE_CPU = "cpu"
DEVICE_GPU = "gpu"


@dataclass(frozen=True)
class PipelineConfig:
    """Configuration passed to all scorers."""

    whisper_model: str = "large-v3"  # turbo is faster but hallucinates on ~5% of songs
    whisper_device: str = ""
    device: str = "cpu"
    scorer_timeout: int = SCORER_TIMEOUT_SECONDS


ScorerFunc = Callable[[Path, SongMeta | None, AudioData | None, PipelineConfig, dict], object]

_VALID_SCORER_NAMES = frozenset(f.name for f in fields(SongScores))


class ScorerRegistry:
    """Registry of scorer functions. Supports lazy loading and test isolation."""

    def __init__(self, *, autoload: bool = False) -> None:
        self._scorers: dict[str, ScorerFunc] = {}
        self._needs_audio: dict[str, bool] = {}
        self._device: dict[str, str] = {}
        self._after_gpu: dict[str, bool] = {}
        self._loaded: bool = False
        self._autoload: bool = autoload

    def register(
        self, name: str, needs_audio: bool = True,
        device: str = DEVICE_CPU, after_gpu: bool = False,
    ) -> Callable[[ScorerFunc], ScorerFunc]:
        """Decorator to register a scorer function.

        The name must match a field on SongScores (e.g. "silence", "bpm_accuracy").
        Set needs_audio=False for scorers that use file paths (e.g. Whisper, AudioBox).
        Set device="gpu" for scorers that require GPU (serialized to avoid VRAM contention).
        Set after_gpu=True for CPU scorers that depend on GPU scorer output via shared_data.
        """

        def decorator(func: ScorerFunc) -> ScorerFunc:
            if name not in _VALID_SCORER_NAMES:
                raise ValueError(
                    f"Scorer name '{name}' does not match any SongScores field. "
                    f"Valid names: {sorted(_VALID_SCORER_NAMES)}"
                )
            self._scorers[name] = func
            self._needs_audio[name] = needs_audio
            self._device[name] = device
            self._after_gpu[name] = after_gpu
            return func

        return decorator

    def available(self) -> list[str]:
        self.ensure_loaded()
        return list(self._scorers.keys())

    def get(self, name: str) -> ScorerFunc | None:
        return self._scorers.get(name)

    def scorer_needs_audio(self, name: str) -> bool:
        return self._needs_audio.get(name, True)

    def scorer_uses_gpu(self, name: str) -> bool:
        return self._device.get(name, DEVICE_CPU) == DEVICE_GPU

    def scorer_after_gpu(self, name: str) -> bool:
        return self._after_gpu.get(name, False)

    def all_names(self) -> list[str]:
        return list(self._scorers.keys())

    def ensure_loaded(self) -> None:
        """Lazily import scorer modules to trigger @register decorators.

        Only runs on registries created with autoload=True (i.e. the
        default_registry). Test registries skip this entirely.
        """
        if self._loaded or not self._autoload:
            return
        self._loaded = True
        import songmaker_cli.scoring.audiobox_aesthetics  # noqa: F401
        import songmaker_cli.scoring.bpm_accuracy  # noqa: F401
        import songmaker_cli.scoring.emotional_dynamics  # noqa: F401
        import songmaker_cli.scoring.lyrical_coherence  # noqa: F401
        import songmaker_cli.scoring.silence_detection  # noqa: F401
        import songmaker_cli.scoring.spectral_quality  # noqa: F401
        import songmaker_cli.scoring.text_accuracy  # noqa: F401

    def reset_for_testing(self) -> None:
        """Clear all scorers for test isolation."""
        self._scorers.clear()
        self._needs_audio.clear()
        self._device.clear()
        self._after_gpu.clear()
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


def _run_with_timeout(
    func: ScorerFunc, mp3_path: Path, meta: SongMeta | None,
    audio_data: AudioData | None, config: PipelineConfig,
    shared_data: dict, timeout: int, name: str,
) -> object:
    """Run a scorer with a thread-based timeout.

    Uses ThreadPoolExecutor instead of SIGALRM because SIGALRM is unsafe
    with C extensions (numpy, torch, librosa) that hold the GIL.
    """
    if timeout <= 0:
        return func(mp3_path, meta, audio_data, config, shared_data)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(func, mp3_path, meta, audio_data, config, shared_data)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeout:
            raise _ScorerTimeout(f"Scorer '{name}' timed out after {timeout}s")


def _validated(
    results: dict[str, object], key: str, expected_type: type[T],
) -> T | None:
    """Extract and type-check a scorer result, returning None on mismatch."""
    value = results.get(key)
    if value is None:
        return None
    if not isinstance(value, expected_type):
        log.warning(
            "Scorer '%s' returned %s, expected %s",
            key, type(value).__name__, expected_type.__name__,
        )
        return None
    return value


def _resolve_scorer(
    reg: ScorerRegistry, name: str,
) -> ScorerFunc | None:
    func = reg.get(name)
    if func is None:
        log.warning("Unknown scorer: %s (available: %s)", name, ", ".join(reg.all_names()))
    return func


def _submit_scorers(
    pool: ThreadPoolExecutor,
    names: list[str],
    reg: ScorerRegistry,
    mp3_path: Path,
    meta: SongMeta | None,
    audio_data: AudioData | None,
    config: PipelineConfig,
    shared_data: dict,
) -> dict[Future[object], str]:
    futures: dict[Future[object], str] = {}
    for name in names:
        func = _resolve_scorer(reg, name)
        if func is None:
            continue
        log.info("Running scorer: %s", name)
        future = pool.submit(
            _run_with_timeout, func, mp3_path, meta, audio_data,
            config, shared_data, config.scorer_timeout, name,
        )
        futures[future] = name
    return futures


def _collect_futures(
    futures: dict[Future[object], str],
    results: dict[str, object],
) -> None:
    for future in as_completed(futures):
        name = futures[future]
        try:
            results[name] = future.result()
        except Exception:  # noqa: BLE001 — scorer failures must not block others
            log.exception("Scorer '%s' failed", name)


def run_scoring_pipeline(
    mp3_path: Path,
    meta: SongMeta | None = None,
    scorers: list[str] | None = None,
    config: PipelineConfig | None = None,
    registry: ScorerRegistry | None = None,
) -> SongScores:
    """Run all (or selected) scorers on an MP3 and return aggregated scores.

    Audio is loaded once and shared across all scorers.
    Each scorer runs independently — one failure does not block others.

    Execution strategy for parallelism:
    1. Independent CPU scorers run concurrently in a thread pool
    2. GPU scorers run sequentially in the main thread (VRAM contention)
    3. CPU scorers that depend on GPU output (after_gpu) run after GPU completes
    CPU and GPU phases overlap — CPU scorers execute during GPU inference.
    """
    reg = registry or default_registry
    reg.ensure_loaded()
    if scorers is None:
        scorers = reg.all_names()
    if config is None:
        config = PipelineConfig()

    any_needs_audio = any(
        reg.scorer_needs_audio(s) for s in scorers if reg.get(s) is not None
    )
    audio_data = load_audio(mp3_path) if any_needs_audio else None

    gpu_names = [n for n in scorers if reg.scorer_uses_gpu(n)]
    cpu_names = [n for n in scorers if not reg.scorer_uses_gpu(n) and not reg.scorer_after_gpu(n)]
    deferred_cpu_names = [n for n in scorers if reg.scorer_after_gpu(n)]

    shared_data: dict = {}
    results: dict[str, object] = {}

    with ThreadPoolExecutor(max_workers=min(max(len(cpu_names), 1), os.cpu_count() or 4)) as pool:
        cpu_futures = _submit_scorers(
            pool, cpu_names, reg, mp3_path, meta, audio_data, config, shared_data,
        )

        for name in gpu_names:
            func = _resolve_scorer(reg, name)
            if func is None:
                continue
            try:
                log.info("Running scorer: %s", name)
                results[name] = _run_with_timeout(
                    func, mp3_path, meta, audio_data, config,
                    shared_data, config.scorer_timeout, name,
                )
            except Exception:  # noqa: BLE001 — scorer failures must not block others
                log.exception("Scorer '%s' failed", name)

        deferred_futures = _submit_scorers(
            pool, deferred_cpu_names, reg, mp3_path, meta, audio_data, config, shared_data,
        )

        _collect_futures(cpu_futures, results)
        _collect_futures(deferred_futures, results)

    return SongScores(
        text_accuracy=_validated(results, "text_accuracy", TextAccuracyScore),
        emotional_dynamics=_validated(results, "emotional_dynamics", EmotionalDynamicsScore),
        audiobox=_validated(results, "audiobox", AudioBoxScore),
        bpm_accuracy=_validated(results, "bpm_accuracy", BpmAccuracyScore),
        silence=_validated(results, "silence", SilenceScore),
        spectral_quality=_validated(results, "spectral_quality", SpectralQualityScore),
        lyrical_coherence=_validated(results, "lyrical_coherence", LyricalCoherenceScore),
    )

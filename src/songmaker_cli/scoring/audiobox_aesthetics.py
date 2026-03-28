"""AudioBox Aesthetics scorer — Meta's audio quality prediction model.

Scores audio on four dimensions (1-10 each):
- Content Enjoyment (CE): how enjoyable is the content
- Content Understanding (CU): how understandable is the content
- Production Complexity (PC): how complex is the production
- Production Quality (PQ): how well-produced is the audio
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import AudioBoxScore, SharedScorerData
from songmaker_cli.scoring.pipeline import DEVICE_GPU, AudioData, PipelineConfig, register

log = logging.getLogger(__name__)

_predictor: object | None = None
_predictor_device: str | None = None
_predictor_lock = threading.Lock()


def clear_cache() -> None:
    import gc

    global _predictor, _predictor_device
    with _predictor_lock:
        if _predictor is not None:
            if hasattr(_predictor, "model") and hasattr(_predictor.model, "cpu"):
                try:
                    _predictor.model.cpu()
                except Exception:
                    pass
        _predictor = None
        _predictor_device = None
    gc.collect()
    log.info("Cleared AudioBox model cache")


@contextmanager
def _force_cpu_env() -> Iterator[None]:
    """Temporarily hide CUDA devices to force CPU model loading.

    Must be used under _predictor_lock for thread safety.
    IMPORTANT: Scoring must remain sequential — the lock only protects
    against Songmaker threads, not other processes reading CUDA_VISIBLE_DEVICES.

    Known limitation: AesPredictor has no explicit device parameter, so
    env mutation is the only way to force CPU. If upstream adds device
    support, replace this with direct device passing.
    """
    saved = os.environ.get("CUDA_VISIBLE_DEVICES")
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("CUDA_VISIBLE_DEVICES", None)
        else:
            os.environ["CUDA_VISIBLE_DEVICES"] = saved


@register("audiobox", needs_audio=False, device=DEVICE_GPU)
def score_audiobox(
    mp3_path: Path, meta: SongMeta | None = None, audio_data: AudioData | None = None,
    config: PipelineConfig | None = None, shared_data: SharedScorerData | None = None,
) -> AudioBoxScore:
    """Score audio quality using Meta's AudioBox Aesthetics model."""
    effective_config = config if isinstance(config, PipelineConfig) else PipelineConfig()
    predictor = _get_predictor(device=effective_config.device)
    result = predictor.forward([{"path": str(mp3_path)}])  # type: ignore[union-attr]

    scores = result[0]
    log.info(
        "AudioBox: CE=%.1f CU=%.1f PC=%.1f PQ=%.1f",
        scores["CE"], scores["CU"], scores["PC"], scores["PQ"],
    )

    return AudioBoxScore(
        content_enjoyment=round(scores["CE"], 2),
        content_understanding=round(scores["CU"], 2),
        production_complexity=round(scores["PC"], 2),
        production_quality=round(scores["PQ"], 2),
    )


def _get_predictor(
    device: str = "cpu",
) -> object:
    """Return a cached AudioBox predictor, loading on first use.

    Uses a threading lock around CUDA_VISIBLE_DEVICES mutation
    to prevent race conditions with concurrent scorers.
    """
    from audiobox_aesthetics.infer import AesPredictor

    global _predictor, _predictor_device
    with _predictor_lock:
        if _predictor_device != device:
            if device == "cpu":
                log.info("Loading AudioBox Aesthetics model on CPU...")
                with _force_cpu_env():
                    _predictor = AesPredictor(checkpoint_pth="default")
            else:
                log.info("Loading AudioBox Aesthetics model on %s...", device)
                _predictor = AesPredictor(checkpoint_pth="default")
            _predictor_device = device
    return _predictor

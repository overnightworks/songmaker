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
from songmaker_cli.scoring.models import AudioBoxScore
from songmaker_cli.scoring.pipeline import AudioData, PipelineConfig, register

log = logging.getLogger(__name__)

_predictor_cache: dict[str, object] = {}
_cpu_env_lock = threading.Lock()


@contextmanager
def _force_cpu_env() -> Iterator[None]:
    """Temporarily hide CUDA devices to force CPU model loading.

    Must be used under _cpu_env_lock for thread safety.
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


@register("audiobox", needs_audio=False)
def score_audiobox(
    mp3_path: Path, meta: SongMeta | None = None, audio_data: AudioData | None = None,
    config: PipelineConfig | None = None,
) -> AudioBoxScore:
    """Score audio quality using Meta's AudioBox Aesthetics model."""
    predictor = _get_predictor()
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
    cache: dict[str, object] | None = None,
) -> object:
    """Return a cached AudioBox predictor, loading on first use.

    Uses a threading lock around CUDA_VISIBLE_DEVICES mutation
    to prevent race conditions with concurrent scorers.
    """
    from audiobox_aesthetics.infer import AesPredictor

    if cache is None:
        cache = _predictor_cache
    if "default" not in cache:
        log.info("Loading AudioBox Aesthetics model on CPU...")
        with _cpu_env_lock, _force_cpu_env():
            cache["default"] = AesPredictor(checkpoint_pth="default")
    return cache["default"]

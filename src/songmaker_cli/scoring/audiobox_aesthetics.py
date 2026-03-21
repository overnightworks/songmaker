"""AudioBox Aesthetics scorer — Meta's audio quality prediction model.

Scores audio on four dimensions (1-10 each):
- Content Enjoyment (CE): how enjoyable is the content
- Content Understanding (CU): how understandable is the content
- Production Complexity (PC): how complex is the production
- Production Quality (PQ): how well-produced is the audio
"""

from __future__ import annotations

import logging
from pathlib import Path

from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import AudioBoxScore
from songmaker_cli.scoring.pipeline import AudioData, PipelineConfig, register

log = logging.getLogger(__name__)

_predictor_cache: dict[str, object] = {}


@register("audiobox")
def score_audiobox(
    mp3_path: Path, meta: SongMeta | None = None, audio_data: AudioData | None = None,
    config: PipelineConfig | None = None,
) -> AudioBoxScore:
    """Score audio quality using Meta's AudioBox Aesthetics model.

    Note: audio_data is unused — AudioBox requires a file path, not a numpy array.
    The parameter exists to satisfy the scorer function signature.
    """
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
    """Return a cached AudioBox predictor, loading on first use."""
    from audiobox_aesthetics.infer import AesPredictor

    if cache is None:
        cache = _predictor_cache
    if "default" not in cache:
        log.info("Loading AudioBox Aesthetics model...")
        cache["default"] = AesPredictor(checkpoint_pth="default")
    return cache["default"]

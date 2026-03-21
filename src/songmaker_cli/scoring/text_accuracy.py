"""Text accuracy scorer — Whisper transcription vs intended lyrics."""

from __future__ import annotations

import logging
import re
import threading
from difflib import SequenceMatcher
from pathlib import Path

from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import TextAccuracyScore
from songmaker_cli.scoring.pipeline import AudioData, PipelineConfig, register

log = logging.getLogger(__name__)

_whisper_model_cache: dict[str, object] = {}
_whisper_cache_lock = threading.Lock()


@register("text_accuracy", needs_audio=False)
def score_text_accuracy(
    mp3_path: Path, meta: SongMeta | None = None, audio_data: AudioData | None = None,
    config: PipelineConfig | None = None,
) -> TextAccuracyScore:
    """Transcribe with Whisper and compare to intended lyrics.

    Note: audio_data is unused — Whisper requires a file path, not a numpy array.
    The parameter exists to satisfy the scorer function signature.
    """
    if meta is None or not meta.lyrics:
        raise ValueError("No lyrics metadata — cannot score text accuracy")

    effective_config = config if isinstance(config, PipelineConfig) else PipelineConfig()
    whisper_size = effective_config.whisper_model
    device = effective_config.device
    language = meta.generation_params.get("language", "en")
    model = _get_whisper_model(whisper_size, device=device)
    transcribed, segments = _transcribe(mp3_path, language, model)

    intended_lines = tuple(
        line.strip() for line in meta.lyrics.splitlines()
        if line.strip() and not line.strip().startswith("[")
    )
    trans_lines = tuple(
        s.get("text", "").strip() for s in segments if s.get("text", "").strip()
    )

    ratio = _per_line_accuracy(intended_lines, trans_lines)

    log.info("Text accuracy: %.0f%% (%d intended, %d transcribed)",
             ratio * 100, len(intended_lines), len(trans_lines))

    return TextAccuracyScore(
        similarity_ratio=round(ratio, 3),
        intended_line_texts=intended_lines,
        transcribed_line_texts=trans_lines,
    )


def _per_line_accuracy(
    intended: tuple[str, ...], transcribed: tuple[str, ...],
) -> float:
    """Compute average best-match similarity per intended line using greedy alignment.

    Each transcribed line can only match one intended line (consumed after use).
    This prevents a single good transcribed line from inflating scores for
    multiple intended lines.
    """
    if not intended or not transcribed:
        return 0.0

    clean_intended = [clean_lyrics(line) for line in intended]
    clean_intended = [c for c in clean_intended if c]
    if not clean_intended:
        return 0.0

    candidates = [clean_lyrics(t) for t in transcribed]
    candidates = [c for c in candidates if c]
    if not candidates:
        return 0.0

    line_scores: list[float] = []
    for line in clean_intended:
        if not candidates:
            line_scores.append(0.0)
            continue
        best_idx, best_ratio = max(
            ((i, SequenceMatcher(None, line, c).ratio()) for i, c in enumerate(candidates)),
            key=lambda pair: pair[1],
        )
        line_scores.append(best_ratio)
        candidates.pop(best_idx)

    return sum(line_scores) / len(line_scores)


def clean_lyrics(text: str) -> str:
    """Strip section tags and normalize whitespace for comparison."""
    text = re.sub(r"\[.*?\]", "", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _get_whisper_model(
    model_size: str,
    device: str = "cpu",
    cache: dict[str, object] | None = None,
) -> object:
    """Return a cached Whisper model, loading it on first use."""
    import whisper

    if cache is None:
        cache = _whisper_model_cache
    cache_key = f"{model_size}:{device}"
    with _whisper_cache_lock:
        if cache_key not in cache:
            log.info("Loading Whisper model (%s) on %s...", model_size, device)
            cache[cache_key] = whisper.load_model(model_size, device=device)
    return cache[cache_key]


def _transcribe(
    mp3_path: Path, language: str, model: object,
) -> tuple[str, list[dict]]:
    log.info("Transcribing %s...", mp3_path.name)
    result = model.transcribe(  # type: ignore[union-attr]
        str(mp3_path), language=language, fp16=False,
        condition_on_previous_text=False,
    )
    return result["text"].strip(), result.get("segments", [])

"""Text accuracy scorer — Whisper transcription vs intended lyrics."""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from pathlib import Path

from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import TextAccuracyScore
from songmaker_cli.scoring.pipeline import AudioData, PipelineConfig, register

log = logging.getLogger(__name__)

_whisper_model_cache: dict[str, object] = {}



@register("text_accuracy")
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
    language = meta.generation_params.get("language", "en")
    model = _get_whisper_model(whisper_size)
    transcribed, segments = _transcribe(mp3_path, language, model)

    clean_intended = clean_lyrics(meta.lyrics)
    clean_transcribed = clean_lyrics(transcribed)
    ratio = SequenceMatcher(None, clean_intended, clean_transcribed).ratio()

    intended_lines = tuple(
        line.strip() for line in meta.lyrics.splitlines()
        if line.strip() and not line.strip().startswith("[")
    )
    trans_lines = tuple(
        s.get("text", "").strip() for s in segments if s.get("text", "").strip()
    )

    log.info("Text accuracy: %.0f%% (%d intended, %d transcribed)",
             ratio * 100, len(intended_lines), len(trans_lines))

    return TextAccuracyScore(
        similarity_ratio=round(ratio, 3),
        intended_line_texts=intended_lines,
        transcribed_line_texts=trans_lines,
    )


def clean_lyrics(text: str) -> str:
    """Strip section tags and normalize whitespace for comparison."""
    text = re.sub(r"\[.*?\]", "", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _get_whisper_model(
    model_size: str,
    cache: dict[str, object] | None = None,
) -> object:
    """Return a cached Whisper model, loading it on first use."""
    import whisper

    if cache is None:
        cache = _whisper_model_cache
    if model_size not in cache:
        log.info("Loading Whisper model (%s) on CPU...", model_size)
        cache[model_size] = whisper.load_model(model_size, device="cpu")
    return cache[model_size]


def _transcribe(
    mp3_path: Path, language: str, model: object,
) -> tuple[str, list[dict]]:
    log.info("Transcribing %s...", mp3_path.name)
    result = model.transcribe(  # type: ignore[union-attr]
        str(mp3_path), language=language, fp16=False,
        condition_on_previous_text=False,
    )
    return result["text"].strip(), result.get("segments", [])

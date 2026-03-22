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

    ratio = _word_level_accuracy(intended_lines, trans_lines)

    log.info("Text accuracy: %.0f%% (%d intended, %d transcribed)",
             ratio * 100, len(intended_lines), len(trans_lines))

    # Save transcription alongside MP3 for player diff view
    whisper_path = mp3_path.with_suffix(".whisper")
    whisper_path.write_text("\n".join(trans_lines), encoding="utf-8")
    log.info("Whisper transcription saved: %s", whisper_path.name)

    return TextAccuracyScore(
        similarity_ratio=round(ratio, 3),
        intended_line_texts=intended_lines,
        transcribed_line_texts=trans_lines,
    )


_VOCALIZATION_PATTERN = re.compile(
    r"^(oh|ah|la|na|da|hey|yeah|oo+h?|hm+|mm+|wo+h?|eh)[\s,]*$",
    re.IGNORECASE,
)


def _is_vocalization(line: str) -> bool:
    """Check if a line is only non-lyric vocalizations (oh, ah, la la, etc.)."""
    words = clean_lyrics(line).split()
    return all(_VOCALIZATION_PATTERN.match(w) for w in words) if words else True


def _word_level_accuracy(
    intended: tuple[str, ...], transcribed: tuple[str, ...],
) -> float:
    """Compare intended vs transcribed at word level.

    Joins all lines into word sequences, filtering out vocalizations
    (oh, ah, la la). Ignores line boundaries entirely — only words matter.
    This handles Whisper merging/splitting lines and intro/outro vocalizations.
    """
    if not intended or not transcribed:
        return 0.0

    intended_words = " ".join(
        clean_lyrics(line) for line in intended if not _is_vocalization(line)
    ).split()
    trans_words = " ".join(
        clean_lyrics(t) for t in transcribed if not _is_vocalization(t)
    ).split()

    if not intended_words:
        return 0.0
    if not trans_words:
        return 0.0

    # Two comparisons — take the higher score:
    # 1. Character-level (handles compound words like streetlights/street lights)
    # 2. Word-level (handles partial transcriptions where Whisper misses sections)
    char_ratio = SequenceMatcher(None, "".join(intended_words), "".join(trans_words)).ratio()
    word_ratio = SequenceMatcher(None, intended_words, trans_words).ratio()
    return max(char_ratio, word_ratio)


def _per_line_accuracy(
    intended: tuple[str, ...], transcribed: tuple[str, ...],
) -> float:
    """Compute average best-match similarity per intended line.

    Each intended line finds its best match among ALL transcribed lines
    (no consumption). This handles songs correctly where:
    - Whisper produces fewer segments than intended lines
    - Choruses repeat (same transcribed line matches multiple intended lines)
    - Whisper splits/merges lines differently than the lyrics
    """
    if not intended or not transcribed:
        return 0.0

    clean_intended = [clean_lyrics(line) for line in intended]
    clean_intended = [c for c in clean_intended if c]
    if not clean_intended:
        return 0.0

    clean_trans = [clean_lyrics(t) for t in transcribed]
    clean_trans = [c for c in clean_trans if c]
    if not clean_trans:
        return 0.0

    line_scores: list[float] = []
    for line in clean_intended:
        best_ratio = max(
            SequenceMatcher(None, line, ct).ratio()
            for ct in clean_trans
        )
        line_scores.append(best_ratio)

    return sum(line_scores) / len(line_scores)


def clean_lyrics(text: str) -> str:
    """Strip section tags and normalize for comparison.

    Normalizes contractions, compound words, and whitespace so that
    'streetlights' == 'street lights' and "I'll" == "I" don't
    count as errors.
    """
    text = re.sub(r"\[.*?\]", "", text)
    text = text.lower()
    # Normalize contractions: I'll -> i will, don't -> do not, etc.
    text = re.sub(r"'ll\b", " will", text)
    text = re.sub(r"n't\b", " not", text)
    text = re.sub(r"'re\b", " are", text)
    text = re.sub(r"'ve\b", " have", text)
    text = re.sub(r"'m\b", " am", text)
    text = re.sub(r"'s\b", "", text)  # possessive/is — remove
    # Remove remaining apostrophes and hyphens
    text = text.replace("'", "").replace("-", " ")
    return re.sub(r"\s+", " ", text).strip()


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
        condition_on_previous_text=True,
    )
    return result["text"].strip(), result.get("segments", [])

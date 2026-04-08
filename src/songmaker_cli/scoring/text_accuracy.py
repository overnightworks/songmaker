"""Text accuracy scorer — Whisper transcription vs intended lyrics."""

from __future__ import annotations

import logging
import re
import threading
from difflib import SequenceMatcher
from pathlib import Path

from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import SharedScorerData, TextAccuracyScore
from songmaker_cli.scoring.pipeline import AudioData, PipelineConfig, register

log = logging.getLogger(__name__)

_whisper_model: object | None = None
_whisper_model_key: str | None = None
_whisper_cache_lock = threading.Lock()


def clear_cache() -> None:
    import gc

    global _whisper_model, _whisper_model_key
    with _whisper_cache_lock:
        _whisper_model = None
        _whisper_model_key = None
    gc.collect()
    log.info("Cleared Whisper model cache")


@register("text_accuracy")
def score_text_accuracy(
    mp3_path: Path, meta: SongMeta | None = None, audio_data: AudioData | None = None,
    config: PipelineConfig | None = None, shared_data: SharedScorerData | None = None,
) -> TextAccuracyScore:
    """Transcribe with Whisper and compare to intended lyrics.

    Stores the transcription in shared_data["whisper_text"] so that
    downstream scorers (lyrical_coherence) can access it without
    going through the filesystem.
    """
    if meta is None or not meta.lyrics:
        raise ValueError("No lyrics metadata — cannot score text accuracy")

    effective_config = config if isinstance(config, PipelineConfig) else PipelineConfig()
    whisper_size = effective_config.whisper_model
    device = effective_config.whisper_device or effective_config.device
    language = meta.generation_params.get("language") or None
    model = _get_whisper_model(whisper_size, device=device)

    intended_lines = tuple(
        line.strip() for line in meta.lyrics.splitlines()
        if line.strip() and not line.strip().startswith("[")
    )

    initial_prompt = " ".join(intended_lines)
    transcribed, segments, detected_language = _transcribe(
        mp3_path, language, model, initial_prompt,
    )

    trans_lines = tuple(
        s.get("text", "").strip() for s in segments if s.get("text", "").strip()
    )
    ratio = _word_level_accuracy(intended_lines, trans_lines)

    log.info("Text accuracy: %.0f%% (%d intended, %d transcribed)",
             ratio * 100, len(intended_lines), len(trans_lines))

    if _is_hallucination(trans_lines):
        log.warning("Whisper hallucination detected — no real vocals in %s", mp3_path.name)
        trans_lines = ()

    if shared_data is not None:
        shared_data.whisper_text = "\n".join(trans_lines)

    return TextAccuracyScore(
        similarity_ratio=round(ratio, 3),
        intended_line_texts=intended_lines,
        transcribed_line_texts=trans_lines,
        detected_language=detected_language,
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
    """Measure what fraction of intended lyrics were correctly sung.

    Joins all lines into word sequences, filtering out vocalizations.
    Uses SequenceMatcher to find matching blocks, then calculates
    coverage of intended words. Extra sung words (ad-libs, improvisation)
    are NOT penalized — only missing or misheard intended words count.
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

    # Count how many intended words were found in the transcription
    # (order-preserving match via SequenceMatcher)
    sm = SequenceMatcher(None, intended_words, trans_words)
    matched_intended = sum(size for _, _, size in sm.get_matching_blocks())

    return matched_intended / len(intended_words)


_HALLUCINATION_PHRASES = frozenset({
    "thank you", "thanks for watching", "goodbye", "you're welcome",
    "please subscribe", "like and subscribe", "music playing",
    "music", "applause", "laughter",
})


def _is_hallucination(lines: tuple[str, ...]) -> bool:
    """Detect Whisper hallucinations — repeated filler phrases with no real content."""
    if len(lines) < 3:
        return False
    cleaned = [clean_lyrics(line) for line in lines if clean_lyrics(line)]
    if not cleaned:
        return True
    from songmaker_cli.constants import (
        HALLUCINATION_MAX_UNIQUE,
        HALLUCINATION_MIN_LINES,
        HALLUCINATION_PHRASE_RATIO,
    )

    unique = set(cleaned)
    if len(unique) <= HALLUCINATION_MAX_UNIQUE and len(cleaned) >= HALLUCINATION_MIN_LINES:
        return True
    hallucinated = sum(1 for c in cleaned if c in _HALLUCINATION_PHRASES)
    return hallucinated > len(cleaned) * HALLUCINATION_PHRASE_RATIO



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
    # Remove remaining apostrophes, hyphens, and punctuation
    text = text.replace("'", "").replace("-", " ")
    text = re.sub(r"[,.\?!;:\"()—]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _get_whisper_model(
    model_size: str,
    device: str = "cpu",
) -> object:
    from faster_whisper import WhisperModel

    from songmaker_cli.constants import WHISPER_COMPUTE_TYPE

    global _whisper_model, _whisper_model_key
    cache_key = f"{model_size}:{device}"
    with _whisper_cache_lock:
        if _whisper_model_key != cache_key:
            log.info("Loading Whisper model (%s) on %s...", model_size, device)
            _whisper_model = WhisperModel(
                model_size, device=device, compute_type=WHISPER_COMPUTE_TYPE,
            )
            _whisper_model_key = cache_key
    return _whisper_model


def _transcribe(
    mp3_path: Path, language: str | None, model: object,
    initial_prompt: str | None = None,
) -> tuple[str, list[dict], str | None]:
    from songmaker_cli.constants import WHISPER_BEAM_SIZE, WHISPER_TEMPERATURE

    log.info("Transcribing %s...", mp3_path.name)
    kwargs: dict[str, object] = {
        "language": language,
        "condition_on_previous_text": False,
        "beam_size": WHISPER_BEAM_SIZE,
        "temperature": WHISPER_TEMPERATURE,
    }
    if initial_prompt:
        kwargs["initial_prompt"] = initial_prompt
    segments_gen, info = model.transcribe(str(mp3_path), **kwargs)  # type: ignore[union-attr]
    segments = [{"text": seg.text} for seg in segments_gen]
    full_text = " ".join(seg["text"].strip() for seg in segments if seg["text"].strip())
    detected_language = getattr(info, "language", None)
    if detected_language:
        log.info("Detected language: %s", detected_language)
    return full_text, segments, detected_language

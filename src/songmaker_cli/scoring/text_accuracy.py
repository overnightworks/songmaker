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

    intended_lines = tuple(
        line.strip() for line in meta.lyrics.splitlines()
        if line.strip() and not line.strip().startswith("[")
    )

    initial_prompt = _build_vocabulary_prompt(intended_lines)
    transcribed, segments = _transcribe(mp3_path, language, model, initial_prompt)

    trans_lines = tuple(
        s.get("text", "").strip() for s in segments if s.get("text", "").strip()
    )
    ratio = _word_level_accuracy(intended_lines, trans_lines)

    log.info("Text accuracy: %.0f%% (%d intended, %d transcribed)",
             ratio * 100, len(intended_lines), len(trans_lines))

    # Detect Whisper hallucinations (repeated "Thank you", "Goodbye", etc.)
    if _is_hallucination(trans_lines):
        log.warning("Whisper hallucination detected — no real vocals in %s", mp3_path.name)
        trans_lines = ()

    # Save transcription with confidence: "0.85|text" per line
    whisper_path = mp3_path.with_suffix(".whisper")
    _save_whisper_with_confidence(whisper_path, segments)
    log.info("Whisper transcription saved: %s", whisper_path.name)

    return TextAccuracyScore(
        similarity_ratio=round(ratio, 3),
        intended_line_texts=intended_lines,
        transcribed_line_texts=trans_lines,
    )


def _build_vocabulary_prompt(lines: tuple[str, ...] | list[str]) -> str | None:
    """Build a Whisper initial_prompt from lyrics as vocabulary hints.

    Uses unique uncommon words rather than full lyrics — Whisper treats
    initial_prompt as "previously spoken text" so full lyrics cause it
    to skip matching lines.
    """
    if not lines:
        return None
    all_words = " ".join(lines).split()
    seen: set[str] = set()
    unique: list[str] = []
    for word in all_words:
        lower = word.lower().strip(".,!?;:")
        if lower not in seen and len(lower) > 3:
            seen.add(lower)
            unique.append(word)
    return ", ".join(unique[:50]) if unique else None


def _segment_confidence(segment: dict) -> float:
    """Derive a 0-1 confidence score from Whisper segment metadata.

    Uses avg_logprob (higher = more confident) and no_speech_prob (lower = more
    likely speech). Combined via: sigmoid(logprob) * (1 - no_speech).
    """
    import math

    avg_logprob = segment.get("avg_logprob", -1.0)
    no_speech = segment.get("no_speech_prob", 0.0)
    # avg_logprob is typically -0.2 (good) to -1.5 (bad)
    # Map to 0-1 via sigmoid shifted so -0.5 -> ~0.5
    sig = 1.0 / (1.0 + math.exp(-(avg_logprob + 0.5) * 4))
    return round(sig * (1.0 - no_speech), 2)


def _save_whisper_with_confidence(whisper_path: Path, segments: list[dict]) -> None:
    """Save Whisper transcription with per-line confidence scores.

    Format: "0.85|The actual transcribed text" per line.
    """
    lines = []
    for s in segments:
        text = s.get("text", "").strip()
        if not text:
            continue
        conf = _segment_confidence(s)
        lines.append(f"{conf}|{text}")
    whisper_path.write_text("\n".join(lines), encoding="utf-8")


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
    unique = set(cleaned)
    # If >80% of lines are the same phrase, it's hallucination
    if len(unique) <= 2 and len(cleaned) >= 5:
        return True
    # If most lines match known hallucination phrases
    hallucinated = sum(1 for c in cleaned if c in _HALLUCINATION_PHRASES)
    return hallucinated > len(cleaned) * 0.5


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
    # Remove remaining apostrophes, hyphens, and punctuation
    text = text.replace("'", "").replace("-", " ")
    text = re.sub(r"[,.\?!;:\"()—]", "", text)
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


def _vocal_preprocess(mp3_path: Path) -> str:
    """Pre-emphasis + vocal frequency boost to help Whisper hear vocals over music.

    Returns path to a temporary 16kHz mono WAV optimized for speech recognition.
    """
    import tempfile

    import librosa
    import numpy as np
    import soundfile as sf
    from scipy.signal import butter, sosfilt

    y, sr = librosa.load(str(mp3_path), sr=16000, mono=True)
    # Pre-emphasis: boost higher frequencies where consonants live
    y = np.append(y[0], y[1:] - 0.97 * y[:-1])
    # Bandpass vocal range and boost by +6dB
    sos = butter(4, [200, 5000], btype="band", fs=sr, output="sos")
    vocals = sosfilt(sos, y)
    y = y + vocals * (10 ** (6 / 20) - 1)
    peak = np.max(np.abs(y))
    if peak > 1e-10:
        y = y / peak * 0.95
    tmp_path = tempfile.mktemp(suffix=".wav")
    sf.write(tmp_path, y, sr)
    return tmp_path


def _transcribe(
    mp3_path: Path, language: str, model: object,
    initial_prompt: str | None = None,
) -> tuple[str, list[dict]]:
    log.info("Transcribing %s...", mp3_path.name)
    kwargs: dict[str, object] = {
        "language": language, "fp16": True,
        "condition_on_previous_text": False,
        "word_timestamps": True,
        "beam_size": 5,
        "best_of": 5,
        "temperature": 0,
        "compression_ratio_threshold": 1.8,
        "logprob_threshold": -0.5,
    }
    if initial_prompt:
        kwargs["initial_prompt"] = initial_prompt
    result = model.transcribe(str(mp3_path), **kwargs)  # type: ignore[union-attr]
    return result["text"].strip(), result.get("segments", [])

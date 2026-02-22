"""Automated vocal phrase validation for DiffSinger output.

Runs checks on generated audio to catch issues before a human
listens. Produces a structured report with pass/warn/fail per phrase.

Checks:
  - Duration: Does the phrase fit its beat window?
  - Silence: Are there unexpected silent gaps mid-phrase?
  - Clipping: Is the audio distorted?
  - Loudness: Is the RMS consistent across phrases?
  - Phoneme coverage: Did G2P produce phonemes for every note?
  - Pronunciation: Does Whisper STT match expected lyrics?
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

from .models import VocalPhrase
from .phonemizer import phonemize_word

logger = logging.getLogger(__name__)

SAMPLE_RATE = 44100


@dataclass
class PhraseCheck:
    """Result of validating a single phrase."""

    phrase_id: str
    duration_sec: float
    window_sec: float  # max allowed duration from beat layout
    issues: list[str] = field(default_factory=list)
    whisper_similarity: float | None = None  # 0.0-1.0, set by pronunciation check
    whisper_transcript: str | None = None

    @property
    def status(self) -> str:
        if any(i.startswith("FAIL") for i in self.issues):
            return "FAIL"
        if self.issues:
            return "WARN"
        return "OK"


@dataclass
class ValidationReport:
    """Full report across all phrases."""

    checks: list[PhraseCheck] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return all(c.status == "OK" for c in self.checks)

    def summary(self) -> str:
        """Human-readable summary with Whisper scores."""
        lines = ["\n=== Vocal Validation Report ===\n"]
        for c in self.checks:
            icon = {"OK": "[OK]", "WARN": "[!!]", "FAIL": "[XX]"}[c.status]
            sim_str = f"{c.whisper_similarity:.0%}" if c.whisper_similarity is not None else "n/a"
            lines.append(
                f"  {icon} {c.phrase_id}: {c.duration_sec:.2f}s / "
                f"{c.window_sec:.2f}s window | Whisper: {sim_str}"
            )
            for issue in c.issues:
                lines.append(f"        {issue}")
        ok = sum(1 for c in self.checks if c.status == "OK")
        warn = sum(1 for c in self.checks if c.status == "WARN")
        fail = sum(1 for c in self.checks if c.status == "FAIL")
        lines.append(f"\n  Total: {ok} OK, {warn} warnings, {fail} failures out of {len(self.checks)} phrases")

        # Average Whisper score
        sims = [c.whisper_similarity for c in self.checks if c.whisper_similarity is not None]
        if sims:
            avg = sum(sims) / len(sims)
            lines.append(f"  Average Whisper similarity: {avg:.0%}")

        return "\n".join(lines)


def check_duration(samples: np.ndarray, window_sec: float) -> list[str]:
    """Check if audio fits its beat window."""
    duration = len(samples) / SAMPLE_RATE
    issues = []
    if duration > window_sec:
        overshoot = duration - window_sec
        issues.append(f"WARN: overflows beat window by {overshoot:.2f}s ({duration:.2f}s > {window_sec:.2f}s)")
    elif duration < window_sec * 0.3:
        issues.append(f"WARN: suspiciously short ({duration:.2f}s for {window_sec:.2f}s window)")
    return issues


def check_silence(samples: np.ndarray, threshold: float = 0.005, min_gap_sec: float = 0.5) -> list[str]:
    """Detect unexpected silence gaps within a phrase.

    Args:
        samples: Audio samples.
        threshold: RMS threshold below which audio is considered silent.
        min_gap_sec: Minimum gap length (seconds) to flag.
    """
    issues = []
    window = int(0.05 * SAMPLE_RATE)  # 50ms analysis windows
    if len(samples) < window * 3:
        return issues

    # Skip first/last 200ms (natural attack/release)
    skip = int(0.2 * SAMPLE_RATE)
    if len(samples) < skip * 2 + window:
        return issues

    # Compute RMS in windows
    inner = samples[skip:-skip]
    n_windows = len(inner) // window
    if n_windows < 2:
        return issues

    silent_start = None
    for i in range(n_windows):
        chunk = inner[i * window:(i + 1) * window]
        rms = np.sqrt(np.mean(chunk ** 2))

        if rms < threshold:
            if silent_start is None:
                silent_start = i
        else:
            if silent_start is not None:
                gap_windows = i - silent_start
                gap_sec = gap_windows * window / SAMPLE_RATE
                if gap_sec >= min_gap_sec:
                    gap_time = (skip + silent_start * window) / SAMPLE_RATE
                    issues.append(f"WARN: {gap_sec:.1f}s silence gap at {gap_time:.1f}s")
                silent_start = None

    return issues


def check_clipping(samples: np.ndarray, threshold: float = 0.99) -> list[str]:
    """Detect clipping (consecutive samples at max amplitude)."""
    issues = []
    abs_samples = np.abs(samples)
    clipped = abs_samples >= threshold
    if not clipped.any():
        return issues

    # Count consecutive clipped samples
    runs = np.diff(np.where(np.concatenate(([clipped[0]], clipped[:-1] != clipped[1:], [True])))[0])[::2]
    if len(runs) > 0:
        longest_run = runs.max()
        if longest_run > 10:  # More than ~0.2ms of clipping
            total_clipped = clipped.sum()
            pct = total_clipped / len(samples) * 100
            issues.append(f"WARN: clipping detected ({total_clipped} samples, {pct:.2f}%)")

    return issues


def check_loudness(samples: np.ndarray) -> tuple[float, list[str]]:
    """Measure RMS loudness and flag extremes.

    Returns:
        Tuple of (rms_db, issues).
    """
    issues = []
    rms = np.sqrt(np.mean(samples ** 2))
    if rms < 1e-10:
        return -100.0, ["FAIL: completely silent (no audio generated)"]

    rms_db = 20 * np.log10(rms)

    if rms_db < -40:
        issues.append(f"WARN: very quiet ({rms_db:.1f} dB RMS)")
    elif rms_db > -3:
        issues.append(f"WARN: very loud ({rms_db:.1f} dB RMS), may distort in mix")

    return rms_db, issues


def check_phonemes(phrase: VocalPhrase) -> list[str]:
    """Verify G2P produces phonemes for every non-rest note."""
    issues = []
    for i, note in enumerate(phrase.notes):
        if note.is_rest:
            continue
        result = phonemize_word(note.lyric)
        if not result.phonemes:
            issues.append(f"FAIL: no phonemes for note {i} lyric='{note.lyric}'")
    return issues


def check_beat_budgets(
    phrases: list[tuple[VocalPhrase, float]],
    total_beats: float,
    tolerance_beats: float = 0.5,
) -> list[str]:
    """Verify every phrase's notes fit within its beat window.

    This is a pure-math check - no audio generation needed. It should
    run instantly and catch composition errors before any slow processing.

    Args:
        phrases: List of (VocalPhrase, start_beat) tuples.
        total_beats: Total song length in beats.
        tolerance_beats: Small buffer to allow for head/tail padding.

    Returns:
        List of error messages. Empty list = all phrases fit.

    Raises:
        ValueError: If any phrase overflows its beat window.
    """
    errors = []

    for i, (phrase, beat) in enumerate(phrases):
        # Calculate beat window
        if i + 1 < len(phrases):
            window_beats = phrases[i + 1][1] - beat
        else:
            window_beats = total_beats - beat

        # Sum note durations
        note_beats = sum(n.duration_beats for n in phrase.notes)

        if note_beats > window_beats + tolerance_beats:
            overflow = note_beats - window_beats
            errors.append(
                f"  {phrase.phrase_id}: {note_beats:.1f} beats of notes in "
                f"{window_beats:.0f}-beat window (overflow: {overflow:.1f} beats)"
            )

    if errors:
        header = f"\nBeat budget check FAILED - {len(errors)} phrase(s) overflow:\n"
        detail = "\n".join(errors)
        raise ValueError(header + detail)


def validate_phrase(
    phrase: VocalPhrase,
    samples: np.ndarray,
    window_sec: float,
) -> PhraseCheck:
    """Run all validation checks on a single phrase.

    Args:
        phrase: The vocal phrase definition.
        samples: Generated audio samples (float32).
        window_sec: Maximum allowed duration from beat layout.
    """
    duration = len(samples) / SAMPLE_RATE
    check = PhraseCheck(
        phrase_id=phrase.phrase_id,
        duration_sec=duration,
        window_sec=window_sec,
    )

    check.issues.extend(check_duration(samples, window_sec))
    check.issues.extend(check_silence(samples))
    check.issues.extend(check_clipping(samples))
    _rms_db, loudness_issues = check_loudness(samples)
    check.issues.extend(loudness_issues)
    check.issues.extend(check_phonemes(phrase))
    pron = check_pronunciation(phrase, samples)
    check.issues.extend(pron.issues)
    check.whisper_similarity = pron.similarity
    check.whisper_transcript = pron.transcript

    return check


def validate_all(
    phrases_with_audio: list[tuple[VocalPhrase, np.ndarray, float]],
) -> ValidationReport:
    """Validate all phrases and produce a report.

    Args:
        phrases_with_audio: List of (phrase, samples, window_sec) tuples.

    Returns:
        ValidationReport with all checks.
    """
    report = ValidationReport()

    rms_values = []
    for phrase, samples, window_sec in phrases_with_audio:
        check = validate_phrase(phrase, samples, window_sec)
        report.checks.append(check)

        # Collect RMS for cross-phrase consistency check
        rms = np.sqrt(np.mean(samples ** 2))
        if rms > 1e-10:
            rms_values.append((phrase.phrase_id, 20 * np.log10(rms)))

    # Cross-phrase loudness consistency
    if len(rms_values) >= 2:
        db_vals = [db for _, db in rms_values]
        spread = max(db_vals) - min(db_vals)
        if spread > 12:
            quietest = min(rms_values, key=lambda x: x[1])
            loudest = max(rms_values, key=lambda x: x[1])
            # Add warning to the quietest phrase
            for check in report.checks:
                if check.phrase_id == quietest[0]:
                    check.issues.append(
                        f"WARN: loudness spread {spread:.1f}dB across phrases "
                        f"(quietest={quietest[1]:.1f}dB, loudest={loudest[1]:.1f}dB)"
                    )
                    break

    return report


# ── Whisper pronunciation validation ────────────────────────────────

WHISPER_MODEL_SIZE = "small.en"  # "tiny.en" (fast, inaccurate) or "small.en" (6x larger, honest scores)

_whisper_model = None
_whisper_model_name = None


def _get_whisper_model():
    """Lazy-load Whisper model (first call downloads + loads)."""
    global _whisper_model, _whisper_model_name
    if _whisper_model is None or _whisper_model_name != WHISPER_MODEL_SIZE:
        try:
            import whisper
        except ImportError:
            logger.warning("openai-whisper not installed - skipping pronunciation check")
            return None
        logger.info("Loading Whisper %s model...", WHISPER_MODEL_SIZE)
        _whisper_model = whisper.load_model(WHISPER_MODEL_SIZE)
        _whisper_model_name = WHISPER_MODEL_SIZE
    return _whisper_model


def _extract_lyrics(phrase: VocalPhrase) -> list[str]:
    """Extract expected words from phrase notes (skip rests)."""
    return [n.lyric.lower().strip() for n in phrase.notes if not n.is_rest and n.lyric.strip()]


@dataclass
class PronunciationResult:
    """Result of Whisper pronunciation check."""

    similarity: float | None  # 0.0-1.0, None if skipped
    transcript: str | None  # What Whisper heard
    issues: list[str]


def _word_error_rate(reference: list[str], hypothesis: list[str]) -> float:
    """Compute Word Error Rate using Levenshtein distance on word lists.

    WER = (substitutions + deletions + insertions) / len(reference)
    Returns 0.0 (perfect) to 1.0+ (completely wrong; can exceed 1.0 if
    hypothesis is longer than reference due to insertions).
    """
    n = len(reference)
    m = len(hypothesis)
    if n == 0:
        return 0.0 if m == 0 else 1.0

    # DP table for edit distance
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if reference[i - 1] == hypothesis[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(
                    dp[i - 1][j],      # deletion
                    dp[i][j - 1],      # insertion
                    dp[i - 1][j - 1],  # substitution
                )

    return dp[n][m] / n


def _find_wrong_words(reference: list[str], hypothesis: list[str]) -> list[str]:
    """Find specific word-level mismatches using SequenceMatcher for alignment."""
    mismatched = []
    matcher = SequenceMatcher(None, reference, hypothesis)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            mismatched.append(f"'{' '.join(reference[i1:i2])}'->'{' '.join(hypothesis[j1:j2])}'")
        elif tag == "delete":
            mismatched.append(f"'{' '.join(reference[i1:i2])}'->MISSING")
        elif tag == "insert":
            mismatched.append(f"EXTRA->'{' '.join(hypothesis[j1:j2])}'")
    return mismatched


def check_pronunciation(
    phrase: VocalPhrase,
    samples: np.ndarray,
) -> PronunciationResult:
    """Transcribe audio with Whisper and score using Word Error Rate.

    Uses WER (stricter than character-level SequenceMatcher):
    - Counts wrong/missing/extra words
    - 3 wrong words out of 10 = 70% accuracy, not 90%+
    - Score = 1 - WER, clamped to [0, 1]

    Args:
        phrase: The vocal phrase with expected lyrics.
        samples: Generated audio (float32, 44100 Hz).

    Returns:
        PronunciationResult with word accuracy score, transcript, and issues.
    """
    model = _get_whisper_model()
    if model is None:
        return PronunciationResult(similarity=None, transcript=None, issues=[])

    expected_words = _extract_lyrics(phrase)
    if not expected_words:
        return PronunciationResult(similarity=None, transcript=None, issues=[])

    expected_text = " ".join(expected_words)

    # Whisper needs a WAV file on disk
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        sf.write(str(tmp_path), samples, SAMPLE_RATE)
        result = model.transcribe(
            str(tmp_path),
            language="en",
            fp16=False,
            condition_on_previous_text=False,
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    transcribed = result["text"].strip().lower()
    # Clean punctuation
    transcribed_clean = "".join(c if c.isalnum() or c == " " else "" for c in transcribed)
    transcribed_words = transcribed_clean.split()

    # Word Error Rate (strict word-level metric)
    wer = _word_error_rate(expected_words, transcribed_words)
    word_accuracy = max(0.0, 1.0 - wer)  # clamp to [0, 1]

    issues: list[str] = []
    if word_accuracy < 0.5:
        issues.append(
            f"WARN: pronunciation mismatch (WER) - expected \"{expected_text}\" "
            f"but heard \"{transcribed_clean}\" (word accuracy: {word_accuracy:.0%})"
        )
    elif word_accuracy < 0.8:
        wrong = _find_wrong_words(expected_words, transcribed_words)
        if wrong:
            issues.append(
                f"WARN: unclear words - {', '.join(wrong)} "
                f"(word accuracy: {word_accuracy:.0%})"
            )

    return PronunciationResult(
        similarity=word_accuracy,
        transcript=transcribed_clean,
        issues=issues,
    )


# ── Run history for cross-run comparison ────────────────────────────

def save_run(
    report: ValidationReport,
    run_label: str,
    output_dir: str,
    song_name: str = "",
) -> Path:
    """Save validation results to a persistent JSON history file.

    Each call appends a new run entry. The history file lives next to
    the generated audio so it's gitignored with _output/.

    Args:
        report: The ValidationReport from validate_all().
        run_label: Short description of what changed (e.g. "100ms consonants, no RVC").
        output_dir: The _output/<album>/ directory.
        song_name: Optional song identifier for the history filename.

    Returns:
        Path to the history file.
    """
    import json
    from datetime import datetime

    history_dir = Path(output_dir)
    history_dir.mkdir(parents=True, exist_ok=True)
    fname = f"validation_history_{song_name}.json" if song_name else "validation_history.json"
    history_path = history_dir / fname

    # Load existing history
    runs: list[dict] = []
    if history_path.exists():
        try:
            runs = json.loads(history_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            runs = []

    # Build run entry
    phrase_scores = {}
    for c in report.checks:
        phrase_scores[c.phrase_id] = {
            "status": c.status,
            "duration_sec": round(c.duration_sec, 2),
            "window_sec": round(c.window_sec, 2),
            "whisper_similarity": round(c.whisper_similarity, 3) if c.whisper_similarity is not None else None,
            "whisper_transcript": c.whisper_transcript,
            "issues": c.issues,
        }

    sims = [c.whisper_similarity for c in report.checks if c.whisper_similarity is not None]
    avg_sim = round(sum(sims) / len(sims), 3) if sims else None

    run_entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "label": run_label,
        "avg_whisper_similarity": avg_sim,
        "total_phrases": len(report.checks),
        "ok": sum(1 for c in report.checks if c.status == "OK"),
        "warn": sum(1 for c in report.checks if c.status == "WARN"),
        "fail": sum(1 for c in report.checks if c.status == "FAIL"),
        "phrases": phrase_scores,
    }

    runs.append(run_entry)
    history_path.write_text(json.dumps(runs, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved validation run '%s' to %s", run_label, history_path)
    return history_path


def compare_runs(
    output_dir: str,
    song_name: str = "",
    last_n: int = 0,
) -> str:
    """Generate a comparison table across saved validation runs.

    Args:
        output_dir: The _output/<album>/ directory.
        song_name: Optional song identifier.
        last_n: Only show the last N runs (0 = all).

    Returns:
        Formatted comparison table string.
    """
    import json

    history_dir = Path(output_dir)
    fname = f"validation_history_{song_name}.json" if song_name else "validation_history.json"
    history_path = history_dir / fname

    if not history_path.exists():
        return "No validation history found."

    try:
        runs = json.loads(history_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "Error reading validation history."

    if not runs:
        return "No runs recorded yet."

    if last_n > 0:
        runs = runs[-last_n:]

    # Collect all phrase IDs across runs (preserve order from latest run)
    all_phrases: list[str] = []
    for run in runs:
        for pid in run["phrases"]:
            if pid not in all_phrases:
                all_phrases.append(pid)

    # Build header
    lines = ["\n=== Validation Run Comparison ===\n"]

    # Run summary row
    run_headers = []
    for i, run in enumerate(runs):
        label = run["label"][:30]
        ts = run["timestamp"][5:16].replace("T", " ")  # MM-DD HH:MM
        run_headers.append(f"#{i+1} {ts}")
        lines.append(f"  #{i+1}: {label}")
        lines.append(f"      {run['timestamp']} | avg: {_fmt_pct(run.get('avg_whisper_similarity'))} | "
                      f"{run['ok']}ok {run['warn']}warn {run['fail']}fail")

    lines.append("")

    # Per-phrase comparison table
    # Column widths
    pid_width = max(len(p) for p in all_phrases) if all_phrases else 10
    col_width = max(len(h) for h in run_headers) + 2

    # Header row
    header = f"  {'Phrase':<{pid_width}}"
    for h in run_headers:
        header += f"  {h:>{col_width}}"
    lines.append(header)
    lines.append("  " + "-" * (pid_width + (col_width + 2) * len(runs)))

    # Data rows
    for pid in all_phrases:
        row = f"  {pid:<{pid_width}}"
        for run in runs:
            pdata = run["phrases"].get(pid)
            if pdata is None:
                row += f"  {'---':>{col_width}}"
            else:
                sim = pdata.get("whisper_similarity")
                row += f"  {_fmt_pct(sim):>{col_width}}"
        lines.append(row)

    # Average row
    lines.append("  " + "-" * (pid_width + (col_width + 2) * len(runs)))
    avg_row = f"  {'AVERAGE':<{pid_width}}"
    for run in runs:
        avg_row += f"  {_fmt_pct(run.get('avg_whisper_similarity')):>{col_width}}"
    lines.append(avg_row)

    return "\n".join(lines)


def _fmt_pct(val: float | None) -> str:
    """Format a 0-1 float as percentage, or 'n/a'."""
    if val is None:
        return "n/a"
    return f"{val:.0%}"

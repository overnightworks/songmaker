"""Automated vocal phrase validation for DiffSinger output.

Runs checks on generated audio to catch issues before a human
listens. Produces a structured report with pass/warn/fail per phrase.

Checks:
  - Duration: Does the phrase fit its beat window?
  - Silence: Are there unexpected silent gaps mid-phrase?
  - Clipping: Is the audio distorted?
  - Loudness: Is the RMS consistent across phrases?
  - Phoneme coverage: Did G2P produce phonemes for every note?
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .models import VocalPhrase
from .phonemizer import phonemize_word

SAMPLE_RATE = 44100


@dataclass
class PhraseCheck:
    """Result of validating a single phrase."""

    phrase_id: str
    duration_sec: float
    window_sec: float  # max allowed duration from beat layout
    issues: list[str] = field(default_factory=list)

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
        """Human-readable summary."""
        lines = ["\n=== Vocal Validation Report ===\n"]
        for c in self.checks:
            icon = {"OK": "[OK]", "WARN": "[!!]", "FAIL": "[XX]"}[c.status]
            lines.append(f"  {icon} {c.phrase_id}: {c.duration_sec:.2f}s / {c.window_sec:.2f}s window")
            for issue in c.issues:
                lines.append(f"        {issue}")
        ok = sum(1 for c in self.checks if c.status == "OK")
        warn = sum(1 for c in self.checks if c.status == "WARN")
        fail = sum(1 for c in self.checks if c.status == "FAIL")
        lines.append(f"\n  Total: {ok} OK, {warn} warnings, {fail} failures out of {len(self.checks)} phrases")
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

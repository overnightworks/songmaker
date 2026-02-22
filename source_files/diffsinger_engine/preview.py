"""Phrase-level preview mode for DiffSinger vocal tracks.

Generates individual phrases as separate WAV files for quick
iteration. Listen to 15 short clips instead of one 4-minute song.

Usage from a track script:
    from diffsinger_engine.preview import generate_previews

    generate_previews(
        phrases=VOCAL_PHRASES,
        voicebank_dir=VOICEBANK_DIR,
        output_dir="_output/midnight_frequency/previews",
        bpm=120,
    )

Or from CLI:
    python -m diffsinger_engine.preview albums/midnight_frequency/tracks/01_let_me_fall.py
"""

from __future__ import annotations

import struct
import time
from pathlib import Path

import numpy as np

from .engine import DiffSingerEngine
from .models import VocalPhrase
from .validation import validate_all, ValidationReport


def _write_wav_mono(path: str, samples: np.ndarray, sr: int = 44100) -> None:
    """Write a mono WAV file from float32 samples. No dependencies."""
    pcm = np.clip(samples, -1.0, 1.0)
    pcm_16 = (pcm * 32767).astype(np.int16)
    data = pcm_16.tobytes()

    with open(path, "wb") as f:
        n_samples = len(pcm_16)
        data_size = n_samples * 2
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(data)


def generate_previews(
    phrases: list[tuple[VocalPhrase, float]],
    voicebank_dir: str | Path,
    output_dir: str | Path,
    bpm: float = 120.0,
    total_beats: float = 480.0,
    device: str = "cuda",
    phrase_ids: list[str] | None = None,
) -> ValidationReport:
    """Generate individual WAV files for each vocal phrase.

    Args:
        phrases: List of (VocalPhrase, start_beat) tuples.
        voicebank_dir: Path to DiffSinger voicebank.
        output_dir: Directory for output WAV files.
        bpm: Song tempo.
        total_beats: Total song length in beats.
        device: "cuda" or "cpu".
        phrase_ids: Optional filter — only generate these phrase IDs.
            If None, generates all phrases.

    Returns:
        ValidationReport with checks for each generated phrase.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    seconds_per_beat = 60.0 / bpm

    # Filter phrases if specific IDs requested
    if phrase_ids:
        phrases = [(p, b) for p, b in phrases if p.phrase_id in phrase_ids]
        if not phrases:
            print(f"No phrases match IDs: {phrase_ids}")
            return ValidationReport()

    print(f"\n{'='*60}")
    print(f"Phrase Preview Mode — generating {len(phrases)} phrases")
    print(f"Output: {output_path.resolve()}")
    print(f"{'='*60}\n")

    engine = DiffSingerEngine(voicebank_dir=str(voicebank_dir), device=device)

    validation_data: list[tuple[VocalPhrase, np.ndarray, float]] = []

    for i, (phrase, beat) in enumerate(phrases):
        # Calculate beat window for this phrase
        if i + 1 < len(phrases):
            next_beat = phrases[i + 1][1]
            window_sec = (next_beat - beat) * seconds_per_beat
        else:
            window_sec = (total_beats - beat) * seconds_per_beat

        print(f"\n[{i+1}/{len(phrases)}] {phrase.phrase_id} (beat {beat}, window {window_sec:.1f}s)")

        start = time.time()
        result = engine.generate(phrase)
        elapsed = time.time() - start

        # Write WAV
        filename = f"{i+1:02d}_{phrase.phrase_id}.wav"
        wav_path = str(output_path / filename)
        _write_wav_mono(wav_path, result.samples)

        print(f"  -> {filename} ({result.duration:.2f}s, generated in {elapsed:.1f}s)")

        validation_data.append((phrase, result.samples, window_sec))

    # Run validation
    report = validate_all(validation_data)
    print(report.summary())

    # Write report to file
    report_path = output_path / "validation_report.txt"
    report_path.write_text(report.summary(), encoding="utf-8")
    print(f"\nReport saved: {report_path}")

    return report

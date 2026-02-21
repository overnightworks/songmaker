"""Audio I/O and mixing utilities for the Bark vocal engine."""

from __future__ import annotations

import struct
import subprocess
import wave
from pathlib import Path

import numpy as np

from bark_engine.constants import TARGET_SAMPLE_RATE


def write_wav_file(
    filename: str,
    samples: list[float] | np.ndarray,
    sample_rate: int = TARGET_SAMPLE_RATE,
) -> None:
    """Write mono WAV file from float samples.

    Args:
        filename: Output WAV file path.
        samples: Audio samples in [-1.0, 1.0] range.
        sample_rate: Sample rate in Hz.
    """
    sample_list: list[float] = (
        samples.tolist() if isinstance(samples, np.ndarray) else samples
    )

    with wave.open(filename, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        packed = struct.pack(
            f"<{len(sample_list)}h",
            *[int(max(-32767, min(32767, s * 32767))) for s in sample_list],
        )
        wf.writeframes(packed)


def read_wav_file(filename: str) -> tuple[list[float], int]:
    """Read mono WAV file to float samples.

    Args:
        filename: Input WAV file path.

    Returns:
        Tuple of (samples as float list, sample rate).
    """
    with wave.open(filename, "r") as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    samples: list[float] = []
    if sample_width == 2:
        for i in range(0, len(raw), 2 * n_channels):
            val = struct.unpack("<h", raw[i : i + 2])[0]
            samples.append(val / 32767.0)
    elif sample_width == 1:
        for i in range(0, len(raw), n_channels):
            samples.append((raw[i] - 128) / 128.0)

    return samples, sample_rate


def normalize_audio(samples: list[float], target_peak: float = 0.95) -> list[float]:
    """Normalize audio to target peak level.

    Args:
        samples: Audio samples.
        target_peak: Target peak amplitude.

    Returns:
        Normalized samples.
    """
    peak = max(abs(s) for s in samples) if samples else 1.0
    if peak < 0.001:
        return samples
    scale = target_peak / peak
    return [s * scale for s in samples]


def overlay_audio(base: list[float], addition: list[float], start_sample: int) -> None:
    """Overlay addition onto base at sample position (in-place).

    Args:
        base: Base audio buffer (modified in-place).
        addition: Audio to add.
        start_sample: Position in base to start overlay.
    """
    for i, val in enumerate(addition):
        pos = start_sample + i
        if 0 <= pos < len(base):
            base[pos] += val


def mix_tracks(tracks: list[tuple[list[float], float]]) -> list[float]:
    """Mix multiple audio tracks with volume levels and normalize.

    Args:
        tracks: List of (samples, volume) tuples.

    Returns:
        Mixed and normalized audio.
    """
    max_len = max(len(t[0]) for t in tracks)
    mixed = [0.0] * max_len

    for track_samples, volume in tracks:
        for i, val in enumerate(track_samples):
            mixed[i] += val * volume

    return normalize_audio(mixed, 0.95)


def apply_fade_out(samples: list[float], duration_seconds: float = 4.0) -> list[float]:
    """Apply exponential fade out to the end of audio.

    Args:
        samples: Audio samples.
        duration_seconds: Fade duration in seconds.

    Returns:
        Audio with fade out applied.
    """
    result = list(samples)
    fade_samples = int(duration_seconds * TARGET_SAMPLE_RATE)
    fade_start = len(result) - fade_samples

    for i in range(fade_samples):
        idx = fade_start + i
        if 0 <= idx < len(result):
            result[idx] *= (1.0 - i / fade_samples) ** 1.5

    return result


def master_to_mp3(wav_path: str, mp3_path: str) -> bool:
    """Master and encode WAV to MP3 with limiting and EQ.

    Args:
        wav_path: Input WAV file path.
        mp3_path: Output MP3 file path.

    Returns:
        True if successful.
    """
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                wav_path,
                "-af",
                (
                    "acompressor=threshold=-8dB:ratio=3:attack=5:release=100,"
                    "equalizer=f=50:t=h:w=30:g=-1,"
                    "equalizer=f=3000:t=h:w=2000:g=2,"
                    "equalizer=f=10000:t=h:w=3000:g=1.5,"
                    "alimiter=limit=0.97:attack=0.3:release=5"
                ),
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "192k",
                mp3_path,
            ],
            check=True,
            capture_output=True,
        )
        Path(wav_path).unlink(missing_ok=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"   ❌ Mastering failed: {exc}")
        return False

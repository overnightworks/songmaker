"""Stereo mixing engine for combining instrument tracks.

Handles stereo panning, volume control, and final mix-down
with limiting and normalization.
"""

from __future__ import annotations

import math
import struct
import subprocess
import wave
from pathlib import Path
from typing import Final

from instrumental_engine.constants import SAMPLE_RATE
from instrumental_engine.models import PAN_VALUES, PanPosition, RenderedTrack


LIMITER_THRESHOLD: Final[float] = 0.95
LIMITER_RATIO: Final[float] = 4.0


def apply_pan(
    mono_samples: list[float], pan: PanPosition
) -> tuple[list[float], list[float]]:
    """Apply stereo panning to mono audio.

    Uses constant-power panning law for natural stereo imaging.

    Args:
        mono_samples: Mono audio samples.
        pan: Stereo pan position.

    Returns:
        Tuple of (left_channel, right_channel).
    """
    pan_value = PAN_VALUES[pan]
    angle = (pan_value + 1.0) * math.pi / 4.0
    left_gain = math.cos(angle)
    right_gain = math.sin(angle)

    left = [s * left_gain for s in mono_samples]
    right = [s * right_gain for s in mono_samples]
    return left, right


def mix_stereo_tracks(
    tracks: list[RenderedTrack],
) -> tuple[list[float], list[float]]:
    """Mix multiple stereo tracks into a stereo master.

    Args:
        tracks: List of rendered tracks with stereo audio and volume.

    Returns:
        Tuple of (left_master, right_master).
    """
    if not tracks:
        return [], []

    max_len = max(max(len(t.samples_left), len(t.samples_right)) for t in tracks)
    left_master: list[float] = [0.0] * max_len
    right_master: list[float] = [0.0] * max_len

    for track in tracks:
        for i, val in enumerate(track.samples_left):
            if i < max_len:
                left_master[i] += val * track.volume
        for i, val in enumerate(track.samples_right):
            if i < max_len:
                right_master[i] += val * track.volume

    return left_master, right_master


def normalize_stereo(
    left: list[float], right: list[float], target_peak: float = 0.95
) -> tuple[list[float], list[float]]:
    """Normalize stereo audio to target peak.

    Args:
        left: Left channel samples.
        right: Right channel samples.
        target_peak: Target peak amplitude.

    Returns:
        Normalized (left, right) channels.
    """
    peak_l = max((abs(s) for s in left), default=0.001)
    peak_r = max((abs(s) for s in right), default=0.001)
    peak = max(peak_l, peak_r, 0.001)
    scale = target_peak / peak
    return [s * scale for s in left], [s * scale for s in right]


def apply_limiter(
    samples: list[float],
    threshold: float = LIMITER_THRESHOLD,
    ratio: float = LIMITER_RATIO,
) -> list[float]:
    """Apply soft-knee limiter to prevent clipping.

    Args:
        samples: Input audio samples.
        threshold: Limiting threshold.
        ratio: Compression ratio above threshold.

    Returns:
        Limited audio samples.
    """
    result: list[float] = []
    for s in samples:
        abs_s = abs(s)
        if abs_s > threshold:
            excess = abs_s - threshold
            compressed = threshold + excess / ratio
            sign = 1.0 if s >= 0 else -1.0
            result.append(sign * compressed)
        else:
            result.append(s)
    return result


def write_stereo_wav(
    filename: str,
    left: list[float],
    right: list[float],
    sample_rate: int = SAMPLE_RATE,
) -> None:
    """Write stereo WAV file from float samples.

    Args:
        filename: Output WAV file path.
        left: Left channel samples in [-1.0, 1.0].
        right: Right channel samples in [-1.0, 1.0].
        sample_rate: Sample rate in Hz.
    """
    n_samples = min(len(left), len(right))
    with wave.open(filename, "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)

        frames = bytearray()
        for i in range(n_samples):
            l_val = max(-32767, min(32767, int(left[i] * 32767)))
            r_val = max(-32767, min(32767, int(right[i] * 32767)))
            frames.extend(struct.pack("<hh", l_val, r_val))

        wf.writeframes(bytes(frames))


def write_mono_wav(
    filename: str,
    samples: list[float],
    sample_rate: int = SAMPLE_RATE,
) -> None:
    """Write mono WAV file from float samples.

    Args:
        filename: Output WAV file path.
        samples: Audio samples in [-1.0, 1.0].
        sample_rate: Sample rate in Hz.
    """
    with wave.open(filename, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        packed = struct.pack(
            f"<{len(samples)}h",
            *[int(max(-32767, min(32767, s * 32767))) for s in samples],
        )
        wf.writeframes(packed)


def stereo_to_mono(left: list[float], right: list[float]) -> list[float]:
    """Downmix stereo to mono.

    Args:
        left: Left channel.
        right: Right channel.

    Returns:
        Mono mix.
    """
    n = min(len(left), len(right))
    return [(left[i] + right[i]) * 0.5 for i in range(n)]


def overlay_onto(
    base_left: list[float],
    base_right: list[float],
    addition_left: list[float],
    addition_right: list[float],
    start_sample: int,
) -> None:
    """Overlay stereo audio onto a stereo base buffer (in-place).

    Args:
        base_left: Left base buffer (modified in-place).
        base_right: Right base buffer (modified in-place).
        addition_left: Left audio to overlay.
        addition_right: Right audio to overlay.
        start_sample: Sample position to start overlay.
    """
    for i in range(len(addition_left)):
        pos = start_sample + i
        if 0 <= pos < len(base_left):
            base_left[pos] += addition_left[i]
        if 0 <= pos < len(base_right) and i < len(addition_right):
            base_right[pos] += addition_right[i]


def apply_fade_out_stereo(
    left: list[float],
    right: list[float],
    duration_seconds: float = 4.0,
) -> tuple[list[float], list[float]]:
    """Apply fade out to stereo audio.

    Args:
        left: Left channel samples.
        right: Right channel samples.
        duration_seconds: Fade duration.

    Returns:
        Tuple of (left, right) with fade applied.
    """
    n = min(len(left), len(right))
    fade_samples = int(duration_seconds * SAMPLE_RATE)
    fade_start = n - fade_samples

    result_l = list(left)
    result_r = list(right)

    for i in range(fade_samples):
        idx = fade_start + i
        if 0 <= idx < n:
            gain = (1.0 - i / fade_samples) ** 1.5
            result_l[idx] *= gain
            result_r[idx] *= gain

    return result_l, result_r


def master_to_mp3(
    wav_path: str,
    mp3_path: str,
    bitrate: str = "192k",
) -> bool:
    """Master and encode WAV to MP3 via ffmpeg.

    Applies multiband compression, EQ, and limiting.

    Args:
        wav_path: Input WAV file path.
        mp3_path: Output MP3 file path.
        bitrate: MP3 encoding bitrate.

    Returns:
        True if successful.
    """
    filter_chain = ",".join(
        [
            "acompressor=threshold=-8dB:ratio=3:attack=5:release=100",
            "equalizer=f=50:t=h:w=30:g=-1",
            "equalizer=f=200:t=h:w=100:g=1",
            "equalizer=f=3000:t=h:w=2000:g=2",
            "equalizer=f=10000:t=h:w=3000:g=1.5",
            "alimiter=limit=0.97:attack=0.3:release=5",
        ]
    )

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                wav_path,
                "-af",
                filter_chain,
                "-codec:a",
                "libmp3lame",
                "-b:a",
                bitrate,
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

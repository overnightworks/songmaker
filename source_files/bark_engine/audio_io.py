"""Audio I/O and mixing utilities for the Bark vocal engine."""

from __future__ import annotations

import logging
import struct
import subprocess
import wave
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from instrumental_engine.mastering import master_stereo

from bark_engine.constants import TARGET_SAMPLE_RATE

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from bark_engine.models import GeneratedVocal


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


def master_to_mp3(
    wav_path: str,
    mp3_path: str,
    target_lufs: float = -14.0,
    stereo_width: float = 1.2,
    bitrate: str = "320k",
    metadata: dict[str, str] | None = None,
) -> bool:
    """Master WAV to MP3 with professional mastering chain.

    Replaces the old ffmpeg-filter-only approach with a full DSP pipeline:
        1. Load mono WAV and create stereo pair
        2. Apply mastering (multiband compression → stereo widening →
           LUFS normalization → soft clipping)
        3. Write mastered audio to temporary WAV
        4. Encode to MP3 via ffmpeg
        5. Clean up temporary and source WAV files

    Args:
        wav_path: Input WAV file path.
        mp3_path: Output MP3 file path.
        target_lufs: Target integrated LUFS (-14.0 for streaming).
        stereo_width: Stereo width multiplier (1.0 = unchanged, 1.2 = wider).
        bitrate: MP3 bitrate (default "320k" for high quality).

    Returns:
        True if mastering and encoding succeeded.
    """
    wav_file = Path(wav_path)
    if not wav_file.exists():
        logger.error("Mastering failed: WAV file not found: %s", wav_path)
        return False

    samples, sample_rate = read_wav_file(wav_path)
    if not samples:
        logger.error("Mastering failed: empty WAV file")
        return False

    logger.info(
        "Mastering: multiband -> stereo(%.1fx) -> LUFS(%.1f) -> clip",
        stereo_width, target_lufs,
    )
    mastered_left, mastered_right = master_stereo(
        samples,
        list(samples),
        target_lufs=target_lufs,
        stereo_width=stereo_width,
        sample_rate=sample_rate,
    )

    mastered_wav = wav_path.replace(".wav", "_mastered.wav")
    _write_stereo_wav(mastered_wav, mastered_left, mastered_right, sample_rate)

    # Build ffmpeg command with optional ID3 metadata
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        mastered_wav,
        "-codec:a",
        "libmp3lame",
        "-b:a",
        bitrate,
    ]
    if metadata:
        tag_map = {"title": "title", "artist": "artist", "album": "album",
                    "track": "track", "genre": "genre", "date": "date"}
        for key, ffmpeg_key in tag_map.items():
            if key in metadata and metadata[key]:
                cmd.extend(["-metadata", f"{ffmpeg_key}={metadata[key]}"])
        # Write lyrics as the 'lyrics' metadata field (ffmpeg id3v2 USLT)
        if "lyrics" in metadata and metadata["lyrics"]:
            cmd.extend(["-metadata", f"lyrics={metadata['lyrics']}"])
    cmd.append(mp3_path)

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        Path(mastered_wav).unlink(missing_ok=True)
        wav_file.unlink(missing_ok=True)
        logger.info("Mastered to %s", mp3_path)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        Path(mastered_wav).unlink(missing_ok=True)
        logger.error("MP3 encoding failed: %s", exc)
        return False


def _write_stereo_wav(
    filename: str,
    left: list[float],
    right: list[float],
    sample_rate: int,
) -> None:
    """Write stereo WAV file from two float channel lists.

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


def calculate_vocal_durations(
    vocals: list[GeneratedVocal],
    sample_rate: int = TARGET_SAMPLE_RATE,
) -> dict[str, float]:
    """Calculate duration of each generated vocal section in seconds.

    Maps each vocal's section_id to its audio length, enabling the ducking
    engine to build sample-accurate gain envelopes.

    Args:
        vocals: List of generated vocal results from BarkVocalEngine.
        sample_rate: Sample rate of vocal audio (default TARGET_SAMPLE_RATE).

    Returns:
        Dict mapping section_id → duration in seconds.
    """
    return {vocal.section_id: len(vocal.samples) / sample_rate for vocal in vocals}

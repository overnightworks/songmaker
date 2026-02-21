"""Audio processing utilities: trimming, crossfade, resampling."""

from __future__ import annotations


def trim_silence(
    samples: list[float], threshold: float = 0.01, min_length: int = 1000
) -> list[float]:
    """Trim leading and trailing silence from audio.

    Args:
        samples: Audio samples.
        threshold: Amplitude below which is considered silence.
        min_length: Minimum number of samples to keep.

    Returns:
        Trimmed samples.
    """
    if len(samples) < min_length:
        return samples

    start = 0
    for i, s in enumerate(samples):
        if abs(s) > threshold:
            start = max(0, i - 200)
            break

    end = len(samples)
    for i in range(len(samples) - 1, -1, -1):
        if abs(samples[i]) > threshold:
            end = min(len(samples), i + 200)
            break

    result = samples[start:end]
    return result if len(result) >= min_length else samples


def crossfade(
    audio_a: list[float], audio_b: list[float], crossfade_length: int
) -> list[float]:
    """Crossfade between two audio segments.

    Args:
        audio_a: First audio segment.
        audio_b: Second audio segment.
        crossfade_length: Number of samples for the crossfade region.

    Returns:
        Combined audio with smooth crossfade transition.
    """
    if crossfade_length <= 0 or not audio_a or not audio_b:
        result = list(audio_a)
        result.extend(audio_b)
        return result

    actual_fade = min(crossfade_length, len(audio_a), len(audio_b))

    result = list(audio_a[:-actual_fade])

    for i in range(actual_fade):
        fade_out = 1.0 - (i / actual_fade)
        fade_in = i / actual_fade
        a_val = audio_a[len(audio_a) - actual_fade + i]
        b_val = audio_b[i]
        result.append(a_val * fade_out + b_val * fade_in)

    result.extend(audio_b[actual_fade:])
    return result


def resample(samples: list[float], source_rate: int, target_rate: int) -> list[float]:
    """Resample audio from source to target sample rate via linear interpolation.

    Args:
        samples: Input samples at source_rate.
        source_rate: Original sample rate.
        target_rate: Desired sample rate.

    Returns:
        Resampled audio at target_rate.
    """
    if source_rate == target_rate:
        return list(samples)

    ratio = target_rate / source_rate
    new_length = int(len(samples) * ratio)
    resampled: list[float] = []

    for i in range(new_length):
        src_pos = i / ratio
        src_idx = int(src_pos)
        frac = src_pos - src_idx

        if src_idx + 1 < len(samples):
            val = samples[src_idx] * (1.0 - frac) + samples[src_idx + 1] * frac
        elif src_idx < len(samples):
            val = samples[src_idx]
        else:
            val = 0.0

        resampled.append(val)

    return resampled

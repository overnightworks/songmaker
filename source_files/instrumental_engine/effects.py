"""Audio effects processors for the instrumental engine.

Provides reverb, delay, chorus, sidechain compression, and
other effects as composable processing functions.
"""

from __future__ import annotations

import math
import random
from typing import Final

from instrumental_engine.constants import SAMPLE_RATE, TWO_PI


def apply_reverb(
    samples: list[float],
    room_size: float = 0.5,
    damping: float = 0.5,
    wet_mix: float = 0.3,
) -> list[float]:
    """Apply simple comb-filter reverb.

    Args:
        samples: Input audio samples.
        room_size: Room size (0.0 - 1.0, larger = longer reverb).
        damping: High-frequency damping (0.0 - 1.0).
        wet_mix: Wet/dry mix (0.0 = dry, 1.0 = full wet).

    Returns:
        Audio with reverb applied.
    """
    delay_times_ms = [29, 37, 43, 53, 67, 79]
    feedbacks = [room_size * (0.85 - i * 0.05) for i in range(len(delay_times_ms))]

    n = len(samples)
    wet: list[float] = [0.0] * n

    for dt_ms, fb in zip(delay_times_ms, feedbacks):
        delay_samples = int(dt_ms * SAMPLE_RATE / 1000)
        buffer: list[float] = [0.0] * delay_samples
        buf_idx = 0
        lp_state = 0.0

        for i in range(n):
            delayed = buffer[buf_idx]
            lp_state = delayed * (1.0 - damping) + lp_state * damping
            new_val = samples[i] + lp_state * fb
            buffer[buf_idx] = new_val
            buf_idx = (buf_idx + 1) % delay_samples
            wet[i] += delayed

    scale = 1.0 / len(delay_times_ms)
    dry_mix = 1.0 - wet_mix
    return [samples[i] * dry_mix + wet[i] * scale * wet_mix for i in range(n)]


def apply_delay(
    samples: list[float],
    delay_ms: float = 250.0,
    feedback: float = 0.4,
    wet_mix: float = 0.25,
) -> list[float]:
    """Apply echo/delay effect.

    Args:
        samples: Input audio samples.
        delay_ms: Delay time in milliseconds.
        feedback: Feedback amount (0.0 - 0.95).
        wet_mix: Wet/dry mix.

    Returns:
        Audio with delay applied.
    """
    delay_samples = int(delay_ms * SAMPLE_RATE / 1000)
    n = len(samples)
    buffer: list[float] = [0.0] * max(1, delay_samples)
    buf_idx = 0
    result: list[float] = []

    fb = min(0.95, feedback)
    dry_mix = 1.0 - wet_mix

    for i in range(n):
        delayed = buffer[buf_idx]
        new_val = samples[i] + delayed * fb
        buffer[buf_idx] = new_val
        buf_idx = (buf_idx + 1) % len(buffer)
        result.append(samples[i] * dry_mix + delayed * wet_mix)

    return result


def apply_chorus(
    samples: list[float],
    rate_hz: float = 1.5,
    depth_ms: float = 3.0,
    wet_mix: float = 0.3,
    voices: int = 2,
) -> list[float]:
    """Apply chorus effect using modulated delay.

    Args:
        samples: Input audio samples.
        rate_hz: LFO modulation rate.
        depth_ms: Maximum delay modulation depth.
        wet_mix: Wet/dry mix.
        voices: Number of chorus voices.

    Returns:
        Audio with chorus applied.
    """
    n = len(samples)
    max_delay = int((depth_ms + 5.0) * SAMPLE_RATE / 1000)
    buffer: list[float] = [0.0] * max(1, max_delay)
    result: list[float] = list(samples)

    for voice in range(voices):
        phase_offset = voice * TWO_PI / voices
        buf_idx = 0

        for i in range(n):
            buffer[buf_idx] = samples[i]

            lfo = math.sin(TWO_PI * rate_hz * i / SAMPLE_RATE + phase_offset)
            delay_samp = int((2.5 + depth_ms * 0.5 * (1.0 + lfo)) * SAMPLE_RATE / 1000)
            read_idx = (buf_idx - delay_samp) % len(buffer)
            delayed = buffer[read_idx]

            result[i] += delayed * wet_mix / voices
            buf_idx = (buf_idx + 1) % len(buffer)

    dry_scale = 1.0 / (1.0 + wet_mix)
    return [s * dry_scale for s in result]


def apply_sidechain_compression(
    samples: list[float],
    bpm: int,
    depth: float = 0.7,
    attack_ms: float = 5.0,
    release_ms: float = 150.0,
) -> list[float]:
    """Apply sidechain-style pumping compression synced to tempo.

    Simulates kick-triggered sidechain without an actual kick signal.

    Args:
        samples: Input audio samples.
        bpm: Tempo for pump timing.
        depth: Compression depth (0.0 = none, 1.0 = full duck).
        attack_ms: Attack time for the duck.
        release_ms: Release time for the pump.

    Returns:
        Audio with sidechain pumping.
    """
    beat_samples = int(60.0 / bpm * SAMPLE_RATE)
    attack_samples = max(1, int(attack_ms * SAMPLE_RATE / 1000))
    release_samples = max(1, int(release_ms * SAMPLE_RATE / 1000))
    n = len(samples)
    result: list[float] = []

    for i in range(n):
        beat_pos = i % beat_samples
        if beat_pos < attack_samples:
            env = 1.0 - depth * (beat_pos / attack_samples)
        elif beat_pos < attack_samples + release_samples:
            release_pos = beat_pos - attack_samples
            env = (1.0 - depth) + depth * (release_pos / release_samples)
        else:
            env = 1.0
        result.append(samples[i] * env)

    return result


def apply_stereo_widener(
    left: list[float], right: list[float], width: float = 1.5
) -> tuple[list[float], list[float]]:
    """Apply stereo widening effect.

    Args:
        left: Left channel.
        right: Right channel.
        width: Width factor (1.0 = normal, >1.0 = wider, <1.0 = narrower).

    Returns:
        Widened (left, right) channels.
    """
    n = min(len(left), len(right))
    result_l: list[float] = []
    result_r: list[float] = []

    for i in range(n):
        mid = (left[i] + right[i]) * 0.5
        side = (left[i] - right[i]) * 0.5
        side *= width
        result_l.append(mid + side)
        result_r.append(mid - side)

    return result_l, result_r


def generate_noise_sweep(
    duration_seconds: float,
    start_cutoff: float = 200.0,
    end_cutoff: float = 12000.0,
    amplitude: float = 0.3,
) -> list[float]:
    """Generate a filtered noise sweep (riser/downer effect).

    Args:
        duration_seconds: Duration in seconds.
        start_cutoff: Starting filter cutoff in Hz.
        end_cutoff: Ending filter cutoff in Hz.
        amplitude: Output amplitude.

    Returns:
        Noise sweep audio samples.
    """
    n = int(duration_seconds * SAMPLE_RATE)
    noise = [random.uniform(-1.0, 1.0) for _ in range(n)]
    result: list[float] = []
    prev = 0.0

    for i in range(n):
        progress = i / max(1, n - 1)
        cutoff = start_cutoff + (end_cutoff - start_cutoff) * progress
        rc = 1.0 / (TWO_PI * cutoff)
        dt = 1.0 / SAMPLE_RATE
        alpha = dt / (rc + dt)
        prev = prev + alpha * (noise[i] - prev)
        result.append(prev * amplitude * (0.5 + 0.5 * progress))

    return result


def generate_impact(amplitude: float = 0.8) -> list[float]:
    """Generate a cinematic impact/hit sound.

    Args:
        amplitude: Impact loudness.

    Returns:
        Impact audio samples.
    """
    duration = 0.5
    n = int(duration * SAMPLE_RATE)
    noise = [random.uniform(-1.0, 1.0) for _ in range(n)]
    result: list[float] = []

    for i in range(n):
        t = i / SAMPLE_RATE
        env = math.exp(-8.0 * t)
        low_boom = math.sin(TWO_PI * 40.0 * t) * math.exp(-5.0 * t) * 0.6
        noisy = noise[i] * math.exp(-15.0 * t) * 0.4
        result.append(amplitude * env * (low_boom + noisy))

    return result

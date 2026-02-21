"""Drum machine with synthesized percussion and pattern library.

Provides realistic drum synthesis using noise, sine waves, and
envelope shaping — no samples required.
"""

from __future__ import annotations

import math
import random
from typing import Final

from instrumental_engine.constants import SAMPLE_RATE, TWO_PI
from instrumental_engine.models import DrumHit, DrumPattern, DrumSound


KICK_DURATION: Final[float] = 0.25
SNARE_DURATION: Final[float] = 0.18
HIHAT_CLOSED_DURATION: Final[float] = 0.06
HIHAT_OPEN_DURATION: Final[float] = 0.25
CRASH_DURATION: Final[float] = 0.8
CLAP_DURATION: Final[float] = 0.15
TOM_DURATION: Final[float] = 0.2
RIMSHOT_DURATION: Final[float] = 0.08


def _generate_noise(n_samples: int) -> list[float]:
    """Generate white noise samples."""
    return [random.uniform(-1.0, 1.0) for _ in range(n_samples)]


def synthesize_kick(velocity: float = 0.9) -> list[float]:
    """Synthesize a kick drum using pitch-dropping sine wave.

    Args:
        velocity: Hit velocity (0.0 - 1.0).

    Returns:
        Kick drum audio samples.
    """
    n = int(KICK_DURATION * SAMPLE_RATE)
    result: list[float] = []

    for i in range(n):
        t = i / SAMPLE_RATE
        pitch_env = 150.0 * math.exp(-40.0 * t) + 45.0
        amp_env = math.exp(-6.0 * t)
        click = 0.8 * math.exp(-200.0 * t) if t < 0.01 else 0.0
        body = math.sin(TWO_PI * pitch_env * t)
        result.append(velocity * amp_env * (body + click))

    return result


def synthesize_snare(velocity: float = 0.7) -> list[float]:
    """Synthesize a snare drum with noise and tone body.

    Args:
        velocity: Hit velocity.

    Returns:
        Snare drum audio samples.
    """
    n = int(SNARE_DURATION * SAMPLE_RATE)
    noise = _generate_noise(n)
    result: list[float] = []

    for i in range(n):
        t = i / SAMPLE_RATE
        tone_env = math.exp(-20.0 * t)
        noise_env = math.exp(-12.0 * t)
        tone = math.sin(TWO_PI * 180.0 * t) * tone_env * 0.5
        noisy = noise[i] * noise_env * 0.6
        result.append(velocity * (tone + noisy))

    return result


def synthesize_clap(velocity: float = 0.5) -> list[float]:
    """Synthesize a handclap using layered noise bursts.

    Args:
        velocity: Hit velocity.

    Returns:
        Clap audio samples.
    """
    n = int(CLAP_DURATION * SAMPLE_RATE)
    noise = _generate_noise(n)
    result: list[float] = [0.0] * n
    burst_times = [0.0, 0.008, 0.016, 0.025]

    for bt in burst_times:
        start = int(bt * SAMPLE_RATE)
        for i in range(start, n):
            t = (i - start) / SAMPLE_RATE
            env = math.exp(-30.0 * t)
            if i < n:
                result[i] += velocity * noise[i] * env * 0.3

    return result


def synthesize_hihat(velocity: float = 0.3, open_hat: bool = False) -> list[float]:
    """Synthesize a hihat using filtered noise.

    Args:
        velocity: Hit velocity.
        open_hat: If True, longer decay for open hihat.

    Returns:
        Hihat audio samples.
    """
    duration = HIHAT_OPEN_DURATION if open_hat else HIHAT_CLOSED_DURATION
    n = int(duration * SAMPLE_RATE)
    noise = _generate_noise(n)
    decay_rate = 8.0 if open_hat else 40.0
    result: list[float] = []

    for i in range(n):
        t = i / SAMPLE_RATE
        env = math.exp(-decay_rate * t)
        metallic = 0.0
        for freq in (3200.0, 5800.0, 8400.0, 11000.0):
            metallic += math.sin(TWO_PI * freq * t) * 0.15
        result.append(velocity * env * (noise[i] * 0.7 + metallic * 0.3))

    return result


def synthesize_crash(velocity: float = 0.6) -> list[float]:
    """Synthesize a crash cymbal.

    Args:
        velocity: Hit velocity.

    Returns:
        Crash cymbal audio samples.
    """
    n = int(CRASH_DURATION * SAMPLE_RATE)
    noise = _generate_noise(n)
    result: list[float] = []

    for i in range(n):
        t = i / SAMPLE_RATE
        env = math.exp(-3.5 * t)
        metallic = sum(
            math.sin(TWO_PI * f * t) * 0.1
            for f in (2800.0, 4200.0, 6500.0, 9200.0, 12000.0)
        )
        result.append(velocity * env * (noise[i] * 0.6 + metallic * 0.4))

    return result


def synthesize_tom(velocity: float = 0.7, pitch_hz: float = 120.0) -> list[float]:
    """Synthesize a tom drum.

    Args:
        velocity: Hit velocity.
        pitch_hz: Fundamental pitch of the tom.

    Returns:
        Tom drum audio samples.
    """
    n = int(TOM_DURATION * SAMPLE_RATE)
    result: list[float] = []

    for i in range(n):
        t = i / SAMPLE_RATE
        pitch_env = pitch_hz * (1.0 + 0.5 * math.exp(-15.0 * t))
        amp_env = math.exp(-8.0 * t)
        body = math.sin(TWO_PI * pitch_env * t)
        result.append(velocity * amp_env * body)

    return result


def synthesize_rimshot(velocity: float = 0.6) -> list[float]:
    """Synthesize a rimshot.

    Args:
        velocity: Hit velocity.

    Returns:
        Rimshot audio samples.
    """
    n = int(RIMSHOT_DURATION * SAMPLE_RATE)
    noise = _generate_noise(n)
    result: list[float] = []

    for i in range(n):
        t = i / SAMPLE_RATE
        env = math.exp(-50.0 * t)
        tone = math.sin(TWO_PI * 800.0 * t) * 0.6
        result.append(velocity * env * (tone + noise[i] * 0.4))

    return result


TOM_PITCHES: Final[dict[DrumSound, float]] = {
    DrumSound.TOM_LOW: 90.0,
    DrumSound.TOM_MID: 120.0,
    DrumSound.TOM_HIGH: 160.0,
}

_DRUM_RENDERERS: Final[dict[DrumSound, object]] = {}


def render_drum_hit(sound: DrumSound, velocity: float) -> list[float]:
    """Render a single drum sound.

    Args:
        sound: Which drum to synthesize.
        velocity: Hit velocity (0.0 - 1.0).

    Returns:
        Audio samples for the drum hit.
    """
    renderers = {
        DrumSound.KICK: lambda v: synthesize_kick(v),
        DrumSound.SNARE: lambda v: synthesize_snare(v),
        DrumSound.CLOSED_HIHAT: lambda v: synthesize_hihat(v, open_hat=False),
        DrumSound.OPEN_HIHAT: lambda v: synthesize_hihat(v, open_hat=True),
        DrumSound.RIDE: lambda v: synthesize_hihat(v * 0.8, open_hat=True),
        DrumSound.CRASH: lambda v: synthesize_crash(v),
        DrumSound.CLAP: lambda v: synthesize_clap(v),
        DrumSound.TOM_LOW: lambda v: synthesize_tom(v, TOM_PITCHES[DrumSound.TOM_LOW]),
        DrumSound.TOM_MID: lambda v: synthesize_tom(v, TOM_PITCHES[DrumSound.TOM_MID]),
        DrumSound.TOM_HIGH: lambda v: synthesize_tom(
            v, TOM_PITCHES[DrumSound.TOM_HIGH]
        ),
        DrumSound.RIMSHOT: lambda v: synthesize_rimshot(v),
        DrumSound.COWBELL: lambda v: synthesize_rimshot(v * 0.7),
        DrumSound.SHAKER: lambda v: synthesize_hihat(v * 0.4, open_hat=False),
    }
    renderer = renderers.get(sound)
    if renderer is None:
        return synthesize_hihat(velocity)
    return renderer(velocity)


def render_drum_pattern(pattern: DrumPattern, bpm: int) -> list[float]:
    """Render a complete drum pattern to audio.

    Args:
        pattern: The drum pattern to render.
        bpm: Tempo in beats per minute.

    Returns:
        Audio samples for the complete pattern.
    """
    seconds_per_beat = 60.0 / bpm
    total_seconds = pattern.length_beats * seconds_per_beat
    total_samples = int(total_seconds * SAMPLE_RATE)
    output: list[float] = [0.0] * total_samples

    for hit in pattern.hits:
        hit_start = int(hit.beat_position * seconds_per_beat * SAMPLE_RATE)
        hit_audio = render_drum_hit(hit.sound, hit.velocity)

        for i, val in enumerate(hit_audio):
            pos = hit_start + i
            if 0 <= pos < total_samples:
                output[pos] += val

    return output


def repeat_pattern(pattern: DrumPattern, bpm: int, total_beats: float) -> list[float]:
    """Repeat a drum pattern to fill a duration.

    Args:
        pattern: The drum pattern to repeat.
        bpm: Tempo in beats per minute.
        total_beats: Total duration in beats to fill.

    Returns:
        Audio samples with the pattern repeated.
    """
    single = render_drum_pattern(pattern, bpm)
    seconds_per_beat = 60.0 / bpm
    total_samples = int(total_beats * seconds_per_beat * SAMPLE_RATE)
    output: list[float] = [0.0] * total_samples
    pattern_len = len(single)

    if pattern_len == 0:
        return output

    repetitions = int(math.ceil(total_samples / pattern_len))
    for rep in range(repetitions):
        offset = rep * pattern_len
        for i, val in enumerate(single):
            pos = offset + i
            if pos < total_samples:
                output[pos] += val

    return output


# ═══════════════════════════════════════════════════════════════════
# Pre-built drum pattern library
# ═══════════════════════════════════════════════════════════════════


def _build_basic_rock() -> DrumPattern:
    """Standard rock beat: kick on 1 & 3, snare on 2 & 4, hihats on 8ths."""
    hits: list[DrumHit] = []
    for beat in (0.0, 2.0):
        hits.append(DrumHit(DrumSound.KICK, 0.9, beat))
    for beat in (1.0, 3.0):
        hits.append(DrumHit(DrumSound.SNARE, 0.8, beat))
    for eighth in range(8):
        hits.append(DrumHit(DrumSound.CLOSED_HIHAT, 0.4, eighth * 0.5))
    return DrumPattern("basic_rock", tuple(hits), 4.0)


def _build_four_on_floor() -> DrumPattern:
    """EDM/disco four-on-the-floor: kick on every beat."""
    hits: list[DrumHit] = []
    for beat in range(4):
        hits.append(DrumHit(DrumSound.KICK, 0.9, float(beat)))
    for beat in (1.0, 3.0):
        hits.append(DrumHit(DrumSound.CLAP, 0.7, beat))
    for eighth in range(8):
        hits.append(DrumHit(DrumSound.CLOSED_HIHAT, 0.35, eighth * 0.5))
    hits.append(DrumHit(DrumSound.OPEN_HIHAT, 0.4, 3.5))
    return DrumPattern("four_on_floor", tuple(hits), 4.0)


def _build_boom_bap() -> DrumPattern:
    """Hip-hop boom bap: kick on 1 & 2.5, snare on 2 & 4."""
    hits: list[DrumHit] = []
    hits.append(DrumHit(DrumSound.KICK, 0.9, 0.0))
    hits.append(DrumHit(DrumSound.KICK, 0.7, 1.5))
    hits.append(DrumHit(DrumSound.SNARE, 0.85, 1.0))
    hits.append(DrumHit(DrumSound.SNARE, 0.85, 3.0))
    for eighth in range(8):
        vel = 0.4 if eighth % 2 == 0 else 0.25
        hits.append(DrumHit(DrumSound.CLOSED_HIHAT, vel, eighth * 0.5))
    return DrumPattern("boom_bap", tuple(hits), 4.0)


def _build_trap() -> DrumPattern:
    """Trap beat: sparse kick, rapid hihats, hard snare."""
    hits: list[DrumHit] = []
    hits.append(DrumHit(DrumSound.KICK, 0.95, 0.0))
    hits.append(DrumHit(DrumSound.KICK, 0.8, 2.25))
    hits.append(DrumHit(DrumSound.SNARE, 0.9, 1.0))
    hits.append(DrumHit(DrumSound.SNARE, 0.9, 3.0))
    for sixteenth in range(16):
        vel = 0.35 + 0.1 * (sixteenth % 3 == 0)
        hits.append(DrumHit(DrumSound.CLOSED_HIHAT, vel, sixteenth * 0.25))
    hits.append(DrumHit(DrumSound.OPEN_HIHAT, 0.3, 1.75))
    hits.append(DrumHit(DrumSound.OPEN_HIHAT, 0.3, 3.75))
    return DrumPattern("trap", tuple(hits), 4.0)


def _build_reggaeton() -> DrumPattern:
    """Reggaeton dembow rhythm."""
    hits: list[DrumHit] = []
    hits.append(DrumHit(DrumSound.KICK, 0.9, 0.0))
    hits.append(DrumHit(DrumSound.KICK, 0.85, 1.5))
    hits.append(DrumHit(DrumSound.KICK, 0.85, 2.5))
    hits.append(DrumHit(DrumSound.SNARE, 0.8, 0.75))
    hits.append(DrumHit(DrumSound.SNARE, 0.8, 1.75))
    hits.append(DrumHit(DrumSound.SNARE, 0.8, 2.75))
    hits.append(DrumHit(DrumSound.SNARE, 0.8, 3.75))
    for eighth in range(8):
        hits.append(DrumHit(DrumSound.CLOSED_HIHAT, 0.3, eighth * 0.5))
    return DrumPattern("reggaeton", tuple(hits), 4.0)


def _build_ballad() -> DrumPattern:
    """Soft ballad beat with brushes."""
    hits: list[DrumHit] = []
    hits.append(DrumHit(DrumSound.KICK, 0.5, 0.0))
    hits.append(DrumHit(DrumSound.KICK, 0.4, 2.5))
    hits.append(DrumHit(DrumSound.SNARE, 0.35, 1.0))
    hits.append(DrumHit(DrumSound.SNARE, 0.35, 3.0))
    for eighth in range(8):
        hits.append(DrumHit(DrumSound.RIDE, 0.2, eighth * 0.5))
    return DrumPattern("ballad", tuple(hits), 4.0)


def _build_schlager() -> DrumPattern:
    """German Schlager/party beat."""
    hits: list[DrumHit] = []
    for beat in range(4):
        hits.append(DrumHit(DrumSound.KICK, 0.85, float(beat)))
    for beat in (1.0, 3.0):
        hits.append(DrumHit(DrumSound.SNARE, 0.75, beat))
    for beat in (0.5, 1.5, 2.5, 3.5):
        hits.append(DrumHit(DrumSound.CLOSED_HIHAT, 0.35, beat))
    for beat in (0.0, 1.0, 2.0, 3.0):
        hits.append(DrumHit(DrumSound.CLOSED_HIHAT, 0.45, beat))
    return DrumPattern("schlager", tuple(hits), 4.0)


def _build_synthwave() -> DrumPattern:
    """80s synthwave/synthpop beat."""
    hits: list[DrumHit] = []
    for beat in range(4):
        hits.append(DrumHit(DrumSound.KICK, 0.85, float(beat)))
    for beat in (1.0, 3.0):
        hits.append(DrumHit(DrumSound.CLAP, 0.7, beat))
    for sixteenth in range(16):
        vel = 0.3 if sixteenth % 2 == 0 else 0.2
        hits.append(DrumHit(DrumSound.CLOSED_HIHAT, vel, sixteenth * 0.25))
    return DrumPattern("synthwave", tuple(hits), 4.0)


PATTERN_LIBRARY: Final[dict[str, DrumPattern]] = {
    "basic_rock": _build_basic_rock(),
    "four_on_floor": _build_four_on_floor(),
    "boom_bap": _build_boom_bap(),
    "trap": _build_trap(),
    "reggaeton": _build_reggaeton(),
    "ballad": _build_ballad(),
    "schlager": _build_schlager(),
    "synthwave": _build_synthwave(),
}

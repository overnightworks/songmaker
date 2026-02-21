"""Pure-Python DSP synthesizer instruments.

Provides high-quality synthesized instruments using additive, subtractive,
and wavetable synthesis techniques. No external dependencies required.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Final

from instrumental_engine.constants import SAMPLE_RATE, TWO_PI

ENVELOPE_MIN: Final[float] = 0.0001


def _apply_envelope(
    samples: list[float],
    attack: float,
    decay: float,
    sustain_level: float,
    release: float,
) -> list[float]:
    """Apply ADSR envelope to audio samples.

    Args:
        samples: Raw audio samples.
        attack: Attack time in seconds.
        decay: Decay time in seconds.
        sustain_level: Sustain amplitude (0.0 - 1.0).
        release: Release time in seconds.

    Returns:
        Samples with envelope applied.
    """
    total = len(samples)
    attack_samples = int(attack * SAMPLE_RATE)
    decay_samples = int(decay * SAMPLE_RATE)
    release_samples = int(release * SAMPLE_RATE)
    sustain_samples = max(0, total - attack_samples - decay_samples - release_samples)

    result: list[float] = []
    for i in range(total):
        if i < attack_samples:
            env = i / max(1, attack_samples)
        elif i < attack_samples + decay_samples:
            decay_pos = (i - attack_samples) / max(1, decay_samples)
            env = 1.0 - decay_pos * (1.0 - sustain_level)
        elif i < attack_samples + decay_samples + sustain_samples:
            env = sustain_level
        else:
            release_pos = i - attack_samples - decay_samples - sustain_samples
            env = sustain_level * (1.0 - release_pos / max(1, release_samples))
        result.append(samples[i] * max(ENVELOPE_MIN, env))

    return result


def _low_pass_filter(
    samples: list[float], cutoff_hz: float, resonance: float = 0.5
) -> list[float]:
    """Simple one-pole low-pass filter.

    Args:
        samples: Input samples.
        cutoff_hz: Cutoff frequency in Hz.
        resonance: Filter resonance (0.0 - 1.0).

    Returns:
        Filtered samples.
    """
    rc = 1.0 / (TWO_PI * cutoff_hz)
    dt = 1.0 / SAMPLE_RATE
    alpha = dt / (rc + dt)
    feedback = resonance + resonance / (1.0 - alpha)

    result: list[float] = []
    prev = 0.0
    prev2 = 0.0
    for s in samples:
        filtered = prev + alpha * (s + feedback * (prev - prev2) - prev)
        result.append(filtered)
        prev2 = prev
        prev = filtered

    return result


def _soft_clip(samples: list[float], drive: float = 1.0) -> list[float]:
    """Apply soft clipping distortion.

    Args:
        samples: Input samples.
        drive: Distortion amount (1.0 = clean, higher = more distorted).

    Returns:
        Clipped samples.
    """
    return [math.tanh(s * drive) for s in samples]


@dataclass(frozen=True)
class SupersawSynth:
    """Supersaw synthesizer with multiple detuned saw waves.

    Attributes:
        voices: Number of detuned oscillators.
        detune_cents: Maximum detune spread in cents.
        attack: Envelope attack in seconds.
        decay: Envelope decay in seconds.
        sustain: Sustain level.
        release: Envelope release in seconds.
        cutoff_hz: Low-pass filter cutoff.
    """

    voices: int = 7
    detune_cents: float = 15.0
    attack: float = 0.01
    decay: float = 0.1
    sustain: float = 0.7
    release: float = 0.15
    cutoff_hz: float = 8000.0

    def render_note(
        self, freq: float, duration_seconds: float, velocity: float
    ) -> list[float]:
        """Render a supersaw note."""
        n_samples = int(duration_seconds * SAMPLE_RATE)
        detune_range = self.detune_cents / 1200.0
        voice_detunes = [
            freq * (2.0 ** ((i - self.voices // 2) * detune_range / self.voices))
            for i in range(self.voices)
        ]

        raw: list[float] = [0.0] * n_samples
        amp_per_voice = velocity / self.voices

        for vf in voice_detunes:
            phase = random.random() * TWO_PI
            for i in range(n_samples):
                phase += TWO_PI * vf / SAMPLE_RATE
                raw[i] += amp_per_voice * (2.0 * (phase / TWO_PI % 1.0) - 1.0)

        filtered = _low_pass_filter(raw, self.cutoff_hz)
        return _apply_envelope(
            filtered,
            self.attack,
            self.decay,
            self.sustain,
            self.release,
        )

    def render_chord(
        self,
        frequencies: tuple[float, ...],
        duration_seconds: float,
        velocity: float,
    ) -> list[float]:
        """Render a supersaw chord."""
        n_samples = int(duration_seconds * SAMPLE_RATE)
        mixed: list[float] = [0.0] * n_samples
        vel_per_note = velocity / max(1, len(frequencies))

        for freq in frequencies:
            note_audio = self.render_note(freq, duration_seconds, vel_per_note)
            for i, s in enumerate(note_audio):
                if i < n_samples:
                    mixed[i] += s

        return mixed


@dataclass(frozen=True)
class PadSynth:
    """Warm pad synthesizer using additive synthesis with slow attack.

    Attributes:
        harmonics: Number of harmonics to include.
        attack: Slow attack for pad character.
        decay: Decay time.
        sustain: Sustain level.
        release: Release time.
        cutoff_hz: Filter cutoff.
        warmth: Amount of even-harmonic emphasis (0.0 - 1.0).
    """

    harmonics: int = 8
    attack: float = 0.4
    decay: float = 0.3
    sustain: float = 0.6
    release: float = 0.8
    cutoff_hz: float = 4000.0
    warmth: float = 0.5

    def render_note(
        self, freq: float, duration_seconds: float, velocity: float
    ) -> list[float]:
        """Render a warm pad tone."""
        n_samples = int(duration_seconds * SAMPLE_RATE)
        raw: list[float] = [0.0] * n_samples

        for h in range(1, self.harmonics + 1):
            harmonic_freq = freq * h
            if harmonic_freq > SAMPLE_RATE / 2:
                break
            amp = velocity / (h**1.2)
            if h % 2 == 0:
                amp *= 1.0 + self.warmth
            phase = random.random() * TWO_PI
            for i in range(n_samples):
                raw[i] += amp * math.sin(
                    phase + TWO_PI * harmonic_freq * i / SAMPLE_RATE
                )

        filtered = _low_pass_filter(raw, self.cutoff_hz)
        normalized_peak = max(abs(s) for s in filtered) if filtered else 1.0
        scale = velocity / max(0.001, normalized_peak)
        scaled = [s * scale for s in filtered]

        return _apply_envelope(
            scaled,
            self.attack,
            self.decay,
            self.sustain,
            self.release,
        )

    def render_chord(
        self,
        frequencies: tuple[float, ...],
        duration_seconds: float,
        velocity: float,
    ) -> list[float]:
        """Render a pad chord."""
        n_samples = int(duration_seconds * SAMPLE_RATE)
        mixed: list[float] = [0.0] * n_samples
        vel_per_note = velocity / max(1, len(frequencies))

        for freq in frequencies:
            note_audio = self.render_note(freq, duration_seconds, vel_per_note)
            for i, s in enumerate(note_audio):
                if i < n_samples:
                    mixed[i] += s

        return mixed


@dataclass(frozen=True)
class PluckSynth:
    """Plucked string synthesizer using Karplus-Strong algorithm.

    Attributes:
        brightness: Controls filter cutoff (0.0 = dull, 1.0 = bright).
        decay_factor: Controls how fast the string decays.
        attack: Short attack transient.
    """

    brightness: float = 0.5
    decay_factor: float = 0.996
    attack: float = 0.003

    def render_note(
        self, freq: float, duration_seconds: float, velocity: float
    ) -> list[float]:
        """Render a plucked string note via Karplus-Strong synthesis."""
        n_samples = int(duration_seconds * SAMPLE_RATE)
        period = max(2, int(SAMPLE_RATE / freq))

        buffer = [random.uniform(-velocity, velocity) for _ in range(period)]
        result: list[float] = []

        blend = 0.5 + 0.3 * self.brightness

        for i in range(n_samples):
            idx = i % period
            val = buffer[idx]
            next_val = buffer[(idx + 1) % period]
            new_val = self.decay_factor * (blend * val + (1.0 - blend) * next_val)
            buffer[idx] = new_val
            result.append(new_val)

        attack_samples = int(self.attack * SAMPLE_RATE)
        for i in range(min(attack_samples, len(result))):
            result[i] *= i / max(1, attack_samples)

        return result

    def render_chord(
        self,
        frequencies: tuple[float, ...],
        duration_seconds: float,
        velocity: float,
    ) -> list[float]:
        """Render a plucked chord (arpeggio-like strum)."""
        n_samples = int(duration_seconds * SAMPLE_RATE)
        mixed: list[float] = [0.0] * n_samples
        strum_delay = int(0.015 * SAMPLE_RATE)
        vel_per_note = velocity / max(1, len(frequencies))

        for note_idx, freq in enumerate(frequencies):
            note_audio = self.render_note(freq, duration_seconds, vel_per_note)
            offset = note_idx * strum_delay
            for i, s in enumerate(note_audio):
                pos = offset + i
                if pos < n_samples:
                    mixed[pos] += s

        return mixed


@dataclass(frozen=True)
class SubBassSynth:
    """Deep sub-bass synthesizer using sine + light saturation.

    Attributes:
        attack: Attack time.
        decay: Decay time.
        sustain: Sustain level.
        release: Release time.
        saturation: Soft clipping drive.
        sub_octave_mix: Amount of sub-octave added (0.0 - 1.0).
    """

    attack: float = 0.01
    decay: float = 0.05
    sustain: float = 0.8
    release: float = 0.1
    saturation: float = 1.5
    sub_octave_mix: float = 0.3

    def render_note(
        self, freq: float, duration_seconds: float, velocity: float
    ) -> list[float]:
        """Render a sub-bass note."""
        n_samples = int(duration_seconds * SAMPLE_RATE)
        raw: list[float] = []

        for i in range(n_samples):
            t = i / SAMPLE_RATE
            fundamental = math.sin(TWO_PI * freq * t)
            sub = math.sin(TWO_PI * freq * 0.5 * t) * self.sub_octave_mix
            raw.append(velocity * (fundamental + sub) / (1.0 + self.sub_octave_mix))

        saturated = _soft_clip(raw, self.saturation)
        return _apply_envelope(
            saturated,
            self.attack,
            self.decay,
            self.sustain,
            self.release,
        )

    def render_chord(
        self,
        frequencies: tuple[float, ...],
        duration_seconds: float,
        velocity: float,
    ) -> list[float]:
        """Render bass chord (typically monophonic — uses lowest note)."""
        lowest = min(frequencies) if frequencies else 100.0
        return self.render_note(lowest, duration_seconds, velocity)


@dataclass(frozen=True)
class LeadSynth:
    """Monophonic lead synthesizer with square/saw blend.

    Attributes:
        saw_mix: Sawtooth wave mix (0.0 - 1.0, rest is square).
        attack: Envelope attack.
        decay: Envelope decay.
        sustain: Sustain level.
        release: Envelope release.
        cutoff_hz: Filter cutoff frequency.
        vibrato_hz: Vibrato rate.
        vibrato_depth: Vibrato depth in semitones.
    """

    saw_mix: float = 0.6
    attack: float = 0.01
    decay: float = 0.08
    sustain: float = 0.75
    release: float = 0.12
    cutoff_hz: float = 6000.0
    vibrato_hz: float = 5.0
    vibrato_depth: float = 0.15

    def render_note(
        self, freq: float, duration_seconds: float, velocity: float
    ) -> list[float]:
        """Render a lead synth note."""
        n_samples = int(duration_seconds * SAMPLE_RATE)
        raw: list[float] = []
        phase = 0.0

        for i in range(n_samples):
            t = i / SAMPLE_RATE
            vibrato = 1.0 + self.vibrato_depth / 12.0 * math.sin(
                TWO_PI * self.vibrato_hz * t
            )
            current_freq = freq * vibrato

            phase += TWO_PI * current_freq / SAMPLE_RATE
            saw = 2.0 * (phase / TWO_PI % 1.0) - 1.0
            square = 1.0 if (phase / TWO_PI % 1.0) < 0.5 else -1.0
            raw.append(velocity * (self.saw_mix * saw + (1.0 - self.saw_mix) * square))

        filtered = _low_pass_filter(raw, self.cutoff_hz)
        return _apply_envelope(
            filtered,
            self.attack,
            self.decay,
            self.sustain,
            self.release,
        )

    def render_chord(
        self,
        frequencies: tuple[float, ...],
        duration_seconds: float,
        velocity: float,
    ) -> list[float]:
        """Lead is monophonic — render highest note only."""
        highest = max(frequencies) if frequencies else 440.0
        return self.render_note(highest, duration_seconds, velocity)


@dataclass(frozen=True)
class PianoSynth:
    """Piano-like synthesizer using struck-string modeling.

    Combines multiple harmonics with a percussive attack and natural
    decay for realistic piano sound. Suitable when SoundFont is unavailable.

    Attributes:
        harmonics: Number of overtones.
        attack: Very short attack for hammer strike.
        brightness: Brightness of tone (0.0 - 1.0).
        sustain_time: How long notes ring out.
    """

    harmonics: int = 10
    attack: float = 0.005
    brightness: float = 0.6
    sustain_time: float = 2.0

    def render_note(
        self, freq: float, duration_seconds: float, velocity: float
    ) -> list[float]:
        """Render a piano-like note."""
        n_samples = int(duration_seconds * SAMPLE_RATE)
        raw: list[float] = [0.0] * n_samples
        attack_samp = int(self.attack * SAMPLE_RATE)

        for h in range(1, self.harmonics + 1):
            harmonic_freq = freq * h
            if harmonic_freq > SAMPLE_RATE / 2:
                break

            amp = velocity / (h ** (1.5 - 0.5 * self.brightness))
            decay_rate = h * 1.5 / self.sustain_time
            phase_offset = random.random() * 0.01

            for i in range(n_samples):
                t = i / SAMPLE_RATE
                envelope = math.exp(-decay_rate * t)
                if i < attack_samp:
                    envelope *= i / max(1, attack_samp)
                raw[i] += (
                    amp * envelope * math.sin(TWO_PI * harmonic_freq * t + phase_offset)
                )

        peak = max(abs(s) for s in raw) if raw else 1.0
        scale = velocity / max(0.001, peak)
        return [s * scale for s in raw]

    def render_chord(
        self,
        frequencies: tuple[float, ...],
        duration_seconds: float,
        velocity: float,
    ) -> list[float]:
        """Render a piano chord."""
        n_samples = int(duration_seconds * SAMPLE_RATE)
        mixed: list[float] = [0.0] * n_samples
        vel_per_note = velocity / max(1, len(frequencies))

        for freq in frequencies:
            note_audio = self.render_note(freq, duration_seconds, vel_per_note)
            for i, s in enumerate(note_audio):
                if i < n_samples:
                    mixed[i] += s

        return mixed


@dataclass(frozen=True)
class StringsSynth:
    """String ensemble synthesizer with slow attack and lush sound.

    Attributes:
        voices_per_note: Number of detuned voices for ensemble effect.
        detune_cents: Detune spread per voice.
        attack: Slow bow attack.
        decay: Decay after attack.
        sustain: Sustain level.
        release: Release time.
        vibrato_hz: Natural vibrato rate.
        vibrato_depth: Vibrato depth in cents.
    """

    voices_per_note: int = 3
    detune_cents: float = 8.0
    attack: float = 0.3
    decay: float = 0.2
    sustain: float = 0.7
    release: float = 0.5
    vibrato_hz: float = 5.5
    vibrato_depth: float = 12.0

    def render_note(
        self, freq: float, duration_seconds: float, velocity: float
    ) -> list[float]:
        """Render a strings note with ensemble effect."""
        n_samples = int(duration_seconds * SAMPLE_RATE)
        raw: list[float] = [0.0] * n_samples

        for voice_idx in range(self.voices_per_note):
            detune = (voice_idx - self.voices_per_note // 2) * self.detune_cents
            voice_freq = freq * (2.0 ** (detune / 1200.0))
            vib_phase = random.random() * TWO_PI
            amp = velocity / self.voices_per_note

            for i in range(n_samples):
                t = i / SAMPLE_RATE
                vib = 1.0 + (self.vibrato_depth / 1200.0) * math.sin(
                    TWO_PI * self.vibrato_hz * t + vib_phase
                )
                current_freq = voice_freq * vib
                val = math.sin(TWO_PI * current_freq * t)
                val += 0.3 * math.sin(TWO_PI * current_freq * 2 * t)
                val += 0.1 * math.sin(TWO_PI * current_freq * 3 * t)
                raw[i] += amp * val

        peak = max(abs(s) for s in raw) if raw else 1.0
        scale = velocity / max(0.001, peak)
        scaled = [s * scale for s in raw]

        return _apply_envelope(
            scaled,
            self.attack,
            self.decay,
            self.sustain,
            self.release,
        )

    def render_chord(
        self,
        frequencies: tuple[float, ...],
        duration_seconds: float,
        velocity: float,
    ) -> list[float]:
        """Render a string ensemble chord."""
        n_samples = int(duration_seconds * SAMPLE_RATE)
        mixed: list[float] = [0.0] * n_samples
        vel_per_note = velocity / max(1, len(frequencies))

        for freq in frequencies:
            note_audio = self.render_note(freq, duration_seconds, vel_per_note)
            for i, s in enumerate(note_audio):
                if i < n_samples:
                    mixed[i] += s

        return mixed


@dataclass(frozen=True)
class DistortedGuitarSynth:
    """Distorted electric guitar synthesizer.

    Attributes:
        drive: Distortion drive amount.
        harmonics: Number of harmonics.
        attack: Pick attack time.
        decay: Note decay.
        sustain: Sustain level.
        release: Release time.
        cutoff_hz: Tone control cutoff.
        palm_mute: Enable palm muting effect.
    """

    drive: float = 3.0
    harmonics: int = 6
    attack: float = 0.005
    decay: float = 0.1
    sustain: float = 0.6
    release: float = 0.15
    cutoff_hz: float = 5000.0
    palm_mute: bool = False

    def render_note(
        self, freq: float, duration_seconds: float, velocity: float
    ) -> list[float]:
        """Render a distorted guitar note."""
        n_samples = int(duration_seconds * SAMPLE_RATE)
        raw: list[float] = [0.0] * n_samples

        for h in range(1, self.harmonics + 1):
            harmonic_freq = freq * h
            if harmonic_freq > SAMPLE_RATE / 2:
                break
            amp = velocity / (h**0.8)
            for i in range(n_samples):
                t = i / SAMPLE_RATE
                raw[i] += amp * math.sin(TWO_PI * harmonic_freq * t)

        distorted = _soft_clip(raw, self.drive)
        cutoff = self.cutoff_hz * (0.3 if self.palm_mute else 1.0)
        filtered = _low_pass_filter(distorted, cutoff, resonance=0.3)

        sustain_val = self.sustain * (0.3 if self.palm_mute else 1.0)
        decay_val = self.decay * (0.3 if self.palm_mute else 1.0)

        return _apply_envelope(
            filtered,
            self.attack,
            decay_val,
            sustain_val,
            self.release,
        )

    def render_chord(
        self,
        frequencies: tuple[float, ...],
        duration_seconds: float,
        velocity: float,
    ) -> list[float]:
        """Render a power chord."""
        n_samples = int(duration_seconds * SAMPLE_RATE)
        mixed: list[float] = [0.0] * n_samples
        vel_per_note = velocity / max(1, len(frequencies))

        for freq in frequencies:
            note_audio = self.render_note(freq, duration_seconds, vel_per_note)
            for i, s in enumerate(note_audio):
                if i < n_samples:
                    mixed[i] += s

        return mixed

"""Domain models for the ACE-Step vocal engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AceStepConfig:
    """Configuration for an ACE-Step music generation request.

    ACE-Step generates a full song (vocals + instruments) from a text
    prompt and lyrics.  Songmaker uses Demucs to extract just the vocals.

    Attributes:
        prompt: Style description (e.g. "emotional female vocal, piano ballad").
        lyrics: Song lyrics with section tags ([verse], [chorus], etc.).
        bpm: Tempo in beats per minute.
        duration: Target duration in seconds (10-600).
        key: Musical key (e.g. "Am", "C", "F#m").
        time_signature: Time signature string (e.g. "4/4", "3/4").
        vocal_language: Two-letter language code ("en", "de", "zh", etc.).
        instrumental: If True, generate without vocals.
        seed: Random seed (-1 = random).
        inference_steps: Denoising steps (8 for turbo, 50 for SFT).
        guidance_scale: Text adherence strength.
    """

    prompt: str
    lyrics: str
    bpm: int = 120
    duration: int = 60
    key: str = "Am"
    time_signature: str = "4/4"
    vocal_language: str = "en"
    instrumental: bool = False
    seed: int = -1
    inference_steps: int = 8
    guidance_scale: float = 15.0


@dataclass(frozen=True)
class AceStepResult:
    """Result from an ACE-Step generation.

    Attributes:
        samples: Audio samples at 44100 Hz, mono, in [-1.0, 1.0].
        sample_rate: Always 44100 (resampled from ACE-Step's native 48000).
        duration: Actual duration in seconds.
        seed: The seed that was used (useful for reproducibility).
    """

    samples: list[float]
    sample_rate: int
    duration: float
    seed: int

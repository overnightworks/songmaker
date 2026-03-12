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
        guidance_scale: CFG strength. 0.0 for turbo (no CFG), 5-9 for SFT/base.
        think_mode: Let the LM reason (CoT) before generating. Requires LM
            to be enabled on the server. Produces more coherent song structure.
    """

    prompt: str
    lyrics: str
    bpm: int | None = 120
    duration: int = 60
    key: str = ""
    time_signature: str = ""
    vocal_language: str = "en"
    instrumental: bool = False
    seed: int = -1
    inference_steps: int = 8
    # Turbo model (inference_steps=8) does not use CFG — set to 0.0.
    # SFT / base models use CFG; typical value 5.0-9.0.
    guidance_scale: float = 0.0
    # shift: flow matching shift parameter. 3.0 is recommended for all models.
    shift: float = 3.0
    # think_mode: let the LM reason (Chain-of-Thought) before generating.
    # Produces better-structured songs when the LM is enabled on the server.
    # Adds a few extra seconds of planning time.
    think_mode: bool = True
    # lm_temperature: LM sampling temperature. Higher = more creative/unpredictable.
    # Default 0.85. Try 1.1-1.2 for more "alive" sounding results.
    lm_temperature: float = 0.85
    # infer_method: "ode" (default, deterministic) or "sde" (adds stochastic noise,
    # more textured and "felt" output, less deterministic).
    infer_method: str = "ode"


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

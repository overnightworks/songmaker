"""Domain models for the ACE-Step music engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AceStepConfig:
    """Configuration for an ACE-Step music generation request."""

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
    guidance_scale: float = 0.0
    shift: float = 3.0
    think_mode: bool = True
    lm_temperature: float = 0.85
    infer_method: str = "ode"


@dataclass(frozen=True)
class AceStepResult:
    """Result from an ACE-Step generation.

    Contains raw WAV bytes from the server. The caller is responsible
    for decoding to numpy arrays via audio_engine.read_wav_bytes().
    """

    wav_bytes: bytes
    seed: int

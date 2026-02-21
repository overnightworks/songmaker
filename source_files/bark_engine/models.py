"""Domain models for the Bark vocal engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class VocalStyle(StrEnum):
    """Vocal processing style applied via ffmpeg post-processing."""

    SINGING = "singing"
    RAP = "rap"
    SPOKEN = "spoken"
    SHOUT = "shout"
    WHISPER = "whisper"
    EPIC = "epic"


class VocalLanguage(StrEnum):
    """Supported Bark voice languages."""

    GERMAN = "de"
    ENGLISH = "en"


@dataclass(frozen=True)
class VocalSection:
    """Immutable configuration for a single vocal section.

    Attributes:
        section_id: Unique identifier for this section.
        text: Raw lyrics text (♪ markers added automatically for singing).
        language: Voice language selection.
        speaker_index: Bark speaker preset index (0-9).
        style: Post-processing vocal style.
        singing: Whether to add ♪ markers for Bark singing mode.
        volume: Relative volume multiplier (0.0 - 1.0).
        gap_after_seconds: Silence gap after this section in seconds.
        num_takes: Number of takes to generate; best is auto-selected.
        pitch_correction_intensity: Correction strength (0.0=off, 1.0=hard snap).
        pitch_correction_key: Musical key for pitch quantization (C, C#, D, etc.).
        pitch_correction_scale: Scale type for quantization (major, minor, chromatic).
    """

    section_id: str
    text: str
    language: VocalLanguage = VocalLanguage.GERMAN
    speaker_index: int = 0
    style: VocalStyle = VocalStyle.SINGING
    singing: bool = True
    volume: float = 1.0
    gap_after_seconds: float = 0.5
    num_takes: int = 3
    pitch_correction_intensity: float = 0.7
    pitch_correction_key: str = "C"
    pitch_correction_scale: str = "minor"


@dataclass(frozen=True)
class GeneratedVocal:
    """Result of vocal generation.

    Attributes:
        section_id: Matches the input VocalSection.
        samples: Audio samples at TARGET_SAMPLE_RATE, normalized [-1.0, 1.0].
        volume: Volume multiplier from the section config.
        gap_after_seconds: Gap after this section.
    """

    section_id: str
    samples: list[float]
    volume: float
    gap_after_seconds: float

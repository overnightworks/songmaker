"""Data models for the DiffSinger engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class VocalNote:
    """A single sung note with lyrics and expression."""

    midi: int  # MIDI note number (60 = C4)
    lyric: str  # Syllable text (e.g. "hel", "lo")
    duration_beats: float  # Duration in beats
    velocity: float = 0.8  # Volume/energy 0.0-1.0
    breathiness: float = 0.0  # 0.0=clean, 1.0=breathy
    tension: float = 0.5  # 0.0=relaxed, 1.0=tense
    is_rest: bool = False  # Silent note


@dataclass(frozen=True)
class VocalPhrase:
    """A singable phrase: sequence of notes with lyrics at a given tempo."""

    phrase_id: str  # Unique ID for caching
    notes: tuple[VocalNote, ...]  # Sequence of notes
    bpm: float  # Tempo for beat→seconds conversion
    voice: str = "tiger"  # Voicebank name
    gender: float = 0.0  # Formant shift (-1=male, +1=female)
    pitch_shift: int = 0  # Semitone transposition
    seed: int = -1  # Reproducibility (-1=random)


@dataclass(frozen=True)
class DiffSingerResult:
    """Output from DiffSinger inference."""

    samples: np.ndarray  # 44100 Hz mono float32 [-1.0, 1.0]
    sample_rate: int  # Always 44100
    duration: float  # Seconds
    phrase_id: str  # Matches input phrase


@dataclass
class VoicebankConfig:
    """Parsed dsconfig.yaml for an OpenUTAU DiffSinger voicebank."""

    base_dir: Path
    phoneme_map: dict[str, int] = field(default_factory=dict)
    acoustic_path: Path | None = None
    linguistic_path: Path | None = None
    dur_path: Path | None = None
    pitch_path: Path | None = None
    variance_path: Path | None = None
    vocoder_dir: Path | None = None

    # Speaker
    speakers: list[str] = field(default_factory=list)
    hidden_size: int = 256

    # Feature flags
    use_lang_id: bool = False
    use_key_shift_embed: bool = False
    use_speed_embed: bool = False
    use_energy_embed: bool = False
    use_breathiness_embed: bool = False
    use_voicing_embed: bool = False
    use_tension_embed: bool = False
    use_expr: bool = False
    use_note_rest: bool = False
    use_continuous_acceleration: bool = True
    use_variable_depth: bool = False
    max_depth: float = 0.0

    # Variance prediction flags
    predict_dur: bool = False
    predict_energy: bool = False
    predict_breathiness: bool = False
    predict_voicing: bool = False
    predict_tension: bool = False

    # Audio spec
    sample_rate: int = 44100
    hop_size: int = 512
    num_mel_bins: int = 128
    mel_base: str = "e"
    mel_scale: str = "slaney"

    # Augmentation
    pitch_shift_range: tuple[float, float] = (-5.0, 5.0)

    @property
    def frame_ms(self) -> float:
        return 1000.0 * self.hop_size / self.sample_rate


@dataclass
class VocoderConfig:
    """Parsed vocoder.yaml."""

    model_path: Path | None = None
    sample_rate: int = 44100
    hop_size: int = 512
    num_mel_bins: int = 128
    mel_base: str = "e"
    mel_scale: str = "slaney"

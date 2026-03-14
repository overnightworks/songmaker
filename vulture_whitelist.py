"""Vulture whitelist — suppress false positives for intentionally unused code.

These are public API constants, enum values, dataclass fields, and methods
that are used by track scripts or are part of the library's public interface.

Usage: vulture source_files/ scripts/ tests/ vulture_whitelist.py
"""

# GM program constants (instrumental_engine/models.py)
# Track scripts select instruments from this library.
from instrumental_engine.models import GMProgram
GMProgram.BRIGHT_PIANO
GMProgram.ELECTRIC_PIANO
GMProgram.HARPSICHORD
GMProgram.NYLON_GUITAR
GMProgram.STEEL_GUITAR
GMProgram.ELECTRIC_GUITAR_CLEAN
GMProgram.ELECTRIC_GUITAR_MUTED
GMProgram.OVERDRIVEN_GUITAR
GMProgram.DISTORTION_GUITAR
GMProgram.ACOUSTIC_BASS
GMProgram.FINGERED_BASS
GMProgram.PICKED_BASS
GMProgram.SLAP_BASS
GMProgram.SYNTH_BASS_1
GMProgram.VIOLIN
GMProgram.VIOLA
GMProgram.CELLO
GMProgram.SYNTH_STRINGS
GMProgram.CHOIR_AAHS
GMProgram.VOICE_OOHS
GMProgram.TRUMPET
GMProgram.TROMBONE
GMProgram.FRENCH_HORN
GMProgram.BRASS_SECTION
GMProgram.SYNTH_LEAD_SQUARE
GMProgram.SYNTH_LEAD_SAW
GMProgram.SYNTH_PAD_WARM
GMProgram.SYNTH_PAD_CHOIR
GMProgram.SYNTH_PAD_SWEEP

# Note duration constants
from instrumental_engine.models import NoteDuration
NoteDuration.WHOLE
NoteDuration.HALF
NoteDuration.QUARTER
NoteDuration.EIGHTH
NoteDuration.SIXTEENTH
NoteDuration.DOTTED_HALF
NoteDuration.DOTTED_QUARTER
NoteDuration.TRIPLET_QUARTER
NoteDuration.TRIPLET_EIGHTH

# SectionType enum
from instrumental_engine.models import SectionType
SectionType.VERSE
SectionType.PRE_CHORUS
SectionType.BRIDGE
SectionType.DROP
SectionType.BREAKDOWN
SectionType.OUTRO
SectionType.BUILDUP
SectionType.SOLO

# VocalLanguage enum
from bark_engine.models import VocalLanguage
VocalLanguage.ENGLISH

# Frequency constants (module-level variables — must be "used" to suppress)
from instrumental_engine.constants import (
    FREQ_C3, FREQ_E3, FREQ_G3, FREQ_C4, FREQ_E4, FREQ_G4, FREQ_A4,
    MIDDLE_C_MIDI,
)
_ = FREQ_C3, FREQ_E3, FREQ_G3, FREQ_C4, FREQ_E4, FREQ_G4, FREQ_A4, MIDDLE_C_MIDI

# Dataclass fields used at construction
from instrumental_engine.models import SongSection, Arrangement
SongSection.section_type
SongSection.label
Arrangement.time_signature_numerator
Arrangement.time_signature_denominator

from instrumental_engine.soundfont_engine import SoundFontRenderer
SoundFontRenderer.render_sequence

# Soundfont validator internals
from instrumental_engine.soundfont_validator import SoundFontHealth
SoundFontHealth.fluidsynth_installed
SoundFontHealth.render_test_passed

"""Instrumental engine for Songmaker.

Package providing high-quality instrumental generation using:
- Pure-Python DSP synthesizers (supersaw, pad, pluck, bass, lead, piano, strings, guitar)
- FluidSynth SoundFont rendering (when available) for sampled instruments
- Synthesized drum machine with genre-specific pattern library
- Stereo mixer with panning, effects, and mastering
- Professional mastering chain (multiband compression, LUFS, stereo widening)
- Arrangement system for section-based song composition
- Vocal-instrumental ducking with smooth cosine envelopes

Public API:
    - render_and_export: Render arrangement to WAV/MP3
    - render_arrangement: Render arrangement to stereo samples
    - Arrangement, SongSection, InstrumentTrack: Song structure models
    - Note, Chord, Rest: Musical event types
    - DrumPattern, DrumHit, DrumSound: Drum configuration
    - PATTERN_LIBRARY: Pre-built drum patterns
    - SYNTH_REGISTRY: Available synthesizer instruments
    - apply_ducking: Vocal-instrumental ducking
    - master_stereo: Professional mastering pipeline
    - multiband_compress, measure_lufs, widen_stereo, soft_clip: Mastering components

Usage:
    from instrumental_engine import (
        Arrangement, SongSection, InstrumentTrack,
        Note, Chord, Rest, DrumSound, DrumHit, DrumPattern,
        PATTERN_LIBRARY, render_and_export,
    )

    arrangement = Arrangement(
        title="My Song",
        default_bpm=120,
        sections=(
            SongSection(
                section_type=SectionType.CHORUS,
                start_beat=0.0,
                length_beats=16.0,
                bpm=120,
                tracks=(
                    InstrumentTrack(
                        name="piano",
                        instrument_id="piano",
                        events=(Note(60), Note(64), Note(67)),
                    ),
                ),
                drum_pattern=PATTERN_LIBRARY["four_on_floor"],
            ),
        ),
    )
    render_and_export(arrangement, "output/my_song")
"""

from instrumental_engine.arrangement_engine import (
    SYNTH_REGISTRY,
    render_and_export,
    render_arrangement,
    render_section,
    render_track,
)
from instrumental_engine.constants import (
    SAMPLE_RATE,
    midi_to_freq,
    note_name_to_midi,
    note_to_freq,
)
from instrumental_engine.drum_machine import (
    PATTERN_LIBRARY,
    render_drum_hit,
    render_drum_pattern,
    repeat_pattern,
)
from instrumental_engine.ducking import apply_ducking
from instrumental_engine.effects import (
    apply_chorus,
    apply_delay,
    apply_reverb,
    apply_sidechain_compression,
    apply_stereo_widener,
    generate_impact,
    generate_noise_sweep,
)
from instrumental_engine.mastering import (
    master_stereo,
    measure_lufs,
    multiband_compress,
    normalize_to_lufs,
    soft_clip,
    widen_stereo,
)
from instrumental_engine.mixer import (
    apply_fade_out_stereo,
    apply_pan,
    master_to_mp3,
    mix_stereo_tracks,
    normalize_stereo,
    stereo_to_mono,
    write_mono_wav,
    write_stereo_wav,
)
from instrumental_engine.models import (
    Arrangement,
    Chord,
    DrumHit,
    DrumPattern,
    DrumSound,
    GMProgram,
    InstrumentTrack,
    Note,
    NoteLength,
    PanPosition,
    RenderedTrack,
    Rest,
    SectionType,
    SongSection,
)
from instrumental_engine.soundfont_engine import (
    SoundFontRenderer,
    find_soundfont,
    is_fluidsynth_available,
    require_fluidsynth,
)
from instrumental_engine.soundfont_validator import (
    SoundFontHealth,
    SoundFontSetupError,
    check_soundfont_health,
    require_soundfont_setup,
)
from instrumental_engine.synth_instruments import (
    DistortedGuitarSynth,
    LeadSynth,
    PadSynth,
    PianoSynth,
    PluckSynth,
    StringsSynth,
    SubBassSynth,
    SupersawSynth,
)

__all__ = [
    # Core rendering
    "render_and_export",
    "render_arrangement",
    "render_section",
    "render_track",
    "SYNTH_REGISTRY",
    # Ducking
    "apply_ducking",
    # Constants
    "SAMPLE_RATE",
    "midi_to_freq",
    "note_to_freq",
    "note_name_to_midi",
    # Models
    "Arrangement",
    "SongSection",
    "SectionType",
    "InstrumentTrack",
    "Note",
    "Chord",
    "Rest",
    "NoteLength",
    "PanPosition",
    "GMProgram",
    "RenderedTrack",
    # Drums
    "DrumPattern",
    "DrumHit",
    "DrumSound",
    "PATTERN_LIBRARY",
    "render_drum_hit",
    "render_drum_pattern",
    "repeat_pattern",
    # Effects
    "apply_reverb",
    "apply_delay",
    "apply_chorus",
    "apply_sidechain_compression",
    "apply_stereo_widener",
    "generate_noise_sweep",
    "generate_impact",
    # Mixer
    "apply_pan",
    "mix_stereo_tracks",
    "normalize_stereo",
    "write_stereo_wav",
    "write_mono_wav",
    "stereo_to_mono",
    "apply_fade_out_stereo",
    "master_to_mp3",
    # Mastering
    "master_stereo",
    "multiband_compress",
    "measure_lufs",
    "normalize_to_lufs",
    "widen_stereo",
    "soft_clip",
    # SoundFont
    "SoundFontRenderer",
    "find_soundfont",
    "is_fluidsynth_available",
    "require_fluidsynth",
    # SoundFont validation
    "SoundFontHealth",
    "SoundFontSetupError",
    "check_soundfont_health",
    "require_soundfont_setup",
    # Synth instruments
    "SupersawSynth",
    "PadSynth",
    "PluckSynth",
    "SubBassSynth",
    "LeadSynth",
    "PianoSynth",
    "StringsSynth",
    "DistortedGuitarSynth",
]

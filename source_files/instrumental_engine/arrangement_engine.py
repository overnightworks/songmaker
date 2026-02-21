"""Arrangement engine: renders complete songs from section definitions.

Orchestrates synth instruments, drum machine, SoundFont rendering,
effects processing, and stereo mixing into finished instrumentals.
"""

from __future__ import annotations

from typing import Final

from instrumental_engine.constants import SAMPLE_RATE, midi_to_freq
from instrumental_engine.drum_machine import repeat_pattern
from instrumental_engine.mixer import (
    apply_fade_out_stereo,
    apply_limiter,
    apply_pan,
    master_to_mp3,
    mix_stereo_tracks,
    normalize_stereo,
    overlay_onto,
    write_stereo_wav,
)
from instrumental_engine.models import (
    Arrangement,
    Chord,
    InstrumentRenderer,
    InstrumentTrack,
    Note,
    PanPosition,
    RenderedTrack,
    Rest,
    SongSection,
)
from instrumental_engine.soundfont_engine import (
    SoundFontRenderer,
    find_soundfont,
    require_fluidsynth,
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

SYNTH_REGISTRY: Final[dict[str, InstrumentRenderer]] = {
    "supersaw": SupersawSynth(),
    "pad": PadSynth(),
    "pluck": PluckSynth(),
    "sub_bass": SubBassSynth(),
    "lead": LeadSynth(),
    "piano": PianoSynth(),
    "strings": StringsSynth(),
    "distorted_guitar": DistortedGuitarSynth(),
    "power_guitar": DistortedGuitarSynth(drive=4.0, palm_mute=False),
    "palm_mute_guitar": DistortedGuitarSynth(drive=2.5, palm_mute=True),
    "bright_piano": PianoSynth(brightness=0.9, harmonics=12),
    "dark_pad": PadSynth(warmth=0.8, cutoff_hz=2500.0, attack=0.6),
    "synth_lead_saw": LeadSynth(saw_mix=1.0, cutoff_hz=8000.0),
    "synth_lead_square": LeadSynth(saw_mix=0.0, cutoff_hz=5000.0),
    "warm_strings": StringsSynth(voices_per_note=4, detune_cents=10.0),
    "808_bass": SubBassSynth(saturation=2.5, sub_octave_mix=0.5),
}


def _resolve_instrument(
    instrument_id: str, track: InstrumentTrack
) -> InstrumentRenderer:
    """Resolve instrument ID to a renderer.

    For ``sf:*`` instruments, requires FluidSynth and a SoundFont file.
    Raises descriptive errors with setup instructions if unavailable.

    For DSP synth instruments, returns the registered synth directly.

    Args:
        instrument_id: Instrument identifier string.
        track: Track configuration with GM program info.

    Returns:
        An InstrumentRenderer implementation.

    Raises:
        RuntimeError: If ``sf:*`` requested but FluidSynth not installed.
        FileNotFoundError: If ``sf:*`` requested but no SoundFont found.
        ValueError: If instrument_id is not recognized.
    """
    if instrument_id.startswith("sf:"):
        require_fluidsynth()
        sf_path = find_soundfont(gm_program=int(track.gm_program))
        return SoundFontRenderer(
            soundfont_path=sf_path,
            gm_program=track.gm_program,
        )

    synth = SYNTH_REGISTRY.get(instrument_id)
    if synth is not None:
        return synth

    available = ", ".join(sorted(SYNTH_REGISTRY.keys()))
    raise ValueError(
        f"Unknown instrument_id: {instrument_id!r}. "
        f"Available DSP synths: {available}. "
        f"For SoundFont instruments, use 'sf:' prefix (e.g. 'sf:piano')."
    )


def render_track(track: InstrumentTrack, bpm: int, total_beats: float) -> RenderedTrack:
    """Render a single instrument track to stereo audio.

    Args:
        track: Track configuration with note events.
        bpm: Tempo in beats per minute.
        total_beats: Total duration in beats.

    Returns:
        Rendered stereo audio track.
    """
    seconds_per_beat = 60.0 / bpm
    total_seconds = total_beats * seconds_per_beat
    total_samples = int(total_seconds * SAMPLE_RATE)

    instrument = _resolve_instrument(track.instrument_id, track)
    mono: list[float] = [0.0] * total_samples
    current_beat = 0.0

    for event in track.events:
        start_sample = int(current_beat * seconds_per_beat * SAMPLE_RATE)

        if isinstance(event, Note):
            freq = midi_to_freq(event.midi)
            dur_seconds = event.duration_beats * seconds_per_beat
            audio = instrument.render_note(freq, dur_seconds, event.velocity)
            _overlay_mono(mono, audio, start_sample)
            current_beat += event.duration_beats

        elif isinstance(event, Chord):
            freqs = tuple(midi_to_freq(n) for n in event.notes)
            dur_seconds = event.duration_beats * seconds_per_beat
            audio = instrument.render_chord(freqs, dur_seconds, event.velocity)
            _overlay_mono(mono, audio, start_sample)
            current_beat += event.duration_beats

        elif isinstance(event, Rest):
            current_beat += event.duration_beats

    left, right = apply_pan(mono, track.pan)
    return RenderedTrack(
        name=track.name,
        samples_left=left,
        samples_right=right,
        volume=track.volume,
    )


def render_section(section: SongSection) -> tuple[list[float], list[float]]:
    """Render a complete song section to stereo audio.

    Args:
        section: Section configuration with tracks and drums.

    Returns:
        Tuple of (left, right) stereo audio for this section.
    """
    rendered_tracks: list[RenderedTrack] = []

    for track in section.tracks:
        rendered = render_track(track, section.bpm, section.length_beats)
        rendered_tracks.append(rendered)

    if section.drum_pattern is not None:
        drum_audio = repeat_pattern(
            section.drum_pattern,
            section.bpm,
            section.length_beats,
        )
        drum_left, drum_right = apply_pan(drum_audio, PanPosition.CENTER)
        rendered_tracks.append(
            RenderedTrack(
                name="drums",
                samples_left=drum_left,
                samples_right=drum_right,
                volume=0.8,
            )
        )

    return mix_stereo_tracks(rendered_tracks)


def render_arrangement(arrangement: Arrangement) -> tuple[list[float], list[float]]:
    """Render a complete song arrangement to stereo audio.

    Args:
        arrangement: Full arrangement with all sections.

    Returns:
        Tuple of (left, right) stereo master audio.
    """
    seconds_per_beat = 60.0 / arrangement.default_bpm
    total_beats = sum(s.length_beats for s in arrangement.sections)
    total_samples = int(total_beats * seconds_per_beat * SAMPLE_RATE)

    master_left: list[float] = [0.0] * total_samples
    master_right: list[float] = [0.0] * total_samples

    for section in arrangement.sections:
        section_bpm = section.bpm if section.bpm > 0 else arrangement.default_bpm
        section_spb = 60.0 / section_bpm
        start_sample = int(section.start_beat * section_spb * SAMPLE_RATE)

        section_left, section_right = render_section(section)
        overlay_onto(
            master_left,
            master_right,
            section_left,
            section_right,
            start_sample,
        )

    left_limited = apply_limiter(master_left)
    right_limited = apply_limiter(master_right)
    return normalize_stereo(left_limited, right_limited, 0.95)


def render_and_export(
    arrangement: Arrangement,
    output_path: str,
    fade_out_seconds: float = 4.0,
    export_mp3: bool = True,
) -> str:
    """Render arrangement and export to WAV/MP3.

    Args:
        arrangement: Complete song arrangement.
        output_path: Output file path (without extension).
        fade_out_seconds: Fade out duration (0 to disable).
        export_mp3: Whether to also export MP3.

    Returns:
        Path to the output file (MP3 if exported, else WAV).
    """
    print(f"   🎵 Rendering: {arrangement.title}")
    left, right = render_arrangement(arrangement)

    if fade_out_seconds > 0:
        left, right = apply_fade_out_stereo(left, right, fade_out_seconds)

    wav_path = f"{output_path}.wav"
    write_stereo_wav(wav_path, left, right)
    duration = len(left) / SAMPLE_RATE
    print(f"   ✅ WAV written: {wav_path} ({duration:.1f}s)")

    if export_mp3:
        mp3_path = f"{output_path}.mp3"
        if master_to_mp3(wav_path, mp3_path):
            print(f"   ✅ MP3 exported: {mp3_path}")
            return mp3_path

    return wav_path


def _overlay_mono(base: list[float], addition: list[float], start: int) -> None:
    """Overlay audio onto mono base buffer at position."""
    for i, val in enumerate(addition):
        pos = start + i
        if 0 <= pos < len(base):
            base[pos] += val

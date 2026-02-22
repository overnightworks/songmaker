"""Convert VocalPhrase → DiffSinger inference tensors."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .models import VocalNote, VocalPhrase, VoicebankConfig
from .phonemizer import phonemize_word

# Silence/breath phoneme tokens
AP = "AP"  # Aspiration/breath
SP = "SP"  # Silence/pause

# Head/tail padding frames (matches OpenUTAU convention)
HEAD_FRAMES = 8
TAIL_FRAMES = 8


def midi_to_hz(midi: float) -> float:
    """Convert MIDI note number to frequency in Hz."""
    return 440.0 * (2.0 ** ((midi - 69.0) / 12.0))


def beats_to_seconds(beats: float, bpm: float) -> float:
    """Convert beats to seconds at given BPM."""
    return beats * 60.0 / bpm


def seconds_to_frames(seconds: float, frame_ms: float) -> int:
    """Convert seconds to frame count."""
    return max(1, round(seconds * 1000.0 / frame_ms))


@dataclass
class InferenceTensors:
    """Prepared tensors for ONNX inference."""

    tokens: np.ndarray  # int64 (1, n_tokens) — phoneme token IDs
    durations: np.ndarray  # int64 (1, n_tokens) — frame durations per phoneme
    f0_hz: np.ndarray  # float32 (1, n_frames) — pitch in Hz
    n_frames: int  # Total number of frames

    # Optional expression curves (per-frame)
    energy: np.ndarray | None = None  # float32 (1, n_frames)
    breathiness: np.ndarray | None = None  # float32 (1, n_frames)
    tension: np.ndarray | None = None  # float32 (1, n_frames)
    gender: np.ndarray | None = None  # float32 (1, n_frames)

    # Note-level data (for pitch predictor)
    note_midi: np.ndarray | None = None  # float32 (1, n_notes)
    note_dur: np.ndarray | None = None  # int64 (1, n_notes)
    note_rest: np.ndarray | None = None  # bool (1, n_notes)

    # Speaker embedding
    spk_embed: np.ndarray | None = None  # float32 (1, n_frames, hidden_size)


def build_tensors(
    phrase: VocalPhrase,
    config: VoicebankConfig,
    speaker_embed: np.ndarray | None = None,
) -> InferenceTensors:
    """Build inference tensors from a VocalPhrase.

    This converts the high-level note+lyric representation into the
    low-level tensor format that DiffSinger ONNX models expect.
    """
    phoneme_map = config.phoneme_map
    frame_ms = config.frame_ms

    # Step 1: Phonemize each note and build token/duration sequences
    all_phonemes: list[str] = []  # flat phoneme list
    all_durations_sec: list[float] = []  # duration per phoneme in seconds
    all_midi: list[float] = []  # MIDI note per phoneme
    ph_num_per_note: list[int] = []  # phonemes per note (for note_dur alignment)
    note_midis: list[float] = []  # MIDI per note
    note_durs_sec: list[float] = []  # seconds per note
    note_rests: list[bool] = []  # rest flags per note

    # Add breath at start
    all_phonemes.append(AP)
    breath_dur = 0.1  # 100ms breath
    all_durations_sec.append(breath_dur)
    all_midi.append(60.0)  # placeholder MIDI for breath

    for note in phrase.notes:
        note_dur_sec = beats_to_seconds(note.duration_beats, phrase.bpm)
        note_midi = float(note.midi + phrase.pitch_shift)

        note_midis.append(note_midi)
        note_durs_sec.append(note_dur_sec)
        note_rests.append(note.is_rest)

        if note.is_rest:
            # Rest = SP token
            all_phonemes.append(SP)
            all_durations_sec.append(note_dur_sec)
            all_midi.append(note_midi)
            ph_num_per_note.append(1)
        else:
            # Phonemize the lyric
            result = phonemize_word(note.lyric)
            if not result.phonemes:
                # Fallback: use the lyric text as-is if g2p fails
                all_phonemes.append(SP)
                all_durations_sec.append(note_dur_sec)
                all_midi.append(note_midi)
                ph_num_per_note.append(1)
            else:
                n_ph = len(result.phonemes)
                ph_num_per_note.append(n_ph)
                # Distribute note duration across phonemes
                # Consonants get a fixed short duration, vowels get the rest
                consonant_dur = min(0.06, note_dur_sec / (n_ph + 1))
                vowel_indices = []
                for i, ph in enumerate(result.phonemes):
                    if ph in _VOWELS:
                        vowel_indices.append(i)

                if vowel_indices:
                    consonant_total = consonant_dur * (n_ph - len(vowel_indices))
                    vowel_dur = (note_dur_sec - consonant_total) / len(vowel_indices)
                else:
                    # All consonants — distribute evenly
                    vowel_dur = 0
                    consonant_dur = note_dur_sec / n_ph

                for i, ph in enumerate(result.phonemes):
                    all_phonemes.append(ph)
                    if ph in _VOWELS:
                        all_durations_sec.append(max(0.02, vowel_dur))
                    else:
                        all_durations_sec.append(consonant_dur)
                    all_midi.append(note_midi)

    # Add silence at end
    all_phonemes.append(SP)
    all_durations_sec.append(0.1)
    all_midi.append(60.0)

    # Step 2: Pad with SP tokens (matches OpenUTAU convention)
    padded_phonemes = [SP] + all_phonemes + [SP]
    padded_midi = [60.0] + all_midi + [60.0]

    # Convert phonemes to token IDs
    token_ids = []
    for ph in padded_phonemes:
        if ph in phoneme_map:
            token_ids.append(phoneme_map[ph])
        elif ph.lower() in phoneme_map:
            token_ids.append(phoneme_map[ph.lower()])
        else:
            # Unknown phoneme → SP
            token_ids.append(phoneme_map.get(SP, phoneme_map.get("SP", 0)))

    # Convert durations to frames
    padded_durations_sec = [HEAD_FRAMES * frame_ms / 1000.0] + all_durations_sec + [TAIL_FRAMES * frame_ms / 1000.0]
    dur_frames = []
    for dur_sec in padded_durations_sec:
        dur_frames.append(seconds_to_frames(dur_sec, frame_ms))

    n_tokens = len(token_ids)
    n_frames = sum(dur_frames)

    # Step 3: Build f0 curve (Hz per frame)
    f0_frames = []
    frame_idx = 0
    for i, n_fr in enumerate(dur_frames):
        midi_val = padded_midi[i]
        hz = midi_to_hz(midi_val) if midi_val > 0 else 0.0
        for _ in range(n_fr):
            f0_frames.append(hz)
        frame_idx += n_fr

    # Step 4: Build expression curves if needed
    energy = None
    breathiness = None
    tension_arr = None
    gender_arr = None

    if config.use_energy_embed:
        # Build per-frame energy from note velocities
        energy_frames = _expand_note_values_to_frames(
            phrase.notes, dur_frames, padded_durations_sec, frame_ms,
            default=0.5, attr="velocity"
        )
        energy = np.array(energy_frames, dtype=np.float32).reshape(1, -1)

    if config.use_breathiness_embed:
        breathiness_frames = _expand_note_values_to_frames(
            phrase.notes, dur_frames, padded_durations_sec, frame_ms,
            default=0.0, attr="breathiness"
        )
        breathiness = np.array(breathiness_frames, dtype=np.float32).reshape(1, -1)

    if config.use_tension_embed:
        tension_frames = _expand_note_values_to_frames(
            phrase.notes, dur_frames, padded_durations_sec, frame_ms,
            default=0.5, attr="tension"
        )
        tension_arr = np.array(tension_frames, dtype=np.float32).reshape(1, -1)

    if config.use_key_shift_embed:
        gender_arr = np.full((1, n_frames), phrase.gender, dtype=np.float32)

    # Step 5: Build note-level arrays (for pitch predictor)
    # Prepend a copy of first note (OpenUTAU convention)
    note_midi_arr = np.array(
        [note_midis[0] if note_midis else 60.0] + note_midis,
        dtype=np.float32
    ).reshape(1, -1)

    note_dur_frames = []
    for dur_sec in note_durs_sec:
        note_dur_frames.append(seconds_to_frames(dur_sec, frame_ms))
    # Prepend head frames, append tail frames
    note_dur_arr = np.array(
        [HEAD_FRAMES] + note_dur_frames + [TAIL_FRAMES],
        dtype=np.int64
    ).reshape(1, -1)

    note_rest_arr = np.array(
        [True] + note_rests + [True],
        dtype=bool
    ).reshape(1, -1)

    # Step 6: Speaker embedding
    spk_embed = None
    if speaker_embed is not None:
        # Expand to (1, n_frames, hidden_size)
        spk_embed = np.tile(
            speaker_embed.reshape(1, 1, -1),
            (1, n_frames, 1)
        ).astype(np.float32)

    tokens = np.array(token_ids, dtype=np.int64).reshape(1, -1)
    durations = np.array(dur_frames, dtype=np.int64).reshape(1, -1)
    f0_hz = np.array(f0_frames[:n_frames], dtype=np.float32).reshape(1, -1)

    return InferenceTensors(
        tokens=tokens,
        durations=durations,
        f0_hz=f0_hz,
        n_frames=n_frames,
        energy=energy,
        breathiness=breathiness,
        tension=tension_arr,
        gender=gender_arr,
        note_midi=note_midi_arr,
        note_dur=note_dur_arr,
        note_rest=note_rest_arr,
        spk_embed=spk_embed,
    )


def _expand_note_values_to_frames(
    notes: tuple[VocalNote, ...],
    dur_frames: list[int],
    padded_durations_sec: list[float],
    frame_ms: float,
    default: float,
    attr: str,
) -> list[float]:
    """Expand per-note attribute values to per-frame values."""
    frames = []

    # Head padding
    head_frames = dur_frames[0]
    frames.extend([default] * head_frames)

    # Breath at start
    breath_frames = dur_frames[1]
    frames.extend([default] * breath_frames)

    # Note phonemes
    frame_offset = 2  # skip SP pad + AP breath
    for note in notes:
        note_dur_sec = beats_to_seconds(note.duration_beats, 120)  # approx
        val = getattr(note, attr, default)
        if note.is_rest:
            n_fr = dur_frames[frame_offset] if frame_offset < len(dur_frames) else 1
            frames.extend([default] * n_fr)
            frame_offset += 1
        else:
            result = phonemize_word(note.lyric)
            n_ph = max(1, len(result.phonemes))
            for _ in range(n_ph):
                if frame_offset < len(dur_frames):
                    n_fr = dur_frames[frame_offset]
                    frames.extend([val] * n_fr)
                    frame_offset += 1

    # Fill remaining frames
    target_len = sum(dur_frames)
    while len(frames) < target_len:
        frames.append(default)

    return frames[:target_len]


# ARPAbet vowels (DiffSinger lowercase format)
_VOWELS = {
    "aa", "ae", "ah", "ao", "aw", "ax", "ay",
    "eh", "er", "ey",
    "ih", "iy",
    "ow", "oy",
    "uh", "uw",
}

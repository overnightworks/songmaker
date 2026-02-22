"""Convert VocalPhrase → DiffSinger inference tensors for the full 4-stage pipeline.

Pipeline stages:
  1. Linguistic encoder: tokens + word_div + word_dur → encoder_out
  2. Duration predictor: encoder_out + ph_midi + spk_embed → ph_dur_pred
  3. Pitch predictor: encoder_out + ph_dur + note_midi/dur/rest + expr + retake → pitch_pred
  4. Acoustic model: tokens + durations + f0 + gender + velocity + spk_embed → mel
  5. Vocoder: mel + f0 → waveform
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
class PhraseTensors:
    """All tensors needed across the full inference pipeline."""

    # Phoneme-level (for linguistic encoder + acoustic)
    tokens: np.ndarray  # int64 (1, n_tokens)
    n_tokens: int

    # Word-level (for linguistic encoder with predict_dur=true)
    word_div: np.ndarray  # int64 (1, n_words) — phonemes per word
    word_dur: np.ndarray  # int64 (1, n_words) — frames per word

    # Phoneme-level MIDI (for duration predictor)
    ph_midi: np.ndarray  # int64 (1, n_tokens) — MIDI note per phoneme

    # Note-level (for pitch predictor)
    note_midi: np.ndarray  # float32 (1, n_notes)
    note_dur: np.ndarray  # int64 (1, n_notes) — frames per note
    note_rest: np.ndarray  # bool (1, n_notes)

    # Per-phoneme durations (fallback if dur predictor not used)
    ph_dur: np.ndarray  # int64 (1, n_tokens) — frame durations per phoneme
    n_frames: int

    # Expression (for pitch predictor, per-frame)
    expr: float = 1.0  # 0-1, applied uniformly

    # Phrase-level metadata
    gender: float = 0.0
    velocity: float = 0.8

    # Per-phoneme info for building note_midi/note_dur/note_rest
    # (intermediate, used to map phonemes to notes)
    _phoneme_midi: list[float] = field(default_factory=list, repr=False)


def build_phrase_tensors(
    phrase: VocalPhrase,
    config: VoicebankConfig,
) -> PhraseTensors:
    """Build tensors from a VocalPhrase for the full pipeline.

    This produces all the tensors needed by the linguistic encoder,
    duration predictor, pitch predictor, and acoustic model.
    """
    phoneme_map = config.phoneme_map
    frame_ms = config.frame_ms

    # ── Step 1: Phonemize notes → flat phoneme sequence ──────────
    # The phoneme sequence is: SP(head) AP <note phonemes...> SP SP(tail)
    all_phonemes: list[str] = []
    all_midi: list[float] = []  # MIDI per phoneme
    all_dur_sec: list[float] = []  # duration per phoneme in seconds
    is_vowel: list[bool] = []  # whether each phoneme is a vowel (for word_div)

    # Note-level data
    note_midis: list[float] = []
    note_durs_sec: list[float] = []
    note_rests: list[bool] = []
    note_ph_counts: list[int] = []  # phonemes per note

    # Leading breath
    all_phonemes.append(AP)
    all_midi.append(0.0)  # rest/breath
    all_dur_sec.append(0.12)  # 120ms breath
    is_vowel.append(True)  # AP counts as vowel for word_div

    for note in phrase.notes:
        note_dur_sec = beats_to_seconds(note.duration_beats, phrase.bpm)
        note_midi_val = float(note.midi + phrase.pitch_shift) if not note.is_rest else 0.0

        note_midis.append(float(note.midi + phrase.pitch_shift) if not note.is_rest else 0.0)
        note_durs_sec.append(note_dur_sec)
        note_rests.append(note.is_rest)

        if note.is_rest:
            all_phonemes.append(SP)
            all_midi.append(0.0)
            all_dur_sec.append(note_dur_sec)
            is_vowel.append(True)  # SP counts as vowel for word_div
            note_ph_counts.append(1)
        else:
            result = phonemize_word(note.lyric)
            if not result.phonemes:
                # Fallback
                all_phonemes.append(SP)
                all_midi.append(note_midi_val)
                all_dur_sec.append(note_dur_sec)
                is_vowel.append(True)
                note_ph_counts.append(1)
            else:
                n_ph = len(result.phonemes)
                note_ph_counts.append(n_ph)
                # Distribute duration: consonants get short fixed, vowels get remainder
                consonant_dur = min(0.10, note_dur_sec / (n_ph + 1))
                vowel_idxs = [i for i, ph in enumerate(result.phonemes) if ph in _VOWELS]

                if vowel_idxs:
                    consonant_total = consonant_dur * (n_ph - len(vowel_idxs))
                    vowel_dur = (note_dur_sec - consonant_total) / len(vowel_idxs)
                else:
                    vowel_dur = 0
                    consonant_dur = note_dur_sec / n_ph

                for i, ph in enumerate(result.phonemes):
                    all_phonemes.append(ph)
                    all_midi.append(note_midi_val)
                    is_vowel.append(ph in _VOWELS)
                    if ph in _VOWELS:
                        all_dur_sec.append(max(0.02, vowel_dur))
                    else:
                        all_dur_sec.append(consonant_dur)

    # Trailing silence
    all_phonemes.append(SP)
    all_midi.append(0.0)
    all_dur_sec.append(0.12)
    is_vowel.append(True)

    # ── Step 2: Add head/tail SP padding ─────────────────────────
    padded_phonemes = [SP] + all_phonemes + [SP]
    padded_midi = [0.0] + all_midi + [0.0]
    padded_is_vowel = [True] + is_vowel + [True]

    head_dur_sec = HEAD_FRAMES * frame_ms / 1000.0
    tail_dur_sec = TAIL_FRAMES * frame_ms / 1000.0
    padded_dur_sec = [head_dur_sec] + all_dur_sec + [tail_dur_sec]

    # ── Step 3: Convert to token IDs ─────────────────────────────
    token_ids = []
    for ph in padded_phonemes:
        if ph in phoneme_map:
            token_ids.append(phoneme_map[ph])
        elif ph.lower() in phoneme_map:
            token_ids.append(phoneme_map[ph.lower()])
        else:
            token_ids.append(phoneme_map.get(SP, phoneme_map.get("SP", 0)))

    n_tokens = len(token_ids)

    # ── Step 4: Convert durations to frames ──────────────────────
    dur_frames = [seconds_to_frames(d, frame_ms) for d in padded_dur_sec]
    n_frames = sum(dur_frames)

    # ── Step 5: Build word_div and word_dur ──────────────────────
    # Words are defined by splitting at vowel boundaries (OpenUTAU convention).
    # Find vowel positions in the padded phoneme sequence.
    vowel_positions = [i for i, v in enumerate(padded_is_vowel) if v]

    if len(vowel_positions) < 2:
        # Degenerate case — treat entire sequence as one word
        word_div_list = [n_tokens]
        word_dur_list = [n_frames]
    else:
        word_div_list = []
        word_dur_list = []

        # First word: from start to (but not including) second vowel
        word_div_list.append(vowel_positions[1])
        word_dur_list.append(sum(dur_frames[:vowel_positions[1]]))

        # Middle words: between consecutive vowels
        for j in range(1, len(vowel_positions) - 1):
            count = vowel_positions[j + 1] - vowel_positions[j]
            frames = sum(dur_frames[vowel_positions[j]:vowel_positions[j + 1]])
            word_div_list.append(count)
            word_dur_list.append(frames)

        # Last word: from last vowel to end
        last_v = vowel_positions[-1]
        count = n_tokens - last_v
        frames = sum(dur_frames[last_v:])
        word_div_list.append(count)
        word_dur_list.append(frames)

    # ── Step 6: Build note-level arrays for pitch predictor ──────
    # Include head rest + notes + tail rest
    # Rest notes: set MIDI to nearest non-rest neighbor
    full_note_midis = []
    full_note_durs_sec = []
    full_note_rests = []

    # Head rest
    full_note_midis.append(0.0)
    full_note_durs_sec.append(head_dur_sec + 0.12)  # head pad + breath
    full_note_rests.append(True)

    for midi_val, dur_s, is_rest in zip(note_midis, note_durs_sec, note_rests):
        full_note_midis.append(midi_val)
        full_note_durs_sec.append(dur_s)
        full_note_rests.append(is_rest)

    # Tail rest
    full_note_midis.append(0.0)
    full_note_durs_sec.append(0.12 + tail_dur_sec)  # trailing SP + tail pad
    full_note_rests.append(True)

    # Fill rest note MIDIs with nearest non-rest neighbor
    non_rest_midi = 60.0  # fallback
    for i, (m, r) in enumerate(zip(full_note_midis, full_note_rests)):
        if not r and m > 0:
            non_rest_midi = m
            break
    for i in range(len(full_note_midis)):
        if full_note_rests[i] or full_note_midis[i] <= 0:
            full_note_midis[i] = non_rest_midi
        else:
            non_rest_midi = full_note_midis[i]

    note_dur_frames = [seconds_to_frames(d, frame_ms) for d in full_note_durs_sec]

    # Adjust note durations to sum to n_frames
    note_total = sum(note_dur_frames)
    if note_total != n_frames:
        diff = n_frames - note_total
        # Add/subtract from the longest note
        longest_idx = note_dur_frames.index(max(note_dur_frames))
        note_dur_frames[longest_idx] += diff

    # ── Step 7: Build ph_midi (per-phoneme MIDI for dur predictor) ──
    ph_midi_list = []
    for midi_val in padded_midi:
        if midi_val <= 0:
            ph_midi_list.append(60)  # placeholder for rest/breath
        else:
            ph_midi_list.append(round(midi_val))

    # ── Assemble tensors ─────────────────────────────────────────
    tokens = np.array(token_ids, dtype=np.int64).reshape(1, -1)
    ph_dur = np.array(dur_frames, dtype=np.int64).reshape(1, -1)
    word_div = np.array(word_div_list, dtype=np.int64).reshape(1, -1)
    word_dur = np.array(word_dur_list, dtype=np.int64).reshape(1, -1)
    ph_midi = np.array(ph_midi_list, dtype=np.int64).reshape(1, -1)
    note_midi = np.array(full_note_midis, dtype=np.float32).reshape(1, -1)
    note_dur = np.array(note_dur_frames, dtype=np.int64).reshape(1, -1)
    note_rest = np.array(full_note_rests, dtype=bool).reshape(1, -1)

    # Average velocity from notes
    velocities = [n.velocity for n in phrase.notes if not n.is_rest]
    avg_velocity = sum(velocities) / len(velocities) if velocities else 0.8

    return PhraseTensors(
        tokens=tokens,
        n_tokens=n_tokens,
        word_div=word_div,
        word_dur=word_dur,
        ph_midi=ph_midi,
        note_midi=note_midi,
        note_dur=note_dur,
        note_rest=note_rest,
        ph_dur=ph_dur,
        n_frames=n_frames,
        expr=1.0,
        gender=phrase.gender,
        velocity=avg_velocity,
        _phoneme_midi=padded_midi,
    )


# ARPAbet vowels (DiffSinger lowercase format)
_VOWELS = {
    "aa", "ae", "ah", "ao", "aw", "ax", "ay",
    "eh", "er", "ey",
    "ih", "iy",
    "ow", "oy",
    "uh", "uw",
}

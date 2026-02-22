# DiffSinger Integration Plan

## Context

Songmaker currently uses Bark for vocal generation, which produces speech-quality audio — not singing. ACE-Step generates full songs but the VAE decode is too slow on our 6GB GPU, and we'd need Demucs to extract vocals (quality loss).

DiffSinger solves this: it generates **isolated singing vocals** from MIDI notes + phonemes, with full control over pitch, timing, breathiness, tension, and vibrato. Claude writes the Python scripts that feed DiffSinger — no manual GUI work needed. This makes Songmaker a true vocal production pipeline.

## Architecture

```
Track script defines:
  - VocalTrack with Note events + lyrics per syllable
  - Voice model (TIGER English voicebank)
  - Expression parameters (breathiness, tension, etc.)
         |
         v
diffsinger_engine converts to .ds format:
  - Lyrics -> phonemes (via g2p_en)
  - Note events -> note_seq, note_dur
  - Beat timing -> seconds
         |
         v
DiffSinger inference (2 stages):
  1. Variance model: predicts timing, pitch curves, expression
  2. Acoustic model: generates 44.1kHz mono WAV
         |
         v
Optional: RVC voice conversion (already exists)
         |
         v
Mix with Songmaker instrumentals -> Master -> MP3
```

**Key difference from ACE-Step**: No separate venv needed. DiffSinger uses the same PyTorch version as Songmaker. Everything runs in `.venv/`.

## New Files

### source_files/diffsinger_engine/

```
diffsinger_engine/
├── __init__.py          # Public API exports
├── models.py            # VocalNote, VocalPhrase, DiffSingerConfig, DiffSingerResult
├── engine.py            # DiffSingerEngine — orchestrates inference
├── phonemizer.py        # English lyrics → ARPAbet phonemes (via g2p_en)
└── ds_builder.py        # Converts VocalPhrase → .ds JSON format
```

### scripts/setup_diffsinger.py

Setup script that:
1. Clones openvpi/DiffSinger into `_diffsinger/`
2. Installs DiffSinger's requirements into our `.venv/`
3. Downloads TIGER English voicebank + NSF-HiFiGAN vocoder
4. Downloads variance + acoustic checkpoints

## Data Models

### VocalNote (new — extends existing Note concept)

```python
@dataclass(frozen=True)
class VocalNote:
    midi: int                    # MIDI note (e.g., 60 = C4)
    lyric: str                   # Syllable text (e.g., "hel")
    duration_beats: float        # Duration in beats
    velocity: float = 0.8        # Volume/energy (0.0-1.0)
    breathiness: float = 0.0     # 0.0=clean, 1.0=breathy
    tension: float = 0.5         # 0.0=relaxed, 1.0=tense
    is_rest: bool = False        # Silent note (no singing)
```

### VocalPhrase (a singable phrase)

```python
@dataclass(frozen=True)
class VocalPhrase:
    phrase_id: str               # Unique ID for caching
    notes: tuple[VocalNote, ...]  # Sequence of notes+lyrics
    bpm: int                     # Tempo for beat→seconds conversion
    voice: str = "tiger"         # Voicebank name
    gender: float = 0.0          # Formant shift (-1=male, +1=female)
    pitch_shift: int = 0         # Semitone transposition
    seed: int = -1               # Reproducibility (-1=random)
```

### DiffSingerResult (output)

```python
@dataclass(frozen=True)
class DiffSingerResult:
    samples: np.ndarray          # 44100 Hz mono float32 [-1.0, 1.0]
    sample_rate: int             # Always 44100
    duration: float              # Seconds
    phrase_id: str               # Matches input
```

## Engine Flow (engine.py)

```python
class DiffSingerEngine:
    def __init__(self, diffsinger_dir="_diffsinger", device="cuda"):
        # Add DiffSinger to sys.path
        # Load variance + acoustic inferencers

    def generate(self, phrase: VocalPhrase) -> DiffSingerResult:
        # 1. Convert lyrics to phonemes (phonemizer.py)
        # 2. Build .ds JSON segments (ds_builder.py)
        # 3. Run variance inference (timing + pitch + expression)
        # 4. Run acoustic inference (generate WAV)
        # 5. Read WAV, convert to numpy array
        # 6. Return DiffSingerResult

    def generate_phrases(self, phrases: list[VocalPhrase]) -> list[DiffSingerResult]:
        # Batch generation with caching
```

## Phonemizer (phonemizer.py)

```python
def lyrics_to_phonemes(text: str) -> tuple[str, str, str]:
    """Convert English text to DiffSinger phoneme format.

    Returns:
        ph_seq: "AP hh eh l ow SP w er l d SP"
        ph_num: "1 2 2 1"  (phonemes per word)
        note_text: "AP Hello world SP"
    """
    # Uses g2p_en library for English grapheme-to-phoneme
    # Adds AP (breath) at start, SP (silence) between phrases
    # Maps CMU phonemes to DiffSinger ARPAbet format
```

## Setup Script (scripts/setup_diffsinger.py)

1. `git clone --depth 1 https://github.com/openvpi/DiffSinger.git _diffsinger/`
2. `pip install g2p_en` (for English phonemization)
3. Download TIGER voicebank checkpoints (variance + acoustic)
4. Download NSF-HiFiGAN vocoder from openvpi/vocoders releases
5. Verify everything loads

## Track Script Usage (how songs will use it)

```python
from diffsinger_engine import DiffSingerEngine, VocalNote, VocalPhrase

# Define a vocal phrase with melody + lyrics
phrase = VocalPhrase(
    phrase_id="verse_1",
    bpm=120,
    notes=(
        VocalNote(midi=60, lyric="hel", duration_beats=1.0),
        VocalNote(midi=60, lyric="lo", duration_beats=1.0),
        VocalNote(midi=64, lyric="world", duration_beats=2.0),
    ),
)

# Generate isolated vocal
engine = DiffSingerEngine()
result = engine.generate(phrase)

# Mix with instrumentals (existing Songmaker pipeline)
overlay_audio(instrumental_mono, result.samples, start_sample)
```

## Dependencies

Add to pyproject.toml:
- `g2p_en` — English grapheme-to-phoneme conversion
- `diffsinger_engine*` in package discovery

DiffSinger's own deps (click, einops, praat-parselmouth, pyworld, etc.) will be installed via its requirements.txt during setup.

## What We Reuse from Existing Codebase

- `bark_engine.audio_io`: `overlay_audio()`, `normalize_audio()`, `write_wav_file()`, `master_to_mp3()`
- `instrumental_engine.mixer`: `stereo_to_mono()`, `write_mono_wav()`
- `rvc_engine`: Voice conversion (optional post-processing)
- `bark_engine.vocal_filters`: FFmpeg vocal effects
- Track script pattern: VOCAL_PLACEMENT list for beat-accurate placement

## .gitignore Addition

```
_diffsinger/
```

## Verification Plan

1. Run `python scripts/setup_diffsinger.py` — should clone repo + download models
2. Run a minimal test: generate "Hello World" as C4 notes → get WAV output
3. Listen to quality, check timing accuracy
4. Mix with simple piano backing from instrumental engine
5. Compare quality with Bark output on same lyrics

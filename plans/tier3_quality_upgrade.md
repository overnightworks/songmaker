# Tier 3: Quality Upgrade Plan

**Goal**: Dramatically improve vocal and instrumental quality while keeping the architecture modular — swapping engines, models, or GPUs should be a config change, not a rewrite.

**Design principle**: Every component is a **backend** behind an abstract interface. Track scripts never import a specific engine directly — they request capabilities, and the system routes to the best available backend.

---

## Architecture: Backend System

```
Track Script
    │
    ├── VocalEngine (abstract)
    │   ├── BarkBackend        (current, text-to-singing, any GPU)
    │   ├── XTTSBackend        (speech/rap, 4GB+ VRAM)
    │   ├── F5TTSBackend       (speech, 6GB+ VRAM)
    │   └── RVCPostProcessor   (voice conversion layer, stacks on any backend)
    │
    ├── InstrumentalEngine (abstract)
    │   ├── DSPBackend         (current, deterministic, CPU-only)
    │   ├── SoundFontBackend   (current, FluidSynth, CPU-only)
    │   └── MusicGenBackend    (AI generation, 4GB+ VRAM)
    │
    └── StemSeparator (optional)
        └── DemucsBackend      (split any audio into drums/bass/vocals/other)
```

### Key Design Rules

1. **Auto-detection**: Each backend checks if its dependencies are installed and if the GPU has enough VRAM. Unavailable backends are silently skipped.
2. **Graceful fallback**: If the requested backend is unavailable, fall back to the next best option (e.g., XTTS → Bark → error).
3. **Config-driven**: A `VocalConfig` / `InstrumentalConfig` dataclass selects the backend + model size. Track scripts set preferences, the system resolves them.
4. **GPU-agnostic**: All backends auto-detect CUDA, use FP16 when available, and work on CPU as fallback. Upgrading from a GTX 1660 Ti to an RTX 3090 requires zero code changes — larger models are automatically unlocked.
5. **Cache-friendly**: The existing vocal cache system works across all backends (cache key includes the backend name).

---

## Phase 1: RVC Voice Conversion (Post-Processing Layer)

**What**: Add RVC as an optional post-processing step that converts Bark's robotic output into a natural-sounding voice. Works on top of ANY vocal backend.

**Impact**: Biggest quality improvement for least effort. Bark + RVC sounds dramatically better than Bark alone.

**Package**: `infer-rvc-python` (v1.2.0, MIT license)
- Supports numpy array I/O (integrates directly with our WAV pipeline)
- Model preloading/caching (load once, convert many sections)
- RMVPE pitch extraction (best quality)

**VRAM**: ~4 GB for inference (fits on GTX 1660 Ti with FP16)

**Voice models**: Pre-trained .pth + .index files from community repos, or train custom voice from 10-30 min of audio.

### Implementation

```
source_files/
└── rvc_engine/
    ├── __init__.py
    ├── converter.py      # RVCConverter class
    └── models/           # .pth + .index voice model files
```

**Integration point**: New step in `BarkVocalEngine._apply_vocal_processing()` — after ffmpeg filters, before returning samples. Controlled by a `rvc_model` field on `VocalSection`.

```python
@dataclass(frozen=True)
class VocalSection:
    # ... existing fields ...
    rvc_model: str | None = None          # e.g., "male_singer_v2"
    rvc_pitch_shift: int = 0              # semitones
    rvc_index_rate: float = 0.66          # 0-1, feature retrieval strength
```

**When `rvc_model` is None**: Skip RVC (current behavior).
**When `rvc_model` is set**: Load the named model from `rvc_engine/models/`, run voice conversion on the processed audio.

### Steps

1. `pip install infer-rvc-python`
2. Create `source_files/rvc_engine/converter.py` with `RVCConverter` class
3. Add `rvc_model`, `rvc_pitch_shift`, `rvc_index_rate` fields to `VocalSection`
4. Add RVC step to `BarkVocalEngine._apply_vocal_processing()`
5. Download a pre-trained voice model for testing
6. Update vocal cache key to include RVC config
7. Test with one section of Let Me Fall

---

## Phase 2: XTTS v2 Vocal Backend (Speech/Rap Upgrade)

**What**: Add Coqui XTTS v2 as an alternative vocal backend for spoken/whispered/rap sections. Much more natural than Bark for non-singing content.

**Impact**: Spoken sections (intro, bridge, outro whispers, rap verses) sound dramatically more human.

**Package**: `coqui-tts` (community-maintained fork by Idiap Research Institute)
- Clean 2-line Python API
- Returns audio at 24 kHz (same as Bark — existing resampling pipeline works unchanged)
- Zero-shot voice cloning from a 6-second audio clip
- 17 languages including English and German

**VRAM**: ~4 GB minimum, 6 GB comfortable (fits on GTX 1660 Ti). RTX 3090 is overkill for XTTS alone.

**Limitation**: Cannot sing. Use Bark for singing sections, XTTS for speech.

### Implementation

```
source_files/
└── vocal_backends/
    ├── __init__.py
    ├── base.py           # Abstract VocalBackend interface
    ├── bark_backend.py   # Current engine, refactored
    ├── xtts_backend.py   # New XTTS v2 backend
    └── voice_refs/       # Reference audio clips for voice cloning
```

**Backend selection via VocalSection**:
```python
@dataclass(frozen=True)
class VocalSection:
    # ... existing fields ...
    backend: str = "bark"   # "bark", "xtts", "f5tts", "auto"
    voice_ref: str | None = None   # Path to reference audio for cloning
```

**`backend="auto"`**: Use XTTS for SPOKEN/WHISPER/RAP styles, Bark for SINGING/EPIC styles.

### Steps

1. `pip install coqui-tts`
2. Create abstract `VocalBackend` base class
3. Refactor current Bark code into `BarkBackend`
4. Create `XTTSBackend` implementing the same interface
5. Add `backend` and `voice_ref` fields to `VocalSection`
6. Update `BarkVocalEngine.generate_vocals()` to route by backend
7. Record or find a 6-second reference voice clip for testing
8. Test spoken sections with XTTS vs Bark

---

## Phase 3: F5-TTS Backend (Optional, Higher Quality Speech)

**What**: Add F5-TTS as a third vocal backend option. Higher quality than XTTS but needs more VRAM.

**Impact**: Best available open-source speech quality. Good for final production renders.

**Package**: `f5-tts`
- Clean API: `F5TTS.infer(ref_file, ref_text, gen_text)`
- 10+ languages including English and German

**VRAM**: ~6.4 GB measured — tight on GTX 1660 Ti, comfortable on RTX 3090.

**Limitation**: Cannot sing. Requires reference audio + transcription (not just audio).

### Implementation

Same `vocal_backends/` structure. Add `F5TTSBackend` class.

### Steps

1. `pip install f5-tts`
2. Create `F5TTSBackend` implementing `VocalBackend` interface
3. Test quality comparison: Bark vs XTTS vs F5-TTS on same section

---

## Phase 4: Better SoundFonts (Instant Win)

**What**: Download higher-quality SoundFont files. Zero code changes — drop files in `soundfonts/` and the existing engine picks them up.

**Impact**: Immediate improvement in piano, strings, guitar, and drum sounds.

### Recommended Downloads

| SoundFont | Size | Best For | Source |
|-----------|------|----------|--------|
| **Timbres of Heaven** | ~400 MB | Best all-around GM set | [Download](https://midkar.com/soundfonts/) |
| **Salamander Grand Piano** | ~230 MB | Realistic piano | [Musical Artifacts](https://musical-artifacts.com/) |
| **FluidR3_GM** | ~141 MB | Good general purpose (you may have this already) | [KeyMusician](https://member.keymusician.com/Member/FluidR3_GM/) |

### Steps

1. Download Timbres of Heaven and Salamander Grand Piano
2. Place in `soundfonts/` directory
3. Update `find_soundfont()` to prefer Timbres of Heaven as default
4. Optionally add instrument-specific SoundFont routing (piano sections → Salamander)

---

## Phase 5: MusicGen AI Instrumentals (New Capability)

**What**: Add Meta's MusicGen as an alternative instrumental renderer. Generate backing tracks from text prompts like "melodic house, deep bass, 124 BPM, E minor".

**Impact**: AI-generated instrumentals that sound more organic than DSP synths. Good for prototyping arrangements quickly.

**Package**: `audiocraft` (Meta)

**Models & VRAM**:
| Model | Params | VRAM | Quality |
|-------|--------|------|---------|
| `musicgen-small` | 300M | ~4-5 GB | Decent (GTX 1660 Ti) |
| `musicgen-medium` | 1.5B | ~10-12 GB | Good (RTX 3090) |
| `musicgen-large` | 3.3B | ~16-20 GB | Best (RTX 3090) |

**Config-driven model selection**:
```python
@dataclass
class MusicGenConfig:
    model: str = "auto"  # "auto" picks best model for available VRAM
    # auto: 6GB → small, 12GB → medium, 20GB+ → large
```

**Output**: 32 kHz mono audio. Needs resampling to 44.1 kHz stereo for mixing.

**Limitation**: Max ~30 seconds per generation. Full songs need concatenation with crossfading.

### Implementation

```
source_files/
└── ai_engine/
    ├── __init__.py
    ├── musicgen_renderer.py   # MusicGenRenderer class
    └── config.py              # Model selection, VRAM detection
```

### Steps

1. `pip install audiocraft`
2. Create `MusicGenRenderer` with text-prompt-to-audio generation
3. Add VRAM auto-detection for model selection
4. Create a section-by-section prompt generator from `SongSection` metadata
5. Add crossfading for multi-segment generation
6. Test alongside existing DSP instrumentals

---

## Phase 6: Demucs Stem Separation (Utility)

**What**: Add Meta's Demucs for splitting any audio into 4 stems: vocals, drums, bass, other.

**Impact**: Enables the "hybrid workflow" — generate with MusicGen or grab a reference track, separate into stems, remix with your own mastering chain.

**Package**: `demucs` or `demucs-infer` (lighter)

**VRAM**: ~3 GB minimum, use `--segment 7` flag for 6 GB GPUs.

### Implementation

```
source_files/
└── stem_separator/
    ├── __init__.py
    └── demucs_separator.py   # DemucsSeparator class
```

### Steps

1. `pip install demucs`
2. Create `DemucsSeparator` class with `separate(input_path) → dict[str, np.ndarray]`
3. Auto-detect GPU, adjust segment size for available VRAM
4. Output: `{"vocals": array, "drums": array, "bass": array, "other": array}`

---

## Phase Summary & Priority

| Phase | Component | Effort | Quality Impact | GPU Requirement |
|-------|-----------|--------|----------------|-----------------|
| **1** | **RVC post-processing** | 1-2 days | HUGE (vocals) | 4 GB (any GPU) |
| **2** | **XTTS v2 backend** | 1-2 days | HIGH (speech) | 4 GB (any GPU) |
| **3** | F5-TTS backend | 1 day | HIGH (speech) | 6 GB+ (better GPU) |
| **4** | **Better SoundFonts** | 10 minutes | MEDIUM (instruments) | None (CPU) |
| **5** | MusicGen instrumentals | 2-3 days | MEDIUM (instruments) | 4-20 GB (scales with GPU) |
| **6** | Demucs stem separation | 1 day | LOW (utility) | 3 GB+ |

**Recommended order**: Phase 4 → Phase 1 → Phase 2 → Phase 3 → Phase 5 → Phase 6

Phase 4 is free (just download files). Phase 1 (RVC) gives the biggest quality jump. Phases 2-3 upgrade non-singing vocals. Phases 5-6 add new capabilities.

---

## Hardware Scalability

The entire system auto-scales to the available GPU:

| GPU | What Unlocks |
|-----|-------------|
| **No GPU (CPU only)** | Bark (slow), DSP synths, SoundFonts |
| **GTX 1660 Ti (6 GB)** | + RVC, + XTTS, + F5-TTS (tight), + MusicGen small, + Demucs |
| **RTX 3090 (24 GB)** | + Full-size Bark models, + MusicGen medium/large, + train custom RVC voices, + run multiple backends simultaneously |
| **RTX 4090 (24 GB)** | Same as 3090 but 2-3x faster inference |

**Upgrading GPU requires zero code changes.** All backends auto-detect CUDA and available VRAM. Larger models are selected automatically when more VRAM is available.

---

## File Structure After All Phases

```
source_files/
├── bark_engine/              # Existing (refactored into vocal_backends/)
├── instrumental_engine/      # Existing (unchanged)
├── vocal_backends/           # NEW — modular vocal engine system
│   ├── __init__.py
│   ├── base.py               # Abstract VocalBackend interface
│   ├── bark_backend.py       # Current Bark, refactored
│   ├── xtts_backend.py       # XTTS v2
│   ├── f5tts_backend.py      # F5-TTS
│   └── voice_refs/           # Reference audio clips for cloning
├── rvc_engine/               # NEW — RVC voice conversion
│   ├── __init__.py
│   ├── converter.py          # RVCConverter class
│   └── models/               # .pth + .index voice model files
├── ai_engine/                # NEW — AI instrumental generation
│   ├── __init__.py
│   ├── musicgen_renderer.py
│   └── config.py             # VRAM detection, model selection
└── stem_separator/           # NEW — Demucs stem separation
    ├── __init__.py
    └── demucs_separator.py
```

---

## Dependencies (All Optional)

```bash
# Phase 1: RVC
pip install infer-rvc-python

# Phase 2: XTTS v2
pip install coqui-tts

# Phase 3: F5-TTS
pip install f5-tts

# Phase 4: SoundFonts
# No pip install — just download .sf2 files

# Phase 5: MusicGen
pip install audiocraft

# Phase 6: Demucs
pip install demucs
```

Each phase is independently installable. Missing dependencies cause graceful fallback, not crashes.

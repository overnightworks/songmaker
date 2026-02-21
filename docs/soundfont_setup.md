# SoundFont Setup Guide

**Project**: Songmaker  
**Status**: Required for production use  
**Last Updated**: 2026-02-21

---

## What Are SoundFonts?

SoundFonts (`.sf2` files) are collections of **recorded instrument samples** mapped across the full MIDI note range. Unlike the project's built-in DSP synthesizers — which generate sound mathematically from waveforms — SoundFonts play back real recordings of acoustic instruments (pianos, strings, brass, etc.), producing far more realistic results.

### DSP Synths vs SoundFonts

| Feature | DSP Synths (built-in) | SoundFont Instruments |
|---------|----------------------|----------------------|
| Sound Source | Mathematical waveforms | Recorded instrument samples |
| Realism | Synthetic, electronic | Realistic, acoustic |
| File Size | None (generated in code) | 30–350 MB per SoundFont |
| Dependency | None | FluidSynth CLI required |
| Best For | Electronic genres (EDM, synthwave) | Acoustic genres (pop, rock, ballad) |
| Instrument ID | `piano`, `strings`, `pad` | `sf:piano`, `sf:strings`, `sf:brass` |

**FluidSynth** is an open-source software synthesizer that reads SoundFont files and renders MIDI data to audio. It is **required** for all `sf:*` instruments.

---

## Step 1: Install FluidSynth

FluidSynth must be installed and accessible from the command line.

### Windows (Recommended: winget)

```cmd
winget install FluidSynth.FluidSynth
```

After installation, restart your terminal. Verify with:

```cmd
fluidsynth --version
```

### Windows (Manual Download)

1. Go to <https://github.com/FluidSynth/fluidsynth/releases>
2. Download the latest Windows release (e.g., `fluidsynth-2.x.x-win64.zip`)
3. Extract to a folder such as `C:\tools\fluidsynth`
4. Add the `bin` subfolder to your system PATH:
   - Open **Settings → System → About → Advanced system settings**
   - Click **Environment Variables**
   - Under **System variables**, find `Path` and click **Edit**
   - Add `C:\tools\fluidsynth\bin`
5. Restart your terminal and verify:

```cmd
fluidsynth --version
```

### macOS

```bash
brew install fluid-synth
```

### Linux (Debian/Ubuntu)

```bash
sudo apt-get install -y fluidsynth
```

### Linux (Fedora)

```bash
sudo dnf install fluidsynth
```

---

## Step 2: Download a SoundFont

You need at least one General MIDI (GM) SoundFont file. These contain all 128 standard MIDI instruments.

### Recommended SoundFonts

| SoundFont | Size | Quality | Download |
|-----------|------|---------|----------|
| **FluidR3_GM.sf2** | ~140 MB | ⭐⭐⭐ Good (recommended) | [KeyMusician](https://member.keymusician.com/Member/FluidR3_GM/FluidR3_GM.sf2) |
| **GeneralUser_GS.sf2** | ~30 MB | ⭐⭐ Decent (lightweight) | [SourceForge](https://generaluser.sourceforge.io/) |
| **Timbres of Heaven** | ~350 MB | ⭐⭐⭐⭐ Excellent | [midkar.com](https://midkar.com/soundfonts/) |

**FluidR3_GM.sf2** is the recommended choice — it provides good quality across all instrument families at a reasonable file size.

---

## Step 3: Place the SoundFont File

Place your downloaded `.sf2` file in the project's `soundfonts/` directory:

```
songmaker/
└── soundfonts/
    └── FluidR3_GM.sf2      ← Place here
```

The engine automatically discovers `.sf2` files in these locations (checked in order):

1. `soundfonts/GeneralUser_GS.sf2`
2. `soundfonts/FluidR3_GM.sf2`
3. `soundfonts/default.sf2`
4. `C:/tools/fluidsynth/share/soundfonts/default.sf2`
5. `C:/soundfonts/GeneralUser_GS.sf2`
6. Any `.sf2` file in `soundfonts/` (alphabetical fallback)

---

## Step 4: Verify Setup

Run the built-in validator to confirm everything works:

```cmd
python source_files/instrumental_engine/soundfont_validator.py
```

### Expected Output (Success)

```
================================================================
  SoundFont Rendering — Health Check Report
================================================================

✅ FluidSynth found: fluidsynth 2.3.4
✅ SoundFont found: soundfonts/FluidR3_GM.sf2 (141.2 MB)
✅ Test render: C major scale rendered successfully

----------------------------------------------------------------
  Status: ✅ READY — SoundFont rendering is fully operational
================================================================
```

### Expected Output (FluidSynth Missing)

```
================================================================
  SoundFont Rendering — Health Check Report
================================================================

❌ FluidSynth not found on PATH
╔══════════════════════════════════════════════════════════════════╗
║  FluidSynth is REQUIRED for SoundFont instrument rendering.    ║
║  ...installation instructions...                                 ║
╚══════════════════════════════════════════════════════════════════╝

----------------------------------------------------------------
  Status: ❌ FAILED — FluidSynth is not installed
================================================================
```

---

## Step 5: Use in Track Scripts

Once setup is verified, use `sf:` prefixed instrument IDs in your track scripts:

```python
from instrumental_engine import (
    Arrangement, SongSection, InstrumentTrack, Note, Chord,
    GMProgram, SectionType, PATTERN_LIBRARY, render_and_export,
)

arrangement = Arrangement(
    title="My Song",
    default_bpm=120,
    sections=(
        SongSection(
            section_type=SectionType.VERSE,
            start_beat=0.0,
            length_beats=16.0,
            bpm=120,
            tracks=(
                InstrumentTrack(
                    name="piano",
                    instrument_id="sf:piano",        # ← SoundFont piano
                    gm_program=GMProgram.ACOUSTIC_GRAND_PIANO,
                    events=(
                        Note(midi=60, velocity=0.8, duration_beats=1.0),
                        Note(midi=64, velocity=0.8, duration_beats=1.0),
                        Note(midi=67, velocity=0.8, duration_beats=1.0),
                        Note(midi=72, velocity=0.9, duration_beats=2.0),
                    ),
                    volume=0.8,
                ),
                InstrumentTrack(
                    name="strings",
                    instrument_id="sf:strings",      # ← SoundFont strings
                    gm_program=GMProgram.STRINGS_ENSEMBLE,
                    events=(
                        Chord(notes=(48, 52, 55), velocity=0.6, duration_beats=4.0),
                        Chord(notes=(53, 57, 60), velocity=0.6, duration_beats=4.0),
                    ),
                    volume=0.6,
                ),
            ),
        ),
    ),
)

render_and_export(arrangement, "output/my_song")
```

### Available SoundFont Instruments

The `instrument_id` uses the `sf:` prefix to select SoundFont rendering. The actual sound is determined by the `gm_program` field:

| `instrument_id` | `gm_program` | Sound |
|-----------------|--------------|-------|
| `sf:piano` | `GMProgram.ACOUSTIC_GRAND_PIANO` (0) | Acoustic piano |
| `sf:bright_piano` | `GMProgram.BRIGHT_PIANO` (1) | Bright piano |
| `sf:electric_piano` | `GMProgram.ELECTRIC_PIANO` (4) | Electric piano |
| `sf:guitar` | `GMProgram.NYLON_GUITAR` (24) | Nylon guitar |
| `sf:steel_guitar` | `GMProgram.STEEL_GUITAR` (25) | Steel guitar |
| `sf:bass` | `GMProgram.ACOUSTIC_BASS` (32) | Acoustic bass |
| `sf:strings` | `GMProgram.STRINGS_ENSEMBLE` (48) | String ensemble |
| `sf:choir` | `GMProgram.CHOIR_AAHS` (52) | Choir ahs |
| `sf:trumpet` | `GMProgram.TRUMPET` (56) | Trumpet |
| `sf:brass` | `GMProgram.BRASS_SECTION` (61) | Brass section |

Any General MIDI program number (0–127) can be used via the `GMProgram` enum.

---

## Troubleshooting

### "FluidSynth not found"

- Verify installation: `fluidsynth --version`
- On Windows, ensure the `bin` directory is in your PATH
- Restart your terminal after installation
- Try the full path: `C:\tools\fluidsynth\bin\fluidsynth --version`

### "No SoundFont files found"

- Verify `.sf2` file exists in `soundfonts/` directory
- Check file extension — must be `.sf2` (not `.zip` or `.sf3`)
- Ensure file is not corrupted (should be > 1 MB)

### "Test render failed"

- The SoundFont file may be corrupted — re-download it
- Check FluidSynth can access the file: `fluidsynth -ni soundfonts/FluidR3_GM.sf2`
- On Windows, check antivirus is not blocking FluidSynth

### Mixing `sf:` and DSP instruments

You can freely mix SoundFont and DSP instruments in the same arrangement:

```python
tracks=(
    InstrumentTrack(name="piano", instrument_id="sf:piano", ...),      # SoundFont
    InstrumentTrack(name="synth_pad", instrument_id="pad", ...),       # DSP synth
    InstrumentTrack(name="bass", instrument_id="sub_bass", ...),       # DSP synth
    InstrumentTrack(name="strings", instrument_id="sf:strings", ...),  # SoundFont
)
```

DSP synth instruments (`piano`, `pad`, `supersaw`, etc.) work without FluidSynth. Only `sf:*` prefixed instruments require the SoundFont stack.

---

## Further Reading

- [FluidSynth Documentation](https://www.fluidsynth.org/documentation/)
- [General MIDI Specification](https://www.midi.org/specifications/item/gm-level-1-sound-set)
- [SoundFont Technical Format](https://freepats.zenvoid.org/sf2/sfspec24.pdf)

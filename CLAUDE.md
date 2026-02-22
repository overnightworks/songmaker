# Songmaker — Claude Code Config

## Project
AI-powered song generation engine by Flex0r. Generates complete songs (vocals + instrumentals) from pure Python scripts.

**Creator**: Flex0r (Felix)
**For**: MC Tobbisch (Tobias)
**Python**: 3.12 (pinned — AI backends require <=3.12)
**Venv**: `.venv/` (single unified environment for all deps)
**Run a track**: `.venv/Scripts/python albums/<album>/tracks/<NN>_<song>.py`

## Key Rules

1. **Lyrics-first workflow**: New songs start as `albums/<album>/lyrics/<NN>_<song>.md`, NOT Python. Get lyrics to APPROVED status before creating track script.
2. **One song = one file**: Every track lives in `albums/<album>/tracks/` as a single `.py` file.
3. **Engine reuse**: Both engines live in `source_files/` — never duplicate engine code into track files.
4. **Ducking always active**: Vocals duck instrumentals by -3dB automatically.
5. **Never commit secrets or API keys.**
6. **DiffSinger: 2 lyric lines per phrase** (~12-16 notes). 4+ lines = garbled consonants, 1 line = too short for context. See AGENTS.md for full DiffSinger production rules.
7. **Validate before shipping**: Run `check_beat_budgets()` pre-generation and Whisper pronunciation check post-generation. Target >80% similarity per phrase.

## Project Structure
- `source_files/` — Shared engine code (bark, instrumental, diffsinger, rvc, xtts)
- `albums/<album>/tracks/` — One `.py` per song
- `albums/<album>/lyrics/` — Lyrics markdown files (draft → review → approved)
- `_models/` — AI model weights (DiffSinger, RVC, SoundFonts, ACE-Step, voice refs)
- `_cache/` — Temp files and vocal cache (all gitignored)
- `_output/` — Generated audio per album (WAV + MP3, all gitignored)
- `scripts/` — Setup and utility scripts
- `AGENTS.md` — Full project documentation (detailed reference)

## Setup
```bash
py -3.12 -m venv .venv
.venv/Scripts/activate          # Windows
pip install -e .                # Core + RVC deps from pyproject.toml
pip install -e .[xtts]          # + XTTS voice cloning (optional)
pip install -e .[demucs]        # + Stem separation (optional)
# ffmpeg must be on PATH
# Optional: FluidSynth + SoundFont for realistic instruments
# GPU: pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
```

## Active Albums
- **Download Days** — Punk rock / hip-hop, 90s Erlangen nostalgia
- **Midnight Frequency** — Melodic house, surrender and freedom themes
- **MC Tobbisch Birthday** — Legacy (edge-tts, archived)

## Conventions
- Commit messages: conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`)
- Language: Lyrics can be German or English; code and docs in English
- Sample rate: 44100 Hz everywhere
- Output: Stereo WAV → MP3 192kbps via ffmpeg
- Mastering: Multiband compression → Stereo widening → LUFS -14 → Soft clipping

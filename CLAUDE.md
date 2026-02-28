# Songmaker — Claude Code Config

## Project
AI-powered song generation engine by Flex0r. Generates complete songs from markdown files via ACE-Step.

**Creator**: Flex0r (Felix)
**For**: MC Tobbisch (Tobias)
**Python**: 3.12 (pinned — AI backends require <=3.12)
**Venv**: `.venv/` (single unified environment for all deps)

## Workflow

### ACE-Step songs (primary)
```bash
# Generate a song from markdown
songmaker generate albums/<album>/lyrics/<NN>_<song>.md

# Generate with specific seed
songmaker generate albums/<album>/lyrics/<NN>_<song>.md --seed 42

# Sync lyrics (transcribe, LRC, HTML player, ID3 tags)
songmaker sync _output/<album>/final/
```

### Complex tracks (instrumental engine, Bark, etc.)
```bash
.venv/Scripts/python albums/<album>/tracks/<NN>_<song>.py
```

## Song Format (markdown with YAML frontmatter)
```markdown
---
title: Song Title
album: album_name
track: 1
prompt: >
  style description for ACE-Step
bpm: 120
duration: 180
key: Am
language: de
status: approved
---

# Song Title

## Concept
What the song is about...

## Lyrics

[verse]
First verse lyrics...

[chorus]
Chorus lyrics...
```

## Key Rules

1. **Lyrics-first workflow**: New songs start as `albums/<album>/lyrics/<NN>_<song>.md`. Get lyrics to APPROVED status before generating.
2. **One song = one markdown file**: Each song is a `.md` file with YAML frontmatter (prompt, bpm, duration, key) + lyrics.
3. **Engine reuse**: All engines live in `source_files/` — never duplicate engine code.
4. **Ducking always active**: Vocals duck instrumentals by -3dB automatically.
5. **Never commit secrets or API keys.**
6. **Validate after generation**: Run `songmaker sync` for Whisper transcription + lyrics embedding.
7. **Commit per version**: Every time lyrics are changed for a new generation, commit the markdown file before generating. Commit message format: `feat(<album>): <song> v<N> — <style>` (e.g. `feat(murphys): pub quiz tuesday v3 — weezer indie rock`). This way any version can be checked out and regenerated.

## Project Structure
- `source_files/` — Shared engine code (acestep, bark, instrumental, diffsinger, rvc, xtts, songmaker_cli)
- `albums/<album>/lyrics/` — Song markdown files (lyrics + generation config)
- `albums/<album>/tracks/` — Complex tracks that need Python (instrumental engine, Bark)
- `albums/<album>/album.yaml` — Album metadata (title, artist, year)
- `_models/` — AI model weights (all gitignored)
- `_cache/` — Temp files and vocal cache (all gitignored)
- `_output/` — Generated audio per album (WAV + MP3, all gitignored)
- `scripts/` — Setup and utility scripts
- `AGENTS.md` — Full project documentation (detailed reference)

## Setup
```bash
py -3.12 -m venv .venv
.venv/Scripts/activate          # Windows
pip install -e .                # Core deps + songmaker CLI
# ffmpeg must be on PATH
# ACE-Step server: python scripts/start_acestep.py
```

## Active Albums
- **Apologiez** — Personal album for MC Tobbisch (ACE-Step, all genres)
- **Download Days** — Punk rock / hip-hop, 90s Erlangen nostalgia
- **Midnight Frequency** — Melodic house, surrender and freedom themes

## Conventions
- Commit messages: conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`)
- Language: Lyrics can be German or English; code and docs in English
- Sample rate: 44100 Hz everywhere
- Output: Stereo WAV → MP3 320kbps via ffmpeg
- Mastering: Multiband compression → Stereo widening → LUFS -14 → Soft clipping

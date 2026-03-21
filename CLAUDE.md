# Songmaker — Claude Code Config

## Project

AI-powered song generation CLI. Markdown files with lyrics and YAML frontmatter go in, mastered MP3s come out.

**Python**: 3.12 (pinned — AI backends require <=3.12)
**Venv**: `.venv/`

## CLI (cyclopts)

```bash
songmaker generate <path> [--seed N] [--count N] [--duration N] [--bpm N]
    [--key KEY] [--shift F] [--guidance-scale F] [--inference-steps N]
    [--lm-temperature F] [--infer-method STR] [--think-mode/--no-think-mode]
    [--check]

songmaker check <mp3> [--source <lyrics.md>] [--whisper-model STR]

songmaker score <mp3> [--source <lyrics.md>] [--scorers STR] [--whisper-model STR]

songmaker player [-o output_dir] [--root project_root]
```

## Song Format

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
---

## Lyrics

[verse]
Lyrics here...

[chorus]
Chorus here...
```

## Code Standards

### KISS
- Short, self-explanatory methods (~20 lines max)
- No inline comments — use descriptive names
- No God classes — one responsibility per class/module
- Flat over nested, three similar lines > one premature abstraction

### No Hardcoded Strings
- Constants for repeated values (paths, magic numbers)
- Config files or CLI options for user-facing settings

### Separation of Concerns
- Each module does one thing well
- I/O at the edges, pure logic in the middle
- No business logic in CLI handlers — delegate to engine modules

### Testing
- 100% coverage goal
- pytest fixtures, no test inheritance
- Mock external services (ACE-Step server, ffmpeg, Whisper)
- Tests must be fast (full suite < 10 seconds)

### General
- Type hints on all function signatures
- Prefer dataclasses/pydantic/TypedDict over untyped dicts for structured data
- Functions return values, don't mutate arguments
- No dead parameters, no unused imports, no stale docstrings — if you move or remove code, clean up all traces

## Key Rules

1. **Lyrics-first workflow**: Songs start as markdown in `albums/<album>/lyrics/`. Finalize lyrics before generating.
2. **One song = one markdown file**: YAML frontmatter + lyrics section.
3. **Engine reuse**: All engines live in `src/` — never duplicate engine code.
4. **Never commit secrets or API keys.**
5. **Commit per version**: Commit lyrics before each generation. Format: `feat(<album>): <song> v<N> — <style>`

## Project Structure

- `src/acestep_engine/` — ACE-Step HTTP client (with retry), config dataclass, response models
- `src/audio_engine/` — Mastering chain, WAV/MP3 I/O, LUFS measurement
- `src/songmaker_cli/` — CLI entrypoint and subcommands
  - `main.py` — Thin CLI adapter (cyclopts commands → generate/score/check/player)
  - `generate.py` — Generation orchestration (generate, decode, master, score, rank)
  - `parser.py` — Markdown + YAML parsing into pydantic models
  - `config.py` — Output path resolution, ACE-Step config building
  - `check.py` — Verbose lyrics check CLI (thin wrapper over scoring.text_accuracy)
  - `scanner.py` — Filesystem scanning, version deduplication
  - `manifest.py` — Player manifest data model + building
  - `player.py` — HTML player generation (thin orchestrator)
  - `snapshot.py` — Generation snapshot read/write (frontmatter, scores, generation info)
  - `scoring/` — Scoring pipeline with ScorerRegistry class + decorator registration
- `albums/<album>/lyrics/` — Song markdown files
- `albums/<album>/album.yaml` — Album metadata (title, artist, year)
- `_output/` — Generated audio (gitignored)
- `_models/` — AI model weights (gitignored)
- `scripts/` — Server setup/start
- `tests/` — pytest suite
- `docs/` — Architecture and testing docs

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
# ffmpeg must be on PATH
# ACE-Step server: python scripts/start_acestep.py
```

## Workflow

- **Commit before reviewing**: After completing a batch of changes, always commit first, then review. This ensures work is safe and reviewable as a clean diff.
- **Run tests before committing**: `pytest tests/ -q` must pass. Run `ruff check` on changed files.

## Conventions

- Commit messages: conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`)
- Code and docs in English, lyrics can be any language
- Sample rate: native from ACE-Step (typically 48kHz), `FALLBACK_SAMPLE_RATE = 48000` in `audio_engine.constants`
- Output: Stereo WAV -> MP3 320kbps via ffmpeg
- Mastering: Multiband compression -> Stereo widening -> LUFS -14 -> Soft clipping

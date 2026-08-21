# Creation and generation

## Intent

A musician can start audio generation from lyrics, a style prompt, a chosen
available model, and generation settings, then compare the resulting takes. A
pinned seed from an earlier take can be reused with changed settings; a take
records the seed that actually produced it. Reimport is a second take producer.
Scoring and transcription inform the musician and do not choose the album take.

## Rules

### REQ-CREATE-01: A musician can start audio generation for a song.
Quelle: DESK — CLAUDE.md, “Product Context”, paragraph 2; corroborated by the current generate workflow.

### REQ-CREATE-02: Songmaker refuses to start generation when the song version used for that generation has no lyrics or no style prompt.
Quelle: DESK — CLAUDE.md, “Product Context”, paragraph 2; corroborated by the current generate refusal when lyrics or prompt are missing.

### REQ-MODEL-01: Starting generation requires a currently available model; Songmaker does not silently substitute a different model.
Quelle: DESK — CLAUDE.md, no-silent-fallbacks and the 2026-04-08 available_models incident; corroborated by generate requiring a currently available model.

### REQ-PARAM-01: A generation uses the generation settings that apply to the chosen model; Songmaker does not silently drop them.
Quelle: DESK — CLAUDE.md, no-silent-fallbacks; corroborated by current generate applying version generation settings and hiding unsupported knobs per model.

### REQ-SEED-01: A musician can pin a previous take's seed and generate again with changed settings.
Quelle: DESK — CLAUDE.md, “Seed pinning”.

### REQ-SEED-02: A pinned non-negative seed is a fixed seed; when the musician does not pin a seed, generation is random.
Quelle: DESK — CLAUDE.md, “Seed pinning”; corroborated by current generate using a pinned non-negative seed as fixed and omitting a seed as random.

### REQ-SEED-03: A generated take records the seed that produced its audio.
Quelle: DESK — CLAUDE.md, Known Technical Debt: the recorded seed is the engine-reported `seed_value`, not a different requested seed.

### REQ-IMPORT-01: Reimporting audio into a song produces a take of that song.
Quelle: DESK — current reimport workflow; corroborated by 0001 Non-goals treating imported audio as a take that may lack a version link.

### REQ-SCORE-01: Scoring a take does not select or change that song's Pick.
Quelle: DESK — CLAUDE.md, “Product Context”, scoring is purely informational.

### REQ-SCORE-02: When a take has a sung transcription, Songmaker presents it as information and does not treat it as a replacement for the lyrics.
Quelle: DESK — CLAUDE.md, “Product Context”, Whisper transcript shows what was sung.

## Non-goals

- This revision does not decide omitted version identity, including whether an
  omitted version is the latest, or whether whitespace-only lyrics or prompt
  count as missing.
- This revision does not decide pin lifetime, batch count, or sampler and
  velocity defaults.
- This revision does not govern repaint, cover, Co-Writer, or Sharing.
- Library and player behavior belong to `0002-library-and-listening.md`.
- This document does not prescribe ACE-Step internals or the generation wire
  payload, LoRA or user-adapter fallback, or leftover stored settings that do
  not apply to the newly chosen model.
- This revision does not decide whether a reimported take records a seed, which
  scorers run, or whether every scoring run produces a transcription.
- Pick and Keep meanings belong to `0001-creative-catalog-and-takes.md`.

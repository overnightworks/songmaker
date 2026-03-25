# ACE-Step 2.0 — Advanced Generation Modes

> **Status: NOT STARTED** — Phase 1 (reference audio) is the next priority.

## Goal

Expose ACE-Step 1.5's full capabilities beyond text2music: cover, repaint, reference audio, lego, extract, complete. Enable human-centered iterative workflows where users refine generations, not just roll the dice.

## Current State

- **text2music only** — prompt + lyrics → audio
- All LM params exposed (temperature, top_k, top_p, cfg_scale, negative_prompt)
- batch_size configurable (1-8)
- Turbo + SFT model switching works
- Generation settings UI complete with per-version param storage

## Architecture: What ACE-Step Supports

All modes use the same `/release_task` endpoint with different `task_type` + audio inputs:

| Mode | task_type | Requires | What It Does |
|------|-----------|----------|-------------|
| Text2Music | `text2music` | caption + lyrics | Generate from scratch (current) |
| Cover | `cover` | src_audio + caption + lyrics | Maintain melody structure, change style/lyrics |
| Repaint | `repaint` | src_audio + start/end times | Edit a specific section (3-90s) |
| Lego | `lego` | src_audio + start/end times | Add new tracks to existing audio |
| Extract | `extract` | src_audio | Separate single tracks from mixed audio |
| Complete | `complete` | src_audio | Add accompaniment to a single track |

**Note**: Lego, Extract, Complete require the **Base** model (not Turbo/SFT).

## Audio Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `reference_audio` | file path | Global timbre/style reference (any mode) |
| `src_audio` | file path | Source audio for cover/repaint/lego/extract/complete |
| `audio_cover_strength` | 0.0-1.0 | How strictly to follow source (cover mode) |
| `repainting_start` | seconds | Start time for repaint/lego |
| `repainting_end` | seconds | End time for repaint/lego |
| `audio_codes` | codes | Semantic codes (advanced: reuse from previous gen) |

---

## Implementation Plan

### Phase 1: Reference Audio (simplest, no new UI patterns)

**What**: Let users upload a reference track to influence timbre/style of new generations.

- [ ] Add `reference_audio` field to AceStepConfig
- [ ] Add file upload endpoint: `POST /api/audio/upload` → saves to temp, returns path
- [ ] Pass reference_audio path to ACE-Step `/release_task`
- [ ] Frontend: "Reference Track" upload button in generation settings
- [ ] Store reference_audio path per song version (optional)

**UX**: Drag-and-drop or file picker → "Your new generations will sound like this track's style"

### Phase 2: Cover Mode

**What**: Take an existing generation (or uploaded track) and re-interpret it with different style/lyrics while keeping the melody structure.

- [ ] Add `task_type` field to AceStepConfig (default: "text2music")
- [ ] Add `src_audio` and `audio_cover_strength` to config
- [ ] Frontend: "Cover" button on each generation → opens cover dialog
  - Source: the selected generation's MP3
  - User can modify caption + lyrics
  - Strength slider (0.0 = free, 1.0 = strict structure)
- [ ] Result is a new generation linked to the same song
- [ ] API: new endpoint or extend generate endpoint with mode param

**UX**: Listen to gen3, like the melody but not the style → click Cover → change prompt to "jazz version" → generate

### Phase 3: Repaint Mode

**What**: Edit a specific time section of an existing generation. Fix a bad chorus, extend an intro, change lyrics in one verse.

- [ ] Add `repainting_start` and `repainting_end` to config
- [ ] Frontend: waveform selection UI — drag to select a time range on a generation
- [ ] User can provide new lyrics/caption for just that section
- [ ] Result replaces the selected section while keeping surrounding audio
- [ ] Store as a new generation (non-destructive)

**UX**: Gen sounds great except 0:45-1:15 → select that range → write new lyrics → repaint → seamless edit

### Phase 4: Base Model Tasks (Lego, Extract, Complete)

**What**: Advanced audio manipulation requiring the Base model.

- [ ] Model switching: detect task_type → auto-switch to Base if needed
- [ ] **Lego**: Add instruments to existing tracks (e.g., add drums to guitar recording)
- [ ] **Extract**: Separate stems from mixed audio (vocals, instruments)
- [ ] **Complete**: Add full accompaniment to a solo track
- [ ] Frontend: dedicated "Audio Tools" panel for these operations

**Note**: These require downloading the Base model (`acestep-download --model acestep-v15-base`) and may need model switching in the GPU queue.

### Phase 5: Infinite Duration Generation

**What**: Chain repaint operations to generate songs longer than the model's limit (~4 min).

- [ ] Auto-chain: generate first segment, then repaint-extend from the end
- [ ] Seamless transitions via context-based completion
- [ ] Progress tracking for multi-segment generation
- [ ] Frontend: "Extend" button on generations

---

## What We're NOT Doing

- **LoRA training UI** — too complex, use ACE-Step's Gradio UI directly
- **Audio codes manipulation** — power user feature, defer
- **Multi-model parallel** — one model at a time is fine for single-GPU

---

## Dependencies

- Phase 1 needs: file upload endpoint (doesn't exist yet)
- Phase 2 needs: Phase 1 (reference audio pattern) + task_type in config
- Phase 3 needs: waveform selection UI (new component)
- Phase 4 needs: Base model download + model switching logic
- Phase 5 needs: Phase 3 (repaint) + chaining logic

---

## Priority

Phase 1 (reference audio) and Phase 2 (cover) are the highest value — they enable the iterative "human-centered" workflow the ACE-Step guide emphasizes. Phases 3-5 build on that foundation.

# ACE-Step Advanced Generation Modes

> **Status: NOT STARTED**

## Goal

1. Per-generation model selection — users pick which model to use from a dropdown, worker auto-switches as needed
2. Show only parameters relevant to the selected model
3. Tag every generation with which model produced it
4. Enable iterative audio refinement: repaint, cover, reference audio

## Prerequisites

- **`plans/admin-sse-and-auth.md`** must be complete before Phase 1b. That plan converts `reinitialize_acestep` into a proper Job with SSE streaming, adds `target_model` parameter to the endpoint, and builds the admin UI model dropdown. Phase 1b here only needs to implement `AceStepManager.switch_model()` and replace the "not yet implemented" stub in the worker.

## Current State

- **text2music only** — prompt + lyrics → audio
- All LM params exposed (temperature, top_k, top_p, cfg_scale, negative_prompt)
- `AvailableModel` table exists with `id` + `is_active` flag
- Admin endpoints: `GET /settings/models/all`, `PUT /settings/models/{id}` (toggle active)
- User endpoint: `GET /settings/models` (active only)
- Presets already scoped by `model_mode` (turbo/sft)
- `build_ace_config()` merges: model defaults → global defaults → preset → version params
- Generation settings UI complete with preset chips filtered by model_mode
- Generate request already has an optional `model` field (validates against active model)
- Reinitialize endpoint returns a `JobResponse` with SSE streaming, accepts optional `target_model` (stubbed — rejects different model until this plan implements `switch_model()`). Admin UI has model dropdown + reinitialize/switch button. See `plans/admin-sse-and-auth.md`.

## Architecture Constraints

- ACE-Step loads **one DiT model at a time**. Switching = restart subprocess (~10-30s).
- Single-GPU: worker auto-switches model per job. Multi-GPU (future): jobs route to the right queue. **UI is identical in both cases** — a dropdown.
- Turbo ignores `guidance_scale`. Parameter visibility must adapt to selected model.
- Cover/Repaint work with Turbo + SFT. Lego/Extract/Complete need Base (deferred — see `plans/base-model-tasks.md`).

---

## Phase 1: Per-Generation Model Selection + Parameter Visibility

### Phase 1a: Model Tagging (backend only, low risk)

**What**: Every generation records which model produced it.

- [ ] Add `model_mode: str` column to `Generation` (Alembic migration)
- [ ] Save `model_mode` when creating generation record in `jobs.py` (read from active model in Redis)
- [ ] Include `model_mode` in `GenerationResponse`

### Phase 1b: Worker Auto-Switch

**What**: Worker checks if the requested model matches the loaded model. If not, switches before processing.

**Depends on:** `plans/admin-sse-and-auth.md` Phase 3 (reinitialize as Job with SSE, `target_model` parameter, admin model dropdown). That plan provides the endpoint, Job tracking, SSE streaming, and admin UI. This phase implements the actual switching logic.

- [ ] Implement `AceStepManager.switch_model(target_model)` method
  - Kill ACE-Step subprocess
  - Restart with new `ACESTEP_CONFIG_PATH`
  - Wait for health
  - Update cached model in Redis
- [ ] In `reinitialize_acestep` worker function: replace the "not yet implemented" stub with `switch_model()` call
  - Update job progress: 0.0 (killing subprocess) → 0.5 (restarting) → 1.0 (health check passed)
  - SSE delivers progress to admin UI automatically (infrastructure from admin-sse-and-auth plan)
- [ ] In generate job: compare `requested_model` vs `active_model`
  - If different: call `switch_model()`, update job progress so frontend shows "Switching model..."
- [ ] Model config mapping in constants: `{"sft": "acestep-v15-sft", "turbo": "acestep-v15-turbo"}`
- [ ] If requested model is not in `AvailableModel` active list → fail the job with clear error

### Phase 1c: Model Dropdown + Parameter Visibility (frontend)

**What**: Users pick a model per generation. Parameters adapt to the selected model.

- [ ] Model dropdown in song editor generation settings
  - Shows only admin-enabled models from `GET /settings/models`
  - Defaults to user's preferred model (from preset or last used)
  - Selection is sent as `model_mode` on the generate request
- [ ] Add model capability metadata to `GET /settings/models` response
  - Which params each model supports (e.g. turbo: no `guidance_scale`)
  - Default values per model
  - Step range per model (turbo: 1-20, SFT: 1-200)
- [ ] Conditional parameter visibility based on **selected** model in dropdown
  - Hide `guidance_scale` when turbo is selected
  - Adjust `inference_steps` range/default per model
  - Preset chips filter to selected model_mode only
  - Hide inapplicable params entirely (no grayed-out fields)
- [ ] Show model badge on generation cards (which model produced it)
- [ ] Backend: log warning if ignored params are sent (e.g. guidance_scale with turbo), don't reject

---

## Phase 2: Repaint Mode

**What**: Edit a specific time section of an existing generation. Fix a wrong lyric, redo a chorus, change one verse. Works with Turbo + SFT. **Highest user value — directly solves "AI sang the wrong words."**

### Backend

- [ ] Add `task_type` field to `AceStepConfig` (default: `"text2music"`)
- [ ] Add `src_audio`, `repainting_start`, `repainting_end` fields
- [ ] `repainting_start` and `repainting_end` are floats 0.0-1.0 (fraction of duration, not seconds)
- [ ] Pass to ACE-Step: `task_type: "repaint"`, `src_audio`, `repainting_start`, `repainting_end`
- [ ] think_mode auto-disabled for repaint (ACE-Step requirement)
- [ ] Store task_type + repaint params in generation record
- [ ] Resolve src_audio from generation ID → file path on disk

### Frontend

- [ ] Waveform selection UI on existing generations
  - Display waveform of the generation
  - Drag handles to select a time range
  - Show selected range in seconds + as fraction
- [ ] Repaint dialog
  - Shows selected time range
  - User provides new lyrics/caption for that section
  - Option to keep or change style prompt
- [ ] Result: new generation (non-destructive — original preserved)
- [ ] Visual indicator showing repainted region on generation card

### UX Flow

Generation sounds great except 0:45-1:15 where the AI sings wrong lyrics → select that range on the waveform → write corrected lyrics → repaint → new generation with fixed section, surrounding audio intact.

---

## Phase 3: Cover Mode

**What**: Take an existing generation and re-interpret it with different style/lyrics while keeping melody structure. Works with Turbo + SFT.

> No dependency on file upload — cover uses an existing generation's audio file, already on disk.

### Backend

- [ ] Add `src_audio` and `audio_cover_strength` fields to `AceStepConfig` (if not already added in Phase 2)
- [ ] Pass to ACE-Step: `task_type: "cover"`, `src_audio: <path>`, `audio_cover_strength: <float>`
- [ ] Resolve src_audio from generation ID → file path
- [ ] Store task_type + cover params in generation record

### Frontend

- [ ] "Cover" action button on each generation in the generations list
  - Opens cover dialog/panel
  - Source: the selected generation's audio file (shown, not editable)
  - Strength slider (0.0 = free reinterpretation, 1.0 = strict structure)
  - User can modify caption + lyrics for the cover
- [ ] Result appears as a new generation linked to the same song version
- [ ] Visual indicator that a generation was produced via cover mode

### UX Flow

Listen to a generation → like the melody but not the style → click "Cover" → change prompt to "jazz version" → adjust strength → generate → new generation with same melody, different style.

---

## Phase 4: Reference Audio

**What**: Upload an external audio track to influence timbre/style of new generations. Works with any model + any task type.

### Backend

- [ ] File upload endpoint: `POST /api/audio/upload` → validate audio, save to persistent location, return ID
  - Accept common formats (mp3, wav, flac, ogg)
  - Size limit (50MB)
  - Store in audio directory (persistent, not temp — reusable across generations)
- [ ] Add `reference_audio` field to `AceStepConfig`
- [ ] Pass `reference_audio` path to ACE-Step `/release_task` payload
- [ ] Store reference_audio ID in version `generation_params`
- [ ] Cleanup: orphaned reference files (no version references them) via periodic task

### Frontend

- [ ] "Reference Track" upload button in generation settings
  - Drag-and-drop or file picker
  - Show filename + remove button when set
  - Audio preview/playback of uploaded reference
- [ ] Per-version storage — reference track is part of the version snapshot, reusable across regenerations

---

## Phase 5: Infinite Duration Generation

**What**: Chain repaint operations to generate songs longer than the model's limit (~4 min).

> Idea-stage, not fully designed. Needs exploration before implementation.

- [ ] Auto-chain: generate first segment, then repaint-extend from the end
- [ ] Seamless transitions via overlap + crossfade
- [ ] How do lyrics align across segments? Need to split lyrics by time
- [ ] Progress tracking for multi-segment generation
- [ ] Frontend: "Extend" button on generations

---

## What We're NOT Doing (Now)

- **Lego/Extract/Complete** — Base model only, deferred to `plans/base-model-tasks.md`
- **LoRA training UI** — too complex, use ACE-Step's Gradio UI directly
- **Audio codes manipulation** — power user feature, defer
- **Multi-model parallel loading** — one model at a time, single-GPU. Multi-GPU routing in `plans/multi-model-routing.md`
- **XL (4B DiT) models** — needs 12GB+ VRAM without offload, revisit when hardware allows
- **New turbo variants** (shift1, shift3, continuous) — add to AvailableModel when users request
- **Job queue sorting by model** — optimization for later if switching overhead becomes a problem

## Dependencies

- `plans/admin-sse-and-auth.md` → Phase 1b (provides Job/SSE infrastructure + admin model dropdown)
- Phase 1a → 1b → 1c (sequential within Phase 1)
- Phase 2 and 3 are **independent siblings** — both need `task_type` + `src_audio` on `AceStepConfig`, either can go first
- Phase 4 is independent (file upload, no dependency on 2 or 3)
- Phase 5 needs Phase 2 (repaint)

## Priority

Phase 1 (model selection) unblocks correct parameter handling. Phase 2 (repaint) is highest user value — directly fixes "wrong lyrics" problem. Phase 3 (cover) enables style iteration. Phase 4 (reference audio) is nice-to-have. Phase 5 is exploratory.

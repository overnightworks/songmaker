# ACE-Step Advanced Generation Modes

> **Status: IN PROGRESS** — Phases 1-3 complete, Phase 4 (Reference Audio) next

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

## Phase 1: Per-Generation Model Selection + Parameter Visibility ✅

### Phase 1a: Model Tagging ✅

- [x] Add `model_mode: str` column to `Generation` (Alembic migration `e5f6a7b8c9d0`)
- [x] Save `model_mode` via `resolve_model_mode(ctx.model_name)` in `jobs.py`
- [x] Include `model_mode` in `GenerationResponse`

### Phase 1b: Worker Auto-Switch ✅

- [x] `AceStepManager.switch_model(target_model)` — stop, set env, restart, wait, refresh
- [x] `MODEL_CONFIG_PATHS` constant: `{"sft": "acestep-v15-sft", "turbo": "acestep-v15-turbo"}`
- [x] `reinitialize_acestep` calls `switch_model()` (replaces stub)
- [x] `generate()` worker auto-switches when `requested_model != active_model`
- [x] Generate API validates model against admin-enabled `AvailableModel` list (not active model)
- [x] Model passed from API → arq → worker as positional arg

### Phase 1c: Model Dropdown + Parameter Visibility ✅

- [x] `ModelCapabilities` on `GET /settings/models` response (defaults, max_inference_steps, hidden_params)
- [x] Model dropdown in song editor (shows when >1 model active, sends `model_mode` to generate)
- [x] `ParamControls` hides params via `hiddenParams` prop (turbo: hides guidance_scale)
- [x] `ParamControls` adjusts inference_steps max via `maxInferenceSteps` prop
- [x] `PresetChips` filters to selected model_mode only
- [x] Model badge on generation cards in `GenerationsList`
- [x] Props threaded: `+page.svelte` → `SongEditor` → `GenerationSettings` → `ParamControls`/`PresetChips`

---

## Phase 2: Repaint Mode ✅

- [x] `task_type`, `src_audio`, `repainting_start/end`, `audio_cover_strength` on AceStepConfig
- [x] AceStepClient sends dynamic task_type + conditional repaint/cover fields
- [x] `POST /generations/{gen_id}/repaint` endpoint with range validation, WAV check, ownership
- [x] `RepaintRequest` model (range 0.0-1.0, optional lyrics/prompt override, model, seed)
- [x] `_apply_repaint_params()` — overrides config, forces think_mode=off
- [x] `StoredGenerationParams` stores task_type + repaint range
- [x] `RepaintDialog` component with range sliders, lyrics/prompt override
- [x] Repaint button on generation cards (only when WAV available)
- [x] `repaintGeneration()` frontend API function
- [ ] Waveform visualization (deferred — using range sliders for now, upgrade to canvas waveform later)

---

## Phase 3: Cover Mode ✅

- [x] `CoverRequest` model (strength 0.0-1.0, optional lyrics/prompt, model, seed)
- [x] `POST /generations/{gen_id}/cover` endpoint with ownership check, WAV validation
- [x] `_apply_cover_params()` — sets task_type=cover, forces think_mode=off
- [x] `audio_cover_strength` stored in `StoredGenerationParams`
- [x] `CoverDialog` component — strength slider, lyrics/prompt override
- [x] "Cover" button on generation cards (only when WAV available)
- [x] `coverGeneration()` frontend API function
- [x] `cover_params` threaded: API → arq → worker → `run_generation_job()`

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

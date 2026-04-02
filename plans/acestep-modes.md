# ACE-Step Advanced Generation Modes

> **Status: COMPLETE** — All phases implemented.

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

## Phase 4: Reference Audio ✅

- [x] `reference_audio` field on AceStepConfig, sent in client payload
- [x] `POST /api/audio/upload` — validates format (.mp3/.wav/.flac/.ogg), size (50MB), stores in `{user}/refs/{uuid}.ext`
- [x] `reference_audio` field on GenerationParams (stored in version generation_params)
- [x] Path resolved to absolute in `_build_generation_context()` (warns + clears if missing)
- [x] Reference track upload UI in GenerationSettings (file picker + clear button)
- [x] `uploadReferenceAudio()` frontend API function
- [ ] Cleanup: orphaned reference files (deferred — periodic task, low priority)
- [ ] Audio preview/playback of uploaded reference (deferred — nice-to-have)

---

## Related Plans

- **Infinite duration generation** — chained repaint for songs > 4 min → `plans/infinite-duration.md`
- **Lego/Extract/Complete** — Base model tasks → `plans/base-model-tasks.md`
- **Multi-GPU routing** — distributed workers → `plans/multi-model-routing.md`

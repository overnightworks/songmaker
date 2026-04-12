**Status:** Proposed
**Date:** 2026-04-12

# Generation Settings Refactor: Parameter Parity + Version/Preset Separation

## Goal

Two coupled problems:

1. **Version/preset blurring.** `Version.generation_params` stores creative content mixed with technical params. Changing `inference_steps` creates a new version identical in lyrics/prompt. Fix: versions own creative content only, technical params live in presets and get snapshotted onto the generation record.

2. **Missing ACE-Step parameters.** Gradio exposes params we don't have that affect quality/experimentation. Some are only available through Gradio's direct Python path, not the HTTP API our subprocess uses — we need to patch the vendored HTTP API to accept them.

## What already exists (extend, don't rebuild)

- Admin panel (`admin_api.py`): workers, models, VRAM, users, audit, rate limits
- Presets (`GenerationPreset`, `settings_api.py`): named, per-model-mode, user-scoped
- Admin global defaults per model mode
- Model capabilities (`acestep_capabilities.py`): per-mode hidden params, max values
- Generation params schema (`BaseGenerationParams`, `StoredGenerationParams`)
- Layered config resolution (`config.py`): builtin < global admin < preset < song meta

## A. Decouple version from generation params

**Current:** `Version.generation_params` (JSONB) holds everything.

**Target:** `Version` drops `generation_params`. Versions are creative-only: lyrics, prompt, BPM, key, time_signature, duration, vocal_language.

**Where do in-progress params live?** Frontend store holds ephemeral param state (already does this). When user hits Generate, resolved params get snapshotted onto the `Generation` record.

**Generation record gets:** `preset_id` (FK, nullable, informational — "I started from this preset") + `generation_params` (JSONB, the fully resolved snapshot — the receipt). The preset is the starting point; the generation record is the immutable receipt. Editing a preset later does not retroactively change what a generation used.

**Migration:** Simple. Existing `generation.generation_params` already stores resolved params. Just stop writing to `version.generation_params` for new versions. Old versions keep their data but it's ignored. Old generations keep their stored params unchanged.

## B. Add missing ACE-Step params

### HTTP API gap

Gradio calls `generate_music()` directly (Python). Our acestep-worker calls the HTTP `/release_task` endpoint. Five params exist in the internal `GenerationParams` dataclass but are NOT exposed on the HTTP API:

| Parameter | In HTTP API | In Gradio | Action |
|---|---|---|---|
| `sampler_mode` | NO | YES | Patch vendored HTTP API |
| `velocity_norm_threshold` | NO | YES | Patch vendored HTTP API |
| `velocity_ema_factor` | NO | YES | Patch vendored HTTP API |
| `latent_shift` | NO | YES | Patch vendored HTTP API |
| `latent_rescale` | NO | YES | Patch vendored HTTP API |
| `timesteps` (custom) | YES | YES | Already wired, just not exposed in our UI |
| `lm_codes_strength` | Likely NO | YES | Verify, then patch if needed |

**Patch scope:** Add these to `release_task_models.py` (request model) + `release_task_param_parser.py` (aliases) + `release_task_request_builder.py` (builder) + `job_generation_setup.py` (wiring to `GenerationParams`). The params already exist on the internal dataclass — we just expose them on the HTTP surface.

**Risk:** Maintaining a fork delta on vendored ACE-Step code. Each upstream update needs these patches re-applied. Keep the patch minimal and well-documented.

### Our side

Add to `BaseGenerationParams`, `AceStepConfig`, and `client.py` payload:
- `sampler_mode`, `custom_timesteps`, `velocity_norm_threshold`, `velocity_ema_factor`, `lm_codes_strength`, `latent_shift`, `latent_rescale`

Update `acestep_capabilities.py` for ranges/visibility per model mode. Run `generate_types.py`.

## C. Frontend preset/settings restructure

Split "Generation Settings" flat list into two collapsible sections:
- **DiT (Sound)**: inference_steps, guidance_scale, shift, infer_method, sampler_mode, use_adg, cfg_interval_start/end, custom_timesteps, velocity_norm_threshold, velocity_ema_factor, latent_shift, latent_rescale
- **LM (Lyrics Interpretation)**: temperature, top_k, top_p, cfg_scale, repetition_penalty, thinking, use_cot_caption, use_cot_language, negative_prompt, lm_codes_strength

Preset picker stays at the top. "CUSTOM" shows sections. "INHERIT" uses preset defaults.

## What we skip

| Feature | Why |
|---|---|
| Audio Output & Post-processing | Our mastering chain, not per-song configurable |
| Automation & Batch | Our job queue |
| LoRA | Separate backlog item |
| Service config (device/compile/INT8/MLX) | Already in admin panel |

## Hard constraints

- Existing generations keep their stored params unchanged
- Seed pinning must work: pin seed, change preset, regenerate
- `sampler_mode` is high priority — euler_ancestral is the only xl-sft workaround (GitHub ACE-Step-1.5 #1063)
- Vendored ACE-Step HTTP API patches must be minimal and documented for upstream re-sync

## First step

Read the live code: `db/models.py`, `api_models/generation_params.py`, `config.py`, `GenerationSettings.svelte`, `presets.ts`, vendored `release_task_models.py`. Design schema changes + ACE-Step patch + migration, then execute.

**Status:** Proposed
**Date:** 2026-04-13 (revised)

# Generation Settings Refactor: Parameter Parity + Version/Preset Separation

## Goal

Two coupled problems:

1. **Version/preset blurring.** `Version.generation_params` stores creative content mixed with technical params. Changing `inference_steps` creates a new version identical in lyrics/prompt. Fix: versions own creative content only, technical params live in presets and get snapshotted onto the generation record.

2. **Missing ACE-Step parameters.** The fork's HTTP API (`vendor/acestep`) already exposes all params. Our songmaker layer (`BaseGenerationParams`, `AceStepConfig`, `AceStepProfile`) doesn't wire them through yet.

## What already exists (extend, don't rebuild)

- Admin panel (`admin_api.py`): workers, models, VRAM, users, audit, rate limits
- Presets (`GenerationPreset`, `settings_api.py`): named, per-model-mode, user-scoped
- Admin global defaults per model mode
- Model capabilities (`acestep_capabilities.py`): per-mode hidden params, max values
- Generation params schema (`BaseGenerationParams`, `StoredGenerationParams`)
- Layered config resolution (`config.py`): builtin < global admin < preset < song meta

## A. Wire missing ACE-Step params into songmaker

The fork's HTTP API already has all params on the `/release_task` surface. No vendor patching needed — just wire them into our layer.

### Params to add

| Parameter | ACE-Step name | Default | What it does |
|---|---|---|---|
| `sampler_mode` | `sampler_mode` | `"euler"` | Diffusion sampler. `euler_ancestral` is the xl-sft quality workaround (#1063) |
| `velocity_norm_threshold` | `velocity_norm_threshold` | `0.0` | DiT velocity normalization threshold |
| `velocity_ema_factor` | `velocity_ema_factor` | `0.0` | DiT velocity EMA smoothing |
| `latent_shift` | `latent_shift` | `0.0` | Latent space shift |
| `latent_rescale` | `latent_rescale` | `1.0` | Latent space rescale factor |
| `audio_cover_strength` | `audio_cover_strength` | `1.0` | Fraction of DiT steps using LM-generated codes. Higher = follows LM plan, lower = DiT creative freedom |

Use ACE-Step server names as-is — the server is the source of truth for param naming.

### Files to touch

- `api_models/generation_params.py`: add to `BaseGenerationParams` + `StoredGenerationParams`
- `acestep_engine/models.py`: add to `AceStepConfig`
- `acestep_capabilities.py`: add `ParamSupport` per mode
- `config.py`: add to `_BUILTIN_DEFAULTS` per mode
- `jobs/generation.py`: persist to `StoredGenerationParams` in `_persist_generation_row()`
- Run `generate_types.py`

## B. Decouple version from generation params

**Current:** `Version.generation_params` (JSONB) holds everything.

**Target:** `Version` drops `generation_params`. Versions are creative-only: lyrics, prompt, BPM, key, time_signature, duration, vocal_language.

**Where do in-progress params live?** Frontend store holds ephemeral param state (already does via `editGenParams`). When user hits Generate, resolved params get snapshotted onto the `Generation` record.

**"Pin settings" from a generation:** Like seed pinning — a "Use these settings" button on any generation copies its stored params into the frontend settings panel. No formal `preset_id` FK needed on Generation; the generation record is the immutable receipt, the pin action is just "copy this receipt into my current draft."

**Migration:** Stop writing to `Version.generation_params` for new versions. Old data stays for reference. Clean up column later.

## C. Frontend preset/settings restructure

Split "Generation Settings" flat list into two collapsible sections:
- **DiT (Sound)**: inference_steps, guidance_scale, shift, infer_method, sampler_mode, use_adg, cfg_interval_start/end, velocity_norm_threshold, velocity_ema_factor, latent_shift, latent_rescale, audio_cover_strength
- **LM (Lyrics Interpretation)**: temperature, top_k, top_p, cfg_scale, repetition_penalty, thinking, use_cot_caption, use_cot_language, negative_prompt

Preset picker stays at the top. "CUSTOM" shows sections. "INHERIT" uses preset defaults.

Add "Use these settings" button on generation detail view (copies stored params into draft).

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
- Use ACE-Step server param names (not Gradio UI labels)

## First step

Read the live code: `api_models/generation_params.py`, `acestep_engine/models.py`, `config.py`, `acestep_capabilities.py`, `GenerationSettings.svelte`, `ParamControls.svelte`. Wire the 6 missing params (section A), then proceed to B and C.

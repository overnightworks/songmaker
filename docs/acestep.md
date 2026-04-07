# ACE-Step Integration

Upstream: [ACE-Step 1.5 v0.1.6](https://github.com/ace-step/ACE-Step-1.5)

## How Songmaker Uses ACE-Step

ACE-Step runs in dedicated `acestep-worker-N` peer containers, one per GPU. Each
worker hosts a FastAPI wrapper (`src/acestep_worker/wrapper.py`) that manages
an LRU cache of loaded models and exposes:

| Method | Path | Purpose |
|---|---|---|
| POST | `/load_model` | Load a model variant into VRAM (idempotent) |
| POST | `/evict_model` | Evict from VRAM |
| POST | `/generate` | Submit generation, returns `{task_id}` |
| GET | `/tasks/{id}/stream` | SSE: `progress`/`done`/`error` events |
| GET | `/loaded_models` | Current state for heartbeat |
| GET | `/health` | Liveness |

Workers self-register with the web container at startup
(`POST /api/internal/workers/register`) and heartbeat ephemeral state to
Redis with a 15s TTL. The `acestep_engine.client.AceStepClient` lives inside
the worker container and talks to the upstream ACE-Step subprocess on
`127.0.0.1:8101`.

```
music worker (songmaker_cli.music_worker.MusicWorkerSettings)
  → on generate job:
    → scheduler.dispatch_generation:
      → pick worker (PG identities + Redis state)
      → INCR queue_depth (Redis)
      → POST /load_model on worker (if needed)
      → POST /generate on worker → task_id
      → consume SSE /tasks/{id}/stream until done
      → DECR queue_depth in finally
    → post_process_generation (in to_thread):
      → read worker WAV from shared volume
      → decode + splice (if repaint) + master + encode MP3
      → INSERT generation row

scoring worker (songmaker_cli.scoring_worker.ScoringWorkerSettings)
  → on score job:
    → load faster-whisper + AudioBox on demand
    → BPM, silence, spectral, text accuracy, aesthetics
```

Client: `src/acestep_engine/client.py` (HTTP client with retry, polling, model info)
Config: `src/songmaker_cli/config.py` (`build_ace_config()` merges defaults + user settings + song params)
Scheduler: `src/songmaker_cli/scheduler.py` (worker picker + SSE consumer with reconnect)

## Model Variants

| Model | Steps | Speed | Quality | Use case |
|-------|-------|-------|---------|----------|
| `acestep-v15-turbo` | 8 | ~10s on 3090 | Very good | Fast iteration |
| `acestep-v15-sft` | 50 | ~60s on 3090 | Best (2B) | Final renders |
| `acestep-v15-xl-turbo` | 8 | ~15s on 3090 | Excellent | Fast iteration (4B) |
| `acestep-v15-xl-sft` | 50 | ~90s on 3090 | Best overall | Final renders, default |
| `acestep-v15-xl-base` | 50 | ~90s on 3090 | Excellent | Supports ADG, extract, lego |

XL models (4B DiT) require ~12GB VRAM with offload, 20GB+ recommended.

LM models (text planner):
- `acestep-5Hz-lm-0.6B` — creative, good structure
- `acestep-5Hz-lm-4B` — more thorough planning (recommended with XL)

## Generation Parameters

Parameters can be set per-song (`generation_params` in version), per-model-type (admin defaults), or globally.

Priority: song params > admin defaults > model defaults.

| Parameter | Range | Default (turbo) | Default (SFT) | Effect |
|-----------|-------|-----------------|---------------|--------|
| `inference_steps` | 1-200 | 8 | 50 | More = slower, potentially higher quality |
| `guidance_scale` | 0-50 | 0.0 | 0.0 | CFG strength (turbo ignores this) |
| `shift` | 0-100 | 3.0 | 3.0 | 1.0 = natural/emotional, 3.0 = accurate lyrics |
| `lm_temperature` | 0-5 | 0.85 | 0.85 | Higher = more creative (try 1.1-1.2) |
| `lm_top_k` | 0-1000 | — | — | LM sampling top-k |
| `lm_top_p` | 0-1 | — | — | LM sampling nucleus |
| `lm_cfg_scale` | 0-50 | — | — | LM classifier-free guidance |
| `lm_negative_prompt` | string | — | — | What to avoid |
| `infer_method` | ode/sde | ode | ode | sde = more textured/alive |
| `think_mode` | string | true | true | false = more creative, true = more structured |
| `lm_repetition_penalty` | 0.5-5 | 1.0 | 1.0 | Penalize LM token repetition |
| `batch_size` | 1-8 | 1 | 1 | Parallel generations per request |
| `duration` | 1-600 | 180 | 180 | Output length in seconds |
| `bpm` | 0-999 | 120 | 120 | 0 = let model decide |
| `use_cot_caption` | bool | true | true | LM chain-of-thought caption rewriting |
| `use_cot_language` | bool | true | true | LM chain-of-thought language detection |
| `constrained_decoding` | bool | false | false | FSM-based structured LM output |
| `timesteps` | string | — | — | Custom diffusion schedule (comma-separated floats) |
| `use_adg` | bool | false | false | Adaptive Dual Guidance (base model only) |
| `cfg_interval_start` | 0-1 | 0.0 | 0.0 | CFG application start fraction |
| `cfg_interval_end` | 0-1 | 1.0 | 1.0 | CFG application end fraction |

## Modes

All modes use the same upstream ACE-Step task endpoint with different `task_type` + audio inputs. If the requested model isn't loaded on the chosen worker, the scheduler issues `POST /load_model` before `POST /generate`.

| Mode | task_type | Trigger | What It Does |
|------|-----------|---------|--------------|
| Text2Music | `text2music` | Generate button | Generate from scratch (default) |
| Repaint | `repaint` | Repaint button on generation | Edit a time section — fix wrong lyrics, redo a chorus |
| Cover | `cover` | Cover button on generation | Re-interpret with different style/lyrics, keep melody |
| Reference | `text2music` + `reference_audio` | Upload in generation settings | Guide timbre/style from an external audio track |

**Repaint** sends `src_audio` (the original WAV), `repainting_start` and `repainting_end` (0.0-1.0 fractions). `think_mode` is auto-disabled. The result is a new generation — non-destructive. v0.1.6 adds server-side crossfade controls:
- `repaint_mode`: `conservative` / `balanced` / `aggressive` — how much source audio is preserved
- `repaint_strength`: 0-1, intensity for balanced mode
- `repaint_latent_crossfade_frames`: latent-level boundary blend width
- `repaint_wav_crossfade_sec`: waveform-level splice crossfade

When `repaint_mode` or `repaint_wav_crossfade_sec` is set, the server handles crossfading and the client-side splice (`_splice_repaint_raw`) is skipped.

**Cover** sends `src_audio` and `audio_cover_strength` (0.0 = free reinterpretation, 1.0 = strict structure). `think_mode` is auto-disabled. v0.1.6 adds `cover_noise_strength` (0-1) for noise blending control.

**Reference audio** uploads via `POST /api/audio/upload` (max 50MB, .mp3/.wav/.flac/.ogg). The path is stored in version `generation_params.reference_audio` and resolved to an absolute path before sending to ACE-Step. Path traversal is blocked at both API validation and job execution levels.

## CoT Response Data

The server returns `cot_caption` and `cot_lyrics` in generation results — the LM's chain-of-thought rewritten caption and lyrics. These are stored in `generation_params` and displayed in the frontend generation detail. Useful for understanding how the LM interpreted your prompt. Disable with `use_cot_caption: false` / `use_cot_language: false`.

**Not yet integrated**: Lego, Extract, Complete (require Base model — see `plans/base-model-tasks.md`). Infinite duration (exploratory — see `plans/acestep-modes.md` Phase 5).

## Environment Variables

| Var | Default | Purpose |
|-----|---------|---------|
| `ACESTEP_API_PORT` | 8001 | ACE-Step server port |
| `ACESTEP_CONFIG_PATH` | acestep-v15-sft | DiT model to load |
| `ACESTEP_INIT_LLM` | 1 | Load LM on startup |
| `ACESTEP_LM_MODEL_PATH` | acestep-5Hz-lm-4B | LM model |
| `ACESTEP_LM_BACKEND` | vllm | LM inference backend |
| `MAX_CUDA_VRAM` | 24 | VRAM budget in GB |
| `ACESTEP_COMPILE_MODEL` | 0 | torch.compile (slower startup, faster inference) |

## Local Submodule Patch — VRAM Pre-flight

The `_models/acestep` submodule (pinned at v0.1.6) has a **local patch** that must be reapplied after any `git submodule update`.

**File:** `_models/acestep/acestep/core/generation/handler/generate_music.py` (around line 325)

**Change:** Replace the `_vram_preflight_check()` call with `gc.collect()` + `torch.cuda.empty_cache()`.

**Why:** v0.1.6 added a VRAM pre-flight check that's overly conservative on 24 GB cards when the desktop shares the GPU. It reports e.g. "1.3 GB free, needs 1.4 GB" and blocks generation, even though PyTorch's caching allocator can handle it. The check did not exist in v0.1.5 and songs generated fine. See ACE-Step issue #822 for similar reports.

**Patch:**
```python
# In GenerateMusicMixin.generate_music(), replace:
vram_error = self._vram_preflight_check(
    actual_batch_size=actual_batch_size,
    audio_duration=audio_duration,
    guidance_scale=guidance_scale,
)
if vram_error is not None:
    return vram_error

# With:
gc.collect()
torch.cuda.empty_cache()
```

**No upstream option exists** — no env var, config flag, or API parameter disables the pre-flight. Only `offload_to_cpu=True` bypasses it (too slow).

**When you can remove this patch:** When the GPU has enough spare VRAM that the check passes reliably (e.g., after adding a second GPU for desktop+scoring, freeing the 3090). Or when ACE-Step adds an official skip flag upstream.

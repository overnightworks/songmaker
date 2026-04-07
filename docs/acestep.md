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

### Downloading models

The Admin → ACE-Step → Model Registry panel has a **Download** button on each row that's marked `not downloaded`. Clicking it enqueues a `download_model_on_worker` arq job that picks an online worker, calls `POST /download_model` on the worker, and streams progress (via the worker's `/tasks/{id}/stream` SSE → PG `Job` row → the existing `/api/jobs/{id}/stream` poll loop → the browser). Once `huggingface_hub.snapshot_download` finishes, the worker's next 5-second heartbeat publishes the new `available_modes` and the registry row flips to ✓ downloaded within ~10 seconds.

Concurrency guard: a Redis flag (`songmaker:acestep:download:{mode}`, 30-minute TTL) prevents two concurrent downloads of the same mode. The flag is set in the arq job's `try` block and cleared in `finally`; the TTL is the safety net for crashed workers.

For bootstrap (no worker yet running, fresh install, CI), use the CLI escape hatch instead: `bash scripts/download_models.sh` calls `huggingface_hub.snapshot_download` directly into `_models/acestep/checkpoints/`. Requires `HF_TOKEN` exported in the host shell.

## Operating the worker pool

This section is the operator-facing reference for the ACE-Step worker pool architecture (Phases 1–6). For the cross-cutting flow (web → music-worker → acestep-worker) see [architecture.md](architecture.md). For trust boundaries and the internal token, see [security.md](security.md).

### Prometheus metric keys

The web container's `/metrics` endpoint exposes the following worker pool gauges (in addition to the existing HTTP, jobs, queue depth, and GPU VRAM metrics):

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `songmaker_acestep_workers_total` | gauge | `status="online\|loading\|offline"` | Count of registered workers in each status. `online` = heartbeat fresh and not currently loading a model. `loading` = heartbeat fresh and `target_loading` is non-null. `offline` = no heartbeat in the last 15 s (Redis TTL). |
| `songmaker_acestep_worker_loaded_models` | gauge | `worker_id="..."` | Number of models currently in the cache for that worker. Always emitted for every registered worker, including offline ones (offline workers report 0). |
| `songmaker_acestep_worker_queue_depth` | gauge | `worker_id="..."` | Per-worker generation queue depth, read from Redis. |

**Useful Prometheus queries:**

- `sum(songmaker_acestep_workers_total) > 0` — at least one worker is registered
- `songmaker_acestep_workers_total{status="online"} == 0 and songmaker_acestep_workers_total{status="loading"} == 0` — pool is unhealthy (alert!)
- `sum(songmaker_acestep_worker_queue_depth)` — total backlog across all workers
- `max by (worker_id) (songmaker_acestep_worker_loaded_models)` — distribution of cached models per worker

**Histograms (deferred):** `songmaker_acestep_model_load_duration_seconds`, `songmaker_acestep_generation_duration_seconds`, and `songmaker_acestep_download_duration_seconds` are NOT in the current `/metrics` output. They need persistent state across requests (`prometheus_client.Histogram`), which would force a new dependency. They're listed for a follow-up phase. For now, use the `Job.started_at`/`completed_at` columns directly via SQL for ad-hoc duration analysis.

### Redis key namespace reference

Operators need to know what's in Redis to debug stuck state. Keys to know:

| Key pattern | Set by | Read by | TTL | Purpose |
|---|---|---|---|---|
| `songmaker:acestep:worker:{worker_id}` | `acestep-worker` heartbeat loop (every 5 s) | `admin_api` `/admin/workers`, `scheduler.pick_worker`, `/health`, `/metrics` | 15 s | Ephemeral worker state — JSON object with `loaded`, `target_loading`, `vram_used_gb`, `vram_total_gb`, `available_modes`, `queue_depth`, `last_heartbeat_at` |
| `songmaker:acestep:queue:{worker_id}` | `scheduler.incr_queue_depth` / `decr_queue_depth` (per generation dispatch) | `admin_api`, `scheduler.pick_worker`, `/metrics` | none | Per-worker generation queue depth (atomic counter) |
| `songmaker:acestep:download:{mode}` | `download_model_on_worker` arq job (atomic SET-NX) | admin endpoint pre-check, arq job duplicate guard | 1800 s | Download-in-progress flag; value is the job_id of the arq job that owns it |

**Useful debug commands:**

```bash
docker compose exec redis redis-cli KEYS 'songmaker:acestep:*'
docker compose exec redis redis-cli GET 'songmaker:acestep:worker:acestep-worker-0'
docker compose exec redis redis-cli TTL 'songmaker:acestep:worker:acestep-worker-0'
docker compose exec redis redis-cli GET 'songmaker:acestep:download:xl-base'
```

If a download appears stuck, check the `download:{mode}` key. If it exists but no arq job is running with that ID, it's a stale flag — delete it manually and the next click will re-acquire:

```bash
docker compose exec redis redis-cli DEL 'songmaker:acestep:download:xl-base'
```

The flag's 30-minute TTL is the automatic safety net for crashed arq workers.

### Worker startup procedure

When an `acestep-worker` container starts:

1. The FastAPI server comes up immediately and binds `0.0.0.0:8001`.
2. `/health` returns **503** with detail `"awaiting control plane registration"`.
3. A background task tries to register with the control plane (`POST /api/internal/workers/register`). Backoff schedule: **1s → 2s → 5s → 10s → 30s → 60s ± 20% jitter forever**. The worker does not give up.
4. Container logs show one startup banner (`"acestep-worker {id} starting; awaiting control plane at {url}"`) plus per-attempt warnings on each failed registration.
5. Once registration succeeds, the log emits `"Worker {id} registered with control plane"`, `/health` flips to **200 OK**, the docker healthcheck flips to healthy, and traffic flows.
6. The heartbeat loop (separate from the registration task) starts publishing to `songmaker:acestep:worker:{id}` every 5 s.

If a worker is stuck in step 3:

- Check container logs for the per-attempt warning lines (`"Registration attempt N failed: ..."`)
- Verify the control plane URL is reachable from inside the worker container: `docker compose exec acestep-worker-0 curl -v http://songmaker-web:8080/health`
- Verify `SONGMAKER_INTERNAL_TOKEN` matches between the worker and the web container env

The cancel-on-shutdown behavior: if the worker is shut down (SIGTERM, container stop) while still in the registration loop, the lifespan finally block cancels the registration task and awaits its cleanup before exiting. No orphaned tasks survive shutdown.

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

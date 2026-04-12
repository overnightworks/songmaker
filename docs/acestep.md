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

For bootstrap (no worker yet running, fresh install, CI), use the CLI escape hatch instead: `bash scripts/download_models.sh` calls `huggingface_hub.snapshot_download` directly into `vendor/acestep/checkpoints/`. Requires `HF_TOKEN` exported in the host shell.

## Operating the worker pool

This section is the operator-facing reference for the ACE-Step worker pool architecture (Phases 1–6). For the cross-cutting flow (web → music-worker → acestep-worker) see [architecture.md](architecture.md). For trust boundaries and the internal token, see [security.md](security.md).

### Building the worker images

As of Phase 8, the worker images form a small hierarchy with reusable base layers. Building them naively with `docker compose build` will fail because compose doesn't understand the base→leaf dependency. Use the orchestration script:

```bash
scripts/build_images.sh           # build everything (bases + leaves)
scripts/build_images.sh bases     # bases only
scripts/build_images.sh leaves    # compose leaves only (assumes bases exist)
```

**Image hierarchy:**

```
python:3.12-slim
  ├── songmaker/gpu-torch-base   (torch 2.10+cu128 + cudnn — heavy CUDA layer)
  │     └── songmaker/acestep-base   (upstream ACE-Step source + delta deps at /opt/acestep)
  │           └── songmaker-acestep-worker   (wrapper venv + entrypoint)
  ├── songmaker-music-worker     (server extras only — no torch, no scoring)
  ├── songmaker-scoring-worker   (server + scoring + whisper, CPU torch)
  └── songmaker-web              (server extras + frontend build, no torch)
```

**The rule:** if you edit any `docker/base/*.Dockerfile`, run `scripts/build_images.sh` first before `docker compose up --build`. Otherwise compose fails with `manifest unknown` for `FROM songmaker/acestep-base:latest`.

**The inner ACE-Step venv is baked into `acestep-base` at `/opt/acestep/.venv`.** Pre-Phase-8, it lived in a host bind mount that uv re-resynced from scratch on every fresh container (5–15 minute model-load gate). Now it's in the image. The bind mount on `acestep-worker` only carries `./vendor/acestep/checkpoints` → `/opt/acestep/checkpoints` (the multi-GB model weights). The upstream source tree, the `.venv`, and everything else under `vendor/acestep/` is COPYed into the image at build time.

The `ARQ_JOB_TIMEOUT=1800` workaround in `.env` is no longer needed. Workers default to `ARQ_JOB_TIMEOUT=1000` and `ACESTEP_STARTUP_TIMEOUT_SECONDS=900` — long enough for a cold xl-turbo + vLLM init, which can take 5–8 min on a fresh container with empty page/JIT caches. If you have an older shorter override in your local `.env`, drop it.

**Music-worker image bloat fix:** prior to Phase 8, music-worker shared `Dockerfile.worker` with scoring-worker and carried ~5 GB of unused torch + scoring + whisper wheels. Phase 8 split that file into `docker/music-worker.Dockerfile` (server extras only) and `docker/scoring-worker.Dockerfile` (server + scoring + whisper). Music-worker is now ~860 MB. This is safe because music-worker's import chain (`music_worker.py` → `jobs.py` → `scoring.{pipeline,models}`) is torch-free at module load — torch imports inside the scoring stack are lazy (inside function bodies) and music-worker never registers `run_scoring_job`.

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

### Restart procedure

The Worker Pool admin panel has a **Restart** button per card. Clicking it (after a confirm dialog) calls `POST /api/admin/workers/{id}/restart`, which proxies to the worker's `POST /restart` endpoint. The worker logs the restart request, schedules `os.kill(os.getpid(), SIGTERM)` after a 100 ms delay (so the HTTP response is flushed first), and returns `{"status": "restarting", "pid": ...}`.

The container is running with `restart: unless-stopped`, so docker compose brings it back up automatically. The new process goes through the normal startup sequence above (FastAPI bind → `/health` 503 → register → `/health` 200). Expected total downtime: ~10–15 s.

**In-flight generations fail.** Restarting kills the worker process, including any subprocess holding a generate task. Affected jobs surface as `error_type=worker_unreachable` in the user's job list. Restart only when the operator is willing to lose the in-flight work.

To verify the restart cycle from the admin UI: the Worker Pool card flips `online → offline → loading → online` over the cycle. The transitions are visible because the heartbeat TTL (15 s) outlasts the brief downtime.

### pin_model semantics

The cache is normally LRU: when a new `load_model` would exceed the VRAM budget, the least-recently-used loaded model is evicted to make room. **Pinning** marks a loaded model as exempt from LRU eviction. Use it when a single-GPU multi-user deployment has a "must always be loaded" preference (e.g. the operator wants `sft` to stay resident regardless of how many other modes get loaded).

How pinning interacts with the cache:

- `POST /api/admin/workers/{id}/pin_model` requires the model to already be loaded (returns 409 otherwise).
- `_evict_to_fit` skips pinned **and** in-use models when picking an LRU victim.
- If **all** loaded models are pinned and a new load doesn't fit, the cache raises `CapacityError` with a clear message naming the pinned set. The admin must explicitly unpin one before the next load can succeed.
- Explicit `evict_model` (the admin "Evict X" button) unpins implicitly — the operator asked for it. `_evict_to_fit` (LRU) does not unpin.
- Worker shutdown (`evict_all`) drains everything regardless of pin state.

Pin/unpin from the admin UI: each loaded-mode row in the Worker Pool card has a **Pin** / **Unpin** button next to its **Evict** button. The button reflects the current state from the heartbeat (`pinned: list[str]`).

### Load-while-generating refcount

Generations and model loads share the same cache. Without coordination, an admin who loads a different mode mid-generation would evict the in-use model and crash the running generation with a stale subprocess handle. The worker uses a **per-mode refcount**:

- The worker's `/generate` endpoint calls `cache.acquire_for_use(mode)` before spawning the runner. If the mode isn't loaded the endpoint returns 409.
- The runner spawn is wrapped in a `try/finally` that calls `cache.release(mode)` on completion (success **or** exception **or** cancellation).
- `_evict_to_fit` skips both pinned and in-use models (refcount > 0). If no eligible victim exists, the load fails with `CapacityError`.
- Explicit `evict_model` refuses to evict a mode with refcount > 0 (returns 409 with the in-flight count).

The user-visible failure mode: if an admin tries to load a model that would require evicting an in-use one, the load job ends `failed` with a clear "all eligible models are in use or pinned" message in the job-tracking UI. The running generation continues unharmed.

### Download auto-retry

`download_model_on_worker` retries the SSE consumption phase up to **3 attempts** with linear backoff (5s → 10s) on the narrow set of transient failure modes:

- `WorkerTaskFailed` — the worker emitted an `error` SSE event (HF rate limit 429, transient HF blip, file system hiccup). Re-submission triggers a fresh `start_download`; HF `snapshot_download` resumes from cache.
- `httpx.RemoteProtocolError` / `httpx.ReadError` — the SSE stream broke mid-flight (worker process crashed, connection reset).

Terminal (no retry) failure modes:

- `httpx.ConnectError` — worker unreachable. Surfaced as `error_type=sse_transport`.
- HTTP 4xx/5xx on the `POST /download_model` submit — `error_type=worker_error`.
- `NoCapacityError` — no online workers — `error_type=no_workers`.
- Unknown mode — `error_type=invalid_mode`.

The Redis flag (`songmaker:acestep:download:{mode}`) is held across all retry attempts via the function-level `try/finally` — concurrent admin clicks for the same mode are still rejected with 409 during the retry window. The flag is cleared exactly once when the function returns, regardless of which attempt succeeded or whether the retry budget was exhausted.

### Troubleshooting playbooks

**"Worker won't register"** — `/health` returns 503. Check container logs for `"Registration attempt N failed: ..."`. Verify the control plane URL is reachable from inside the worker container with `docker compose exec songmaker-acestep-worker-0 curl -v http://songmaker-web:8080/health`. Verify `SONGMAKER_INTERNAL_TOKEN` matches between worker and web. The retry loop never gives up — fix the root cause and the next backoff tick will succeed.

**"Download stalls"** — check the download flag: `docker compose exec redis redis-cli GET 'songmaker:acestep:download:{mode}'`. Cross-reference the value (a job_id) with the job's status in the admin UI. If the job is gone but the flag remains, it's stale — `redis-cli DEL` it and retry. The 30-minute TTL is the automatic safety net.

**"Load fails with CapacityError"** — the message includes the loaded set, the pinned set, and the in-use set. If the in-use set is non-empty, wait for those generations to finish; if it's all pinned, unpin one explicitly. The Worker Pool card's per-mode buttons make this directly actionable.

**"Stale-job reaper killed my long generation"** — the reaper looks at `Job.last_heartbeat_at`. The arq job calls `_touch_heartbeat` on every SSE progress event from the worker (which fires every ~2 s for downloads, every ~1–5 s for generation steps). If a long task is being killed unexpectedly, check whether the on_progress callback is wired into the SSE consumer — the contract is that *every* yielded event refreshes the heartbeat, not just the milestone events.

For the cross-cutting flow (web → music-worker → acestep-worker), see [architecture.md](architecture.md). For the trust boundaries and the internal token, see [security.md](security.md).

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
| `use_adg` | bool | false | false | Adaptive Projected Guidance (no-op on turbo; honored on sft/base when `guidance_scale > 1.0`) |
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

There are two layers of env vars: ones the **acestep-worker container** reads at startup (managed by `WorkerSettings` in `src/acestep_worker/settings.py`) and ones the worker passes to the **ACE-Step subprocess** when it spawns it (set in `src/acestep_worker/subprocess_runner.py:build_env()`).

### Worker container env vars (`WorkerSettings`)

These are set on the `songmaker-acestep-worker-0` container in `docker-compose.yml` and read by the worker's Pydantic `Settings` at startup. `extra="forbid"` — typo'd names raise `ValidationError`.

| Var | Default | Purpose |
|-----|---------|---------|
| `WORKER_ID` | (required, no default) | Unique ID for this worker instance |
| `WORKER_HOST` | None | Hostname this worker advertises to the control plane |
| `WORKER_PORT` | 8001 | Port the worker's FastAPI app listens on |
| `REDIS_URL` | (required) | Redis URL for heartbeat publishing |
| `CONTROL_PLANE_URL` | None | Songmaker web URL for worker registration. If unset, registration is skipped. |
| `SONGMAKER_INTERNAL_TOKEN` | None | Shared secret for control-plane auth. Empty/None disables registration. |
| `VRAM_BUDGET_GB` | 24.0 | VRAM budget in GB. Passed to the ACE-Step subprocess as `MAX_CUDA_VRAM`. Lower values (e.g. 22 on a 24 GB card) cause ACE-Step to auto-fall-back to CPU VAE decode during xl-turbo generation, which is ~100x slower than GPU — raise the budget if the admin panel shows very slow xl-turbo generations at ~0% GPU util. |
| `GPU_ID` | None | CUDA device index (for `CUDA_VISIBLE_DEVICES`) |
| `ACESTEP_CHECKPOINT_DIR` | `/opt/acestep` | Where ACE-Step model weights live |
| `AUDIO_OUTPUT_DIR` | `/app/data/audio/worker_output` | Where the subprocess writes generated WAVs |
| `ACESTEP_LOG_DIR` | `/opt/acestep/logs` | Where the subprocess's merged stdout+stderr is captured. Each load attempt appends a `=== {mode} attempt at {iso} ===` header so retry history isn't clobbered. Also forwarded line-by-line to the worker's own logger as `[ace-step {mode}] ...` (visible in `docker compose logs songmaker-acestep-worker-0`). |
| `ACESTEP_INNER_PORT` | 8101 | Port the ACE-Step subprocess listens on (inside the container) |
| `ACESTEP_STARTUP_TIMEOUT_SECONDS` | 900 | Max seconds to wait for the subprocess to become healthy. Cold xl-turbo + vLLM cold-init can take 5–8 min on the very first load after a container start (page cache and torch JIT cache are empty). Once warm, subsequent loads are <30 s. On timeout, the last 2 KB of the merged log is included in the `SubprocessStartError` and surfaces in the admin job error. |
| `ACESTEP_SHUTDOWN_GRACE_SECONDS` | 15 | SIGTERM grace period before SIGKILL |
| `ACESTEP_SHUTDOWN_KILL_SECONDS` | 5 | SIGKILL grace period |
| `ACESTEP_HEALTH_POLL_SECONDS` | 2.0 | Health-check interval during startup probe |
| `HF_TOKEN` | None | Hugging Face token for downloading model weights |
| `LOG_LEVEL` | `INFO` | Standard Python logging level |

### ACE-Step subprocess env vars (passed by the worker)

These are set on the subprocess by `subprocess_runner.py:build_env()` when it spawns ACE-Step. Most are computed from the worker settings above; you don't set them directly.

| Var | Default / Source | Purpose |
|-----|---|---|
| `ACESTEP_API_HOST` | `127.0.0.1` (hardcoded) | Bind address (subprocess only listens on loopback inside the container) |
| `ACESTEP_API_PORT` | from `ACESTEP_INNER_PORT` (default 8101) | Port the subprocess listens on |
| `ACESTEP_DEVICE` | `cuda` | GPU/CPU device (override to `cpu` for non-GPU testing) |
| `ACESTEP_CONFIG_PATH` | per-mode (e.g. `acestep-v15-sft`) | DiT model variant — set dynamically per `load_model` call from `MODEL_CONFIG_PATHS` |
| `ACESTEP_INIT_LLM` | `1` | Load the LM on startup |
| `ACESTEP_LM_MODEL_PATH` | `acestep-5Hz-lm-4B` | LM model name |
| `ACESTEP_LM_BACKEND` | `vllm` | LM inference backend |
| `ACESTEP_COMPILE_MODEL` | `0` | `torch.compile` the DiT model — slower startup, faster inference per generation |
| `MAX_CUDA_VRAM` | from `VRAM_BUDGET_GB` (default `24`) | Total VRAM budget in GB. ACE-Step **trusts this value as ground truth** — it does not cross-check against the physical GPU. On startup the subprocess logs `⚠️ DEBUG MODE: Simulating GPU memory as N GB (set via MAX_CUDA_VRAM)`. Setting this higher than the physical GPU lets ACE-Step's VAE stay on GPU when it should fall back, which will OOM during decode. Always set `VRAM_BUDGET_GB` ≤ physical VRAM. |
| `PYTORCH_CUDA_ALLOC_CONF` | `expandable_segments:True` (hardcoded) | PyTorch CUDA allocator config |

## Local Submodule Patch — VRAM Pre-flight

The `vendor/acestep` submodule has a **local patch** that must be reapplied after any `git submodule update`.

**File:** `vendor/acestep/acestep/core/generation/handler/generate_music.py` (around line 325)

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

## Deferred features (blocked upstream)

Things we'd like to expose but can't until ACE-Step changes — written down so we don't repeatedly investigate the same dead ends.

### `use_cot_metas` toggle

**What it would do:** Let the user disable the LM's automatic inference of BPM, key signature, and time signature from caption + lyrics, forcing the engine to respect explicit values instead.

**Why it's blocked:** The flag exists internally in the ACE-Step engine ([`acestep/api/job_generation_setup.py`](../vendor/acestep/acestep/api/job_generation_setup.py) sets it from `sample_mode`) and in the unrelated [`openrouter_models.py`](../vendor/acestep/acestep/openrouter_models.py) compatibility schema, but **the canonical `/release_task` HTTP request schema does not accept it as user input**:

- [`release_task_models.py`](../vendor/acestep/acestep/api/http/release_task_models.py) declares only `use_cot_caption` and `use_cot_language` as boolean inputs
- [`release_task_param_parser.py`](../vendor/acestep/acestep/api/http/release_task_param_parser.py) parameter alias allowlist does not include `use_cot_metas` under any name

Sending the field in the wire payload would be silently dropped. A UI toggle would appear to work but have **zero effect** on generation.

**What needs to change upstream:** ACE-Step needs to add `use_cot_metas` to the `/release_task` request model and the param parser allowlist.

**Investigation date:** 2026-04-09. Re-check after a vendored submodule bump.

**When unblocked:** ~10 lines of plumbing — add field to [`AceStepConfig`](../src/acestep_engine/models.py), [`GenerationParams`](../src/songmaker_cli/api_models/songs.py), [`AceStepProfile`](../src/songmaker_cli/acestep_capabilities.py), and the wire payload in [`acestep_engine/client.py`](../src/acestep_engine/client.py); add a tooltip in [`acestep-params.ts`](../frontend/src/lib/constants/acestep-params.ts) and a toggle in [`ParamControls.svelte`](../frontend/src/lib/components/ParamControls.svelte).

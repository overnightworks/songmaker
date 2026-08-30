# ACE-Step Integration

Upstream: [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5). The vendored submodule is pinned to `924604f` on the fork branch `songmaker/vendor-2026-08-24`. That branch is based on upstream `main` at `14c0211` and folds in, as clean merges (no squashes), the focused patches tracked upstream as [#1091](https://github.com/ace-step/ACE-Step-1.5/pull/1091) (VRAM preflight opt-out), [#1092](https://github.com/ace-step/ACE-Step-1.5/pull/1092) (DiT param exposure), [#1300](https://github.com/ace-step/ACE-Step-1.5/pull/1300) (failure-cache carries `error`), and [#1301](https://github.com/ace-step/ACE-Step-1.5/pull/1301) (duration-aware LM/DiT VRAM reserve). It also folds in `fix/batch-reduction-surfaced` on `FlexOr2/ACE-Step-1.5` (issue #211: `requested_batch_size`/`delivered_batch_size` in the job result), not yet submitted upstream. `songmaker/vendor-2026-08-24` supersedes the prior `songmaker/vendor-2026-08-20` line and the two loose fix branches it grew (`fix/failure-cache-carries-error`, `fix/duration-aware-lm-reserve`) — those branches still exist for their upstream PRs but are no longer tracked independently; sync by fast-forwarding this one line.

## How Songmaker Uses ACE-Step

ACE-Step runs in dedicated `acestep-worker-N` peer containers, one per GPU. Each
worker hosts a FastAPI wrapper (`src/acestep_worker/wrapper.py`) that manages
an LRU cache of loaded models and exposes:

| Method | Path | Purpose |
|---|---|---|
| POST | `/load_model` | Load a model variant into VRAM (idempotent) |
| POST | `/evict_model` | Evict from VRAM |
| POST | `/pin_model` | Mark a loaded model as exempt from LRU eviction |
| POST | `/unpin_model` | Remove a model from the pinned set |
| POST | `/restart` | Ask the worker process to terminate so Docker restarts it |
| POST | `/generate` | Submit generation, returns `{task_id}` |
| POST | `/tasks/train_lora` | Submit a LoRA training task, returns `{task_id}` |
| POST | `/download_model` | Download a model variant, returns `{task_id}` |
| GET | `/tasks/{id}` | Current task snapshot |
| GET | `/tasks/{id}/stream` | SSE: `progress`/`done`/`error` events |
| GET | `/loaded_models` | Current state for heartbeat |
| GET | `/health` | Liveness |

Workers self-register with the web container at startup
(`POST /api/internal/workers/register`) and heartbeat ephemeral state to
Redis with a 15s TTL. The `acestep_engine.client.AceStepClient` lives inside
the worker container and talks to the upstream ACE-Step subprocess on
`127.0.0.1:8101` (default base port; each loaded model mode gets its own
port — see `ACESTEP_INNER_PORT` below).

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
      → auto-enqueue a score job for it (own budget, not the user's
        rate limit — see below)

scoring worker (songmaker_cli.scoring_worker.ScoringWorkerSettings)
  → on score job:
    → load faster-whisper + AudioBox on demand
    → BPM, silence, spectral, text accuracy, aesthetics
```

**Auto-scoring (issue #222).** Every successfully persisted generation gets a
score job automatically — `jobs.generation._auto_score_generation`, called
from the generation job's own success path. This job is created with
`user_id=None` so it never counts against the manual re-score button's
per-user rate limit (`count_user_jobs_in_window` always filters on a
specific user id). If the scoring worker is down when the check runs, the
job is marked FAILED cleanly instead of queuing indefinitely — the
generation still has no score row, so `lifecycle.score_backfill_loop`
(throttled, `SCORE_BACKFILL_BATCH_SIZE` generations every
`SCORE_BACKFILL_INTERVAL_SECONDS`) picks it up later, the same path that
also catches up generations that predate auto-scoring. A generation the
backfill loop cannot get scored is retried up to `SCORE_BACKFILL_MAX_ATTEMPTS`
times (tracked per generation in Redis, TTL `SCORE_BACKFILL_ATTEMPT_TTL_SECONDS`)
before it is skipped, so one chronically-broken take cannot starve the rest
of the backlog out of every batch. Auto-score `Job` rows are system-owned
(`user_id=None`) — intentionally invisible and not cancelable through the
regular per-user job endpoints.

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
- `acestep-5Hz-lm-1.7B` — ACE-Step's own `GPU_TIER_CONFIGS["tier6b"]` (`vendor/acestep/acestep/gpu_config.py`, 20-24GB cards, e.g. RTX 3090/4090) names this the `recommended_lm_model` for that VRAM class; a reasonable choice for a tighter card via `ACESTEP_LM_MODEL_PATH`
- `acestep-5Hz-lm-4B` — this deployment's default (`WorkerSettings.acestep_lm_model_path`), by operator decision (issue #202, 2026-08-24): 123 historical xl-turbo takes over 120s ran on this card with 4B and never OOMed, and switching the LM would silently change the sound of existing productions. ACE-Step's own tier6b table only recommends 4B once VRAM is `"unlimited"` (≥24GB free for the LM allocator on top of the DiT) — see the VRAM Pre-flight Note below for how this deployment reconciles that gap

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

**Who gets the GPU:** only `songmaker-acestep-worker-N` (`runtime: nvidia`, `NVIDIA_VISIBLE_DEVICES` pinned to its `GPU_ID`). `songmaker-scoring-worker` is given no GPU device and defaults to `SCORING_DEVICE=cpu`, so it carries CPU torch and never touches VRAM. Generation VRAM therefore has exactly one owner and needs no cross-container arbitration. Setting `SCORING_DEVICE=cuda` would break that assumption: the scoring worker would additionally need GPU access in `docker-compose.yml` and a release/verify protocol against the acestep-worker, neither of which exists today (issues #161, #182).

**The inner ACE-Step venv is baked into `acestep-base` at `/opt/acestep/.venv`.** Pre-Phase-8, it lived in a host bind mount that uv re-resynced from scratch on every fresh container (5–15 minute model-load gate). Now it's in the image. The bind mount on `acestep-worker` only carries `./vendor/acestep/checkpoints` → `/opt/acestep/checkpoints` (the multi-GB model weights). The upstream source tree, the `.venv`, and everything else under `vendor/acestep/` is COPYed into the image at build time.

The old `ARQ_JOB_TIMEOUT=1800` workaround in `.env` is no longer needed. The Python settings defaults are `ARQ_JOB_TIMEOUT=1000` and `ACESTEP_STARTUP_TIMEOUT_SECONDS=900`, matching `.env.docker.example`. `docker-compose.yml` currently supplies shorter 300-second fallbacks when those env vars are unset, so set the longer values in `.env` for Docker deployments that cold-load xl-turbo or vLLM on fresh containers.

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
| `songmaker:acestep:worker:{worker_id}` | `acestep-worker` heartbeat loop (every 5 s) | `admin_api` `/admin/workers`, `scheduler.pick_worker`, `/health`, `/metrics` | 15 s | Ephemeral worker state — JSON object with `loaded`, `target_loading`, `vram_used_gb`, `vram_total_gb`, `vram_measured`, `available_modes`, `queue_depth`, `last_heartbeat_at` |
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

The container is already running when the SIGTERM lands, so the Docker daemon's `restart: unless-stopped` policy restarts *that same container* automatically — this narrow in-process case needs neither docker compose nor a reboot. See [Restart-policy limits and boot autostart](#restart-policy-limits-and-boot-autostart) below for what `unless-stopped` does **not** cover. The new process goes through the normal startup sequence above (FastAPI bind → `/health` 503 → register → `/health` 200). Expected total downtime: ~10–15 s.

**In-flight generations fail.** Restarting kills the worker process, including any subprocess holding a generate task. Affected jobs surface as `error_type=worker_unreachable` in the user's job list. Restart only when the operator is willing to lose the in-flight work.

To verify the restart cycle from the admin UI: the Worker Pool card flips `online → offline → loading → online` over the cycle. The transitions are visible because the heartbeat TTL (15 s) outlasts the brief downtime.

### Restart-policy limits and boot autostart

`restart: unless-stopped` is a per-container Docker Engine policy, not a docker-compose feature: the daemon consults it whenever a container's own process exits, and again for every container whose last recorded state was `running` when the daemon itself restarts. It has one hard limit — **it only ever applies to a container that has been started at least once.** A container docker compose merely *created* but never started (e.g. `docker compose up` failing partway through, such as the NVIDIA driver mismatch in #252) sits in state `Created` with `RestartCount: 0`. Docker ignores `Created` containers on every daemon start and every host reboot, indefinitely — there is no timeout and no self-heal. The only way out is an explicit `docker start <container>` or `docker compose up -d`.

**`docker compose ps` hides this.** Without `-a` it omits containers in `Created`, so the stack can look fully up when a container has in fact never run once. Diagnose a suspected stuck container with:

```bash
docker compose ps -a
```

**Boot autostart.** Since neither dockerd nor compose retries a `Created` container on its own, the host runs a systemd unit (`scripts/songmaker.service`) that runs `docker compose up -d` (no `--build`) once per boot, after `docker.service` is up. `docker compose up -d` starts every container regardless of the state it was left in — `running`, `exited`, or `Created` alike — which is exactly what the restart policy cannot do. Install it once with:

```bash
./scripts/install-autostart.sh
```

The script copies the unit into `/etc/systemd/system/` (deriving `WorkingDirectory` from wherever the script itself lives, so running it from a worktree doesn't silently point the unit at the main checkout, and `User` from whoever is running the installer — `$SUDO_USER` under `sudo`, otherwise the current user, refusing outright if that resolves to `root` — so the unit runs as the stack owner, not as whoever happened to invoke it) and runs `systemctl enable` — it does **not** touch the currently running stack. `enable` only takes effect on the *next* boot; the script's own output names the explicit `systemctl start` command for applying it immediately, and warns that doing so recreates containers (killing an in-flight generation) if `.env` or code changed since the containers last started, so that should happen in a maintenance window, not as a side effect of installing the unit. Rerunning the script is a no-op only if the unit file content is unchanged; if it changed, `daemon-reload` picks up the new file immediately, but `RemainAfterExit=yes` means an already-active unit only picks up the new `ExecStart` on the next boot or an explicit `systemctl restart songmaker.service`.

**Verifying the fix.** To reproduce and confirm the exact failure this closes, without disturbing the live stack for longer than a deliberate maintenance window:

```bash
docker compose stop songmaker-acestep-worker-0
docker compose rm -f songmaker-acestep-worker-0
docker compose create songmaker-acestep-worker-0   # creates but does not start it
docker compose ps -a                                # confirm: State = created
sudo reboot
# after the host comes back:
docker compose ps -a                                # confirm: State = running, no manual `docker start` needed
```

### pin_model semantics

The cache is normally LRU: when a new `load_model` would exceed the VRAM budget, the least-recently-used loaded model is evicted to make room. Capacity is planned against `max(measured VRAM used, sum of declared sizes of what's currently loaded)`, not the declared-size table alone: ACE-Step loads lazily, so a model that hasn't served its first generation yet can measure almost nothing on NVML even though it is genuinely resident, and without that floor the cache would read it as free and overbook the GPU. The full eviction plan — which models, in what order — is computed and checked against the budget before anything is actually unloaded; a load the plan can't satisfy is rejected outright, with nothing destroyed. **Pinning** marks a loaded model as exempt from eviction. Use it when a single-GPU multi-user deployment has a "must always be loaded" preference (e.g. the operator wants `sft` to stay resident regardless of how many other modes get loaded).

How pinning interacts with the cache:

- `POST /api/admin/workers/{id}/pin_model` requires the model to already be loaded (returns 409 otherwise).
- `_evict_to_fit` builds the eviction plan in LRU order, skipping pinned **and** in-use models, and only executes it once the plan proves sufficient.
- If **all** loaded models are pinned (or otherwise ineligible) and the plan still doesn't fit, the cache raises `CapacityError` with a clear message naming the loaded, in-use, and pinned sets — without evicting anything. The admin must explicitly unpin one before the next load can succeed.
- Explicit `evict_model` (the admin "Evict X" button) unpins implicitly — the operator asked for it. `_evict_to_fit` (LRU) does not unpin.
- Worker shutdown (`evict_all`) drains everything regardless of pin state.

Pin/unpin from the admin UI: each loaded-mode row in the Worker Pool card has a **Pin** / **Unpin** button next to its **Evict** button. The button reflects the current state from the heartbeat (`pinned: list[str]`).

### Load-while-generating refcount

Generations and model loads share the same cache. Without coordination, an admin who loads a different mode mid-generation would evict the in-use model and crash the running generation with a stale subprocess handle. The worker uses a **per-mode refcount**:

- The worker's `/generate` endpoint calls `cache.acquire_for_use(mode)` before spawning the runner. If the mode isn't loaded the endpoint returns 409.
- The runner spawn is wrapped in a `try/finally` that calls `cache.release(mode)` on completion (success **or** exception **or** cancellation).
- `_evict_to_fit` skips both pinned and in-use models (refcount > 0). If no eligible victim exists, the load fails with `CapacityError`.
- Explicit `evict_model` refuses to evict a mode with refcount > 0 (returns 409 with the in-flight count).

The user-visible failure mode: if an admin tries to load a model that would require evicting an in-use one, the load job ends `failed` with a message naming the loaded, in-use, and pinned sets in the job-tracking UI. The running generation continues unharmed.

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

**"Docker cannot select the NVIDIA device driver"** — first confirm the host and explicit NVIDIA runtime independently:

```bash
nvidia-smi
docker info | grep -E 'Runtimes|nvidia'
docker run --rm --runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=all \
  nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

On this Docker 29 host, the legacy `--gpus all` / Compose `deploy.resources.reservations.devices` path fails even though the explicit NVIDIA runtime and CDI both work. The worker therefore uses `runtime: nvidia` plus `NVIDIA_VISIBLE_DEVICES`, and does not declare the failing deploy reservation. If the explicit-runtime test fails, stop: fix the NVIDIA Container Toolkit/daemon configuration before retrying Compose. If it succeeds, start exactly one worker and wait for registration before attempting generation.

**"Worker won't register"** — `/health` returns 503. Check container logs for `"Registration attempt N failed: ..."`. Verify the control plane URL is reachable from inside the worker container with `docker compose exec songmaker-acestep-worker-0 curl -v http://songmaker-web:8080/health`. Verify `SONGMAKER_INTERNAL_TOKEN` matches between worker and web. The retry loop never gives up — fix the root cause and the next backoff tick will succeed.

**"Download stalls"** — check the download flag: `docker compose exec redis redis-cli GET 'songmaker:acestep:download:{mode}'`. Cross-reference the value (a job_id) with the job's status in the admin UI. If the job is gone but the flag remains, it's stale — `redis-cli DEL` it and retry. The 30-minute TTL is the automatic safety net.

**"Load fails with CapacityError"** — two distinct messages, both actionable. If the worker has models loaded, the message names the loaded/pinned/in-use sets and how much VRAM is already in use (measured or, without a reader, estimated from declared sizes); if the in-use set is non-empty, wait for those generations to finish; if it's all pinned, unpin one explicitly. If the worker has **nothing** loaded and still can't fit the request, the message says so explicitly — VRAM outside this cache's tracking (a stray process, an unreleased subprocess) is holding the GPU; check `nvidia-smi` on the worker host before retrying. The Worker Pool card's per-mode buttons make the first case directly actionable; the second needs a host-level check.

**"Stale-job reaper killed my long generation"** — the reaper looks at `Job.last_heartbeat_at`. The arq job calls `_touch_heartbeat` on every SSE progress event from the worker (which fires every ~2 s for downloads, every ~1–5 s for generation steps). If a long task is being killed unexpectedly, check whether the on_progress callback is wired into the SSE consumer — the contract is that *every* yielded event refreshes the heartbeat, not just the milestone events.

For the cross-cutting flow (web → music-worker → acestep-worker), see [architecture.md](architecture.md). For the trust boundaries and the internal token, see [security.md](security.md).

## Generation Parameters

The user-facing ACE-Step knobs are stored in `Version.generation_params`, can be set per-model in admin defaults, and are merged into `AceStepConfig`.

Priority: CLI overrides, when supplied > song params > preset params > admin defaults > model defaults. Top-level song/version fields (`bpm`, `audio_duration`, `key_scale`, `vocal_language`) are applied after that merge.

| Parameter | Range | Default (turbo) | Default (SFT) | Effect |
|-----------|-------|-----------------|---------------|--------|
| `inference_steps` | 1-200 | 8 | 50 | More = slower, potentially higher quality |
| `guidance_scale` | 0-50 | 0.0 | 0.0 | CFG strength (turbo ignores this) |
| `shift` | 0-100 | 3.0 | 3.0 | 1.0 = natural/emotional, 3.0 = accurate lyrics |
| `thinking` | bool | true | true | Let the LM plan musical structure |
| `lm_temperature` | 0-5 | 0.85 | 0.85 | Higher = more creative (try 1.1-1.2) |
| `lm_top_k` | 0-1000 | 0 | 0 | LM sampling top-k; 0 disables top-k filtering |
| `lm_top_p` | 0-1 | 0.9 | 0.9 | LM sampling nucleus |
| `lm_cfg_scale` | 0-50 | 2.0 | 2.0 | LM classifier-free guidance |
| `lm_negative_prompt` | string | empty | empty | What to avoid |
| `infer_method` | ode/sde | ode | ode | sde = more textured/alive |
| `batch_size` | 1-8 | 1 | 1 | Parallel generations per request |
| `reference_audio_path` | string | empty | empty | Uploaded reference-audio path |
| `repaint_mode` | conservative/balanced/aggressive | none | none | Server-side repaint preservation mode |
| `repaint_strength` | 0-1 | none | none | Intensity for balanced repaint mode |
| `lm_repetition_penalty` | 0.5-5 | 1.0 | 1.0 | Penalize LM token repetition |
| `use_cot_caption` | bool | true | true | LM chain-of-thought caption rewriting |
| `use_cot_language` | bool | true | true | LM chain-of-thought language detection |
| `use_adg` | bool | false | false | Adaptive Projected Guidance (no-op on turbo; honored on sft/base when `guidance_scale > 1.0`) |
| `cfg_interval_start` | 0-1 | 0.0 | 0.0 | CFG application start fraction |
| `cfg_interval_end` | 0-1 | 1.0 | 1.0 | CFG application end fraction |
| `sampler_mode` | euler/heun | euler | euler | Diffusion sampler |
| `velocity_norm_threshold` | >= 0 | 0.0 | 0.0 | DiT velocity normalization threshold; 0 disables |
| `velocity_ema_factor` | >= 0 | 0.0 | 0.0 | Exponential smoothing for DiT velocity; 0 disables |
| `latent_shift` | float | 0.0 | 0.0 | Shift latent-space center |
| `latent_rescale` | >= 0.1 | 1.0 | 1.0 | Rescale latent magnitude |
| `audio_cover_strength` | 0-1 | 1.0 | 1.0 | Strength for cover/reference guidance |
| `user_lora_id` | string | none | none | User-trained LoRA adapter ID |

Top-level song/version fields:

| Field | Range | Default | Effect |
|-------|-------|---------|--------|
| `audio_duration` | 0-600 | 180 | Output length in seconds; 0 lets ACE-Step decide |
| `bpm` | 0-999 | 0 | Target BPM; 0 lets ACE-Step decide |
| `key_scale` | string | empty | Target key |
| `vocal_language` | string | empty | Vocal language hint |

## Modes

All modes use the same upstream ACE-Step task endpoint with different `task_type` + audio inputs. If the requested model isn't loaded on the chosen worker, the scheduler issues `POST /load_model` before `POST /generate`.

| Mode | task_type | Trigger | What It Does |
|------|-----------|---------|--------------|
| Text2Music | `text2music` | Generate button | Generate from scratch (default) |
| Repaint | `repaint` | Repaint button on generation | Edit a time section — fix wrong lyrics, redo a chorus |
| Cover | `cover` | Cover button on generation | Re-interpret with different style/lyrics, keep melody |
| Reference | `text2music` + `reference_audio_path` | Upload in generation settings | Guide timbre/style from an external audio track |

**Repaint** sends `src_audio` (the original WAV), `repainting_start` and `repainting_end` (0.0-1.0 fractions). `thinking` is auto-disabled. The result is a new generation — non-destructive. ACE-Step 1.5 adds server-side crossfade controls:
- `repaint_mode`: `conservative` / `balanced` / `aggressive` — how much source audio is preserved
- `repaint_strength`: 0-1, intensity for balanced mode
- `repaint_latent_crossfade_frames`: latent-level boundary blend width
- `repaint_wav_crossfade_sec`: waveform-level splice crossfade

When `repaint_mode` or `repaint_wav_crossfade_sec` is set, the server handles crossfading and the client-side splice (`_splice_repaint_raw`) is skipped.

**Cover** sends `src_audio` and `audio_cover_strength` (0.0 = free reinterpretation, 1.0 = strict structure). `thinking` is auto-disabled. ACE-Step 1.5 adds `cover_noise_strength` (0-1) for noise blending control.

**Reference audio** uploads via `POST /api/audio/upload` (max 50MB, .mp3/.wav/.flac/.ogg). The path is stored in version `generation_params.reference_audio_path` and resolved to an absolute path before sending to ACE-Step. Path traversal is blocked at both API validation and job execution levels.

## CoT Response Data

The server returns `cot_caption` and `cot_lyrics` in generation results — the LM's chain-of-thought rewritten caption and lyrics. These are stored in `generation_params` and displayed in the frontend generation detail. Useful for understanding how the LM interpreted your prompt. Disable with `use_cot_caption: false` / `use_cot_language: false`.

**Not yet integrated**: Lego, Extract, Complete (require Base model support in Songmaker). Infinite duration remains exploratory.

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
| `GPU_ID` | None | CUDA device index passed deterministically to the inner process as `CUDA_VISIBLE_DEVICES` |
| `NVIDIA_VISIBLE_DEVICES` | Compose: `0` | Host GPU exposed to the worker by the explicit NVIDIA container runtime |
| `ACESTEP_CHECKPOINT_DIR` | `/opt/acestep` | Where ACE-Step model weights live |
| `AUDIO_OUTPUT_DIR` | `/app/data/audio/worker_output` | Where the subprocess writes generated WAVs |
| `ACESTEP_LOG_DIR` | `/opt/acestep/logs` | Where the subprocess's merged stdout+stderr is captured. Each load attempt appends a `=== {mode} attempt at {iso} ===` header so retry history isn't clobbered. Also forwarded line-by-line to the worker's own logger as `[ace-step {mode}] ...` (visible in `docker compose logs songmaker-acestep-worker-0`). |
| `ACESTEP_INNER_PORT` | 8101 | Base port for ACE-Step subprocesses (inside the container). Each loaded model mode gets `base_port + offset`, offset taken from the mode's position in `MODEL_CONFIG_PATHS` (`subprocess_runner.MODEL_INNER_PORT_OFFSETS`) — this keeps two simultaneously loaded modes from colliding on one port, which used to make the second mode's health check see the first mode's still-running server and falsely report ready (issue #205) |
| `ACESTEP_STARTUP_TIMEOUT_SECONDS` | 900 | Max seconds to wait for the subprocess to become healthy. Cold xl-turbo + vLLM cold-init can take 5–8 min on the very first load after a container start (page cache and torch JIT cache are empty). Once warm, subsequent loads are <30 s. On timeout, the last 2 KB of the merged log is included in the `SubprocessStartError` and surfaces in the admin job error. |
| `ACESTEP_SHUTDOWN_GRACE_SECONDS` | 15 | SIGTERM grace period before SIGKILL |
| `ACESTEP_SHUTDOWN_KILL_SECONDS` | 5 | SIGKILL grace period |
| `ACESTEP_HEALTH_POLL_SECONDS` | 2.0 | Health-check interval during startup probe |
| `HF_TOKEN` | None | Hugging Face token for downloading model weights |
| `LOG_LEVEL` | `INFO` | Standard Python logging level |

### ACE-Step subprocess env vars (passed by the worker)

Most of these are set on the subprocess by `subprocess_runner.py:build_env()` when it spawns ACE-Step, computed from the worker settings above; you don't set them directly. The three tuning vars below (`ACESTEP_LM_DIT_RESERVE_DURATION_S`, `ACESTEP_LM_DIT_RESERVE_BATCH`, `ACESTEP_SKIP_VRAM_PREFLIGHT`) are not built there — `build_env()` copies the worker container's environment, so they ride along from `docker-compose.yml` and are read by ACE-Step itself.

| Var | Default / Source | Purpose |
|-----|---|---|
| `ACESTEP_API_HOST` | `127.0.0.1` (hardcoded) | Bind address (subprocess only listens on loopback inside the container) |
| `ACESTEP_API_PORT` | `ACESTEP_INNER_PORT` + this mode's offset (default base 8101) | Port this mode's subprocess listens on — unique per loaded mode, see `ACESTEP_INNER_PORT` above |
| `ACESTEP_DEVICE` | `cuda` | GPU/CPU device (override to `cpu` for non-GPU testing) |
| `ACESTEP_CONFIG_PATH` | per-mode (e.g. `acestep-v15-sft`) | DiT model variant — set dynamically per `load_model` call from `MODEL_CONFIG_PATHS` |
| `ACESTEP_INIT_LLM` | `1` | Load the LM on startup |
| `ACESTEP_LM_MODEL_PATH` | `acestep-5Hz-lm-4B` | LM model name. Default is this deployment's proven setup (operator decision, issue #202); lower to `acestep-5Hz-lm-1.7B` on a tighter card — ACE-Step's own `tier6b` `recommended_lm_model` (see Model Variants above) |
| `ACESTEP_LM_DIT_RESERVE_DURATION_S` | unset → GPU tier's `max_duration_with_lm` (480 on a 24GB card) | Longest track the LM keeps DiT inference room for. Lower it for a larger LM KV cache, raise it for longer tracks — see the VRAM Pre-flight Note |
| `ACESTEP_LM_DIT_RESERVE_BATCH` | unset → `1` | Samples per request the LM keeps DiT inference room for — see "The batch cliff" |
| `ACESTEP_SKIP_VRAM_PREFLIGHT` | `0` | Emergency bypass of the DiT VRAM pre-flight; a refused generation then OOMs instead — see the VRAM Pre-flight Note |
| `ACESTEP_LM_BACKEND` | `vllm` | LM inference backend |
| `ACESTEP_COMPILE_MODEL` | `0` | `torch.compile` the DiT model — slower startup, faster inference per generation |
| `MAX_CUDA_VRAM` | from `VRAM_BUDGET_GB` (default `24`) | Total VRAM budget in GB. ACE-Step **trusts this value as ground truth** — it does not cross-check against the physical GPU. On startup the subprocess logs `⚠️ DEBUG MODE: Simulating GPU memory as N GB (set via MAX_CUDA_VRAM)`. Setting this higher than the physical GPU lets ACE-Step's VAE stay on GPU when it should fall back, which will OOM during decode. Always set `VRAM_BUDGET_GB` ≤ physical VRAM. |
| `PYTORCH_CUDA_ALLOC_CONF` | `expandable_segments:True` (hardcoded) | PyTorch CUDA allocator config |
| `CUDA_VISIBLE_DEVICES` | from `GPU_ID` when set | Pins the inner ACE-Step process to the worker's configured device index |

## Failure Cause Contract

A failed generation carries ACE-Step's own words all the way to the take list. When a job fails, the server's `mark_failed` records the **full traceback** on the job record, and both payload builders put it in the result entry's `error` field: the job store's (`query_result_service.py`) and — since our fork's `songmaker/vendor-2026-08-24` line (upstream [#1300](https://github.com/ace-step/ACE-Step-1.5/pull/1300)) — the local cache's (`jobs/local_cache_updates.py`). The cache branch is the one that matters in practice: `/query_result` serves the cache before the store, so before that fix a deployed worker reported `status: 2` with no cause at all. `status_message` only ever appears on *succeeded* analysis payloads; the client reads it as a secondary source but a failure carries `error`.

This contract covers jobs that reach `mark_failed`. A job that dies before that point (before `run_one_job_runtime`) writes no terminal cache entry at all — a client sees a bare timeout instead of a cause. That gap is tracked upstream, not yet patched: [FlexOr2/ACE-Step-1.5#1](https://github.com/FlexOr2/ACE-Step-1.5/issues/1).

`AceStepClient._poll_result` decodes the entry through `ResultItem`, logs the full text at ERROR, and raises `GenerationFailedError` with the traceback's **last line** (the exception and its message, e.g. `RuntimeError: Music generation failed: Insufficient free VRAM: need ~2.0 GB, only 1.3 GB available`), capped at `_MAX_CAUSE_CHARS`. It never raises an empty message: without any detail it uses the named reason `generation failed (no detail from ACE-Step)`. The worker's generate runner puts an `AceStepError` message into the task error verbatim (other exception types keep their `TypeName: message` form); the scheduler relays a worker error event as `WorkerGenerationFailed`, the one exception type whose message is user-facing — an empty error field is a protocol violation and stays a `WorkerProtocolError`. `_sanitize_error` passes `WorkerGenerationFailed` through, so `jobs.error` holds the real cause while every other failure keeps its generic message. The frontend job store keeps the cause per song in `generationFailures`, and the take list shows it (full text in the row's `title`) until the next generation starts or the user dismisses it. This survives a reload or a later visit too: the job row now carries the generating song's `song_id` (see `Job.song_id` in `db/models.py`, set at creation via `create_job`/`create_job_with_rate_limit`), and `GET /api/songs/{song_id}/last-failed-generation` returns that song's *last* generate/repaint/cover job (by `started_at`) only if it's still FAILED — any newer job of any outcome, or a newer non-archived take, supersedes it. `selectSong`/`initNavigation` hydrate `generationFailures` from it whenever a song is opened, but a live SSE update always wins: once a song has had a live resolution this session (a dismiss or a fresh generate) hydration skips it for the rest of the session — see `hydrateGenerationFailure` in `stores/jobs.ts`. Showing raw server text to the operator is deliberate: it is what makes a failure diagnosable without grepping worker logs.

## VRAM Pre-flight Note

The vendored fork keeps `_vram_preflight_check()` enabled by default. Before checking, CUDA generations run `gc.collect()` and `torch.cuda.empty_cache()` so cached allocations do not cause a false rejection. This behavior comes from upstream PR [#1091](https://github.com/ace-step/ACE-Step-1.5/pull/1091).

**Current file:** `vendor/acestep/acestep/core/generation/handler/generate_music.py` (around the `_vram_preflight_check()` call in `GenerateMusicMixin.generate_music()`)

**Emergency opt-out:** `ACESTEP_SKIP_VRAM_PREFLIGHT=1` skips only the safety check and logs a warning. The flag is CUDA-only and back to emergency semantics: `docker-compose.yml` defaults it to `0` (override via `.env`). With the check bypassed, a generation that would have been refused runs into an OOM instead. Because the worker copies its environment when starting the ACE-Step subprocess, the flag reaches the subprocess the same way any other passthrough var does.

Targeted fork tests lock both branches of the policy: the pre-flight runs when the flag is unset and is bypassed only for an explicit truthy opt-out.

### How the LM leaves room for the DiT (issue #202)

The pre-flight and the LM allocator used to measure the same GPU with different rulers, and that is what rejected long xl-turbo takes on this card. ACE-Step's LM allocator (`gpu_config.py:get_lm_gpu_memory_ratio`) kept a *constant* `dit_reserve_gb = 1.5` free, while the pre-flight demands `DIT_INFERENCE_VRAM_PER_BATCH[dit_key] * batch * duration/60 + 0.5`. The two agree at 120s and diverge after that, so with `acestep-5Hz-lm-4B` resident the DiT was left 1.30 GB where a 165s take needs 1.88 GB.

The fork now sizes that reserve with the pre-flight's own formula — folded into `songmaker/vendor-2026-08-24` on `FlexOr2/ACE-Step-1.5` (originally `fix/duration-aware-lm-reserve`), upstream PR [#1301](https://github.com/ace-step/ACE-Step-1.5/pull/1301). Three things changed:

- **The reserve is duration- and batch-aware.** `get_dit_inference_reserve_gb()` mirrors the pre-flight and adds `DIT_RESERVE_HEADROOM_GB = 0.5`. The LM initializes before any request, so the reserve is sized for the longest track and the batch size the deployment intends to render with the LM resident — the GPU tier's `max_duration_with_lm` (480s here) and one sample, overridable with `ACESTEP_LM_DIT_RESERVE_DURATION_S` and `ACESTEP_LM_DIT_RESERVE_BATCH`. The resident DiT's checkpoint path now reaches the LM init, so an XL DiT reserves XL activations instead of the default profile.
- **The reserve comes out of the KV cache, never out of the LM weights — and never below what the LM can legally need.** The floor is what nano-vllm's scheduler actually requires: blocks for a full `max_model_len` window, doubled because classifier-free guidance (`lm_cfg_scale > 1`, which songmaker sends on every request) schedules the conditional and the unconditional sequence as a pair. The floor is derived from the checkpoint's own `config.json` (layers × KV heads × head dim × dtype), not from an estimate table — for `acestep-5Hz-lm-4B` that is 2 × 4096 tokens × 144 KB = **1.13 GB**. When the reserve would cut into that floor, the shortfall is logged with the track length that *is* supported; when even the floor does not fit, the LM fails to initialize with that message instead of the DiT hitting an OOM or nano-vllm raising `Insufficient KV cache to schedule sequence` mid-generation. The `min(0.9, …)` ratio clamp logs a warning when it caps, too.
- **Memory the allocator cannot see is subtracted up front.** nano-vllm sizes the KV cache against PyTorch's allocator bookkeeping, which misses the CUDA context and fragmentation the driver reports — 1.42 GB at LM init in the measurement below, and still 1.24 GB when the KV cache was allocated. Without that correction every gigabyte reserved for the DiT was spent twice.

Measured on this RTX 3090 (23.53 GiB usable, xl-turbo + `acestep-5Hz-lm-4B`, 165s track, pre-flight bypassed so the run could complete):

| | before the fix (measured) | after the fix (same inputs) |
|---|---|---|
| LM ratio | 0.915 → clamped to 0.900, silently | 0.836, clamp not reached |
| KV cache | 2.46 GB / 17.9k tokens (≈2 CFG pairs) | 1.13 GB / 8.2k tokens (exactly one CFG pair of 4096-token windows) |
| free for the DiT | 1.28 GB | 2.43 GB |
| longest xl-turbo take that passes, batch 1 | ~96s | ~232s |

The DiT stage itself peaked at 23415 MiB of 24576 MiB against a 22813 MiB plateau while the LM ran — 0.59 GB where the pre-flight demanded 1.88 GB. The pre-flight is therefore still conservative by roughly a factor of three; the point of the fix is that the LM now respects that conservatism instead of contradicting it.

The KV cache is a floor, not a budget that shrinks with track length: one CFG pair of full context windows costs the same 1.13 GB whatever the track is. The LM's own 4096-token window only becomes the binding limit near ACE-Step's 600s ceiling (the 5 Hz LM emits 5 codes per second of audio — 825 codes for the 165s take above — plus the prompt), so on this card the DiT reserve binds first, at ~232s.

Two numbers describe that limit and they are not the same: the LM's startup warning names **~172s**, the pre-flight accepts up to **~232s**. The warning counts the reserve's own `DIT_RESERVE_HEADROOM_GB` slack, the pre-flight does not — the warning is the length that would still have half a gigabyte of margin, the pre-flight is where the estimate runs out. Tracks between the two pass, with less slack than the reserve aims for.

### The batch cliff

The pre-flight's demand scales with the batch size, and so does the reserve — but the reserve is sized once, at LM init, for `ACESTEP_LM_DIT_RESERVE_BATCH` (default 1, this deployment's real usage: songmaker sends `count=1` per request). With the 2.43 GB the LM leaves on this card:

| batch | pre-flight demand at 165s | longest take that passes |
|---|---|---|
| 1 | 1.88 GB | ~232s |
| 2 | 3.25 GB → refused | ~116s |
| 8 | 11.5 GB → refused | refused even at 60s (demand 4.5 GB) |

A refused batch job fails cleanly and its message names the remedy — `Insufficient free VRAM: need ~X GB, only Y GB available. Reduce batch size (currently N) or audio duration (currently Ns).` Raising `ACESTEP_LM_DIT_RESERVE_BATCH` makes the LM hold that room back on a card that *has* it; on this 24 GB card with the 4B LM there is nothing left to hold back (the KV floor already binds), so the real remedies for batch work here are a shorter track or a smaller LM.

`ACESTEP_LM_DIT_RESERVE_DURATION_S` is the other lever: lowering it hands the LM a larger KV cache (better for long lyrics), raising it hands the DiT more room. This deployment leaves both unset and takes the tier default, which on a 24 GB card with the 4B LM lands in the capped case and says so once per subprocess start.

### Batch reduction is surfaced, not refused (issue #211)

The pre-flight above only ever sees the batch size it's handed — and it isn't handed the one the caller asked for. `memory_utils.py:_vram_guard_reduce_batch()` runs first, inside `_prepare_generate_music_runtime()`, and can shrink a requested `batch_size` down to what free VRAM actually supports (e.g. 2 → 1) *before* `_vram_preflight_check()` ever runs on the (already-shrunk) number. Operator decision 2026-08-24: don't turn this into a hard refusal — deliver what VRAM allows, but never silently. The fork now threads both numbers through the same job-result path issue #202 added `error` to:

- `GenerateMusicRequestMixin._prepare_generate_music_runtime()` returns `requested_batch_size` alongside the already-existing `actual_batch_size`.
- `_build_generate_music_success_payload()` puts both on the handler's result dict as `requested_batch_size` / `delivered_batch_size`.
- `inference.py`'s `GenerationResult` carries them through to `build_generation_success_response()` and `jobs/local_cache_updates.py:update_local_cache()` — the same `/query_result` payload `error` rides on.

On the songmaker side, `acestep_engine.models.ResultItem`/`AceStepResult` parse the two fields (mirroring `error`/`status_message`). `StoredGenerationParams.batch_size` persists the *requested* side onto `Generation.generation_params` whenever it isn't the trivial default of 1 (previously dropped silently, even though `ParamControls`/`acestep-param-fields.ts` already expose it as an editable knob). The chain is wired all the way through the worker: `acestep_worker.models.GenerationTaskResult` and `src/songmaker_cli/scheduler.py`'s `GenerationTaskResultDTO` both carry `delivered_batch_size` (kept in lockstep by `tests/test_scheduler.py::test_dto_keys_match_worker_model_fields`, a drift guard), `wrapper.py`'s `default_generate_runner` copies `AceStepResult.delivered_batch_size` onto the task result, and `_persist_generation_row()` writes `StoredGenerationParams.delivered_batch_size` onto the generation — but only when it actually diverges from the requested `batch_size` (the fork always reports a concrete delivered count, matching or not, so the persistence layer is what keeps an unreduced batch from adding noise to every row).

`frontend/src/lib/constants/now-playing.ts:takeBatchReductionLabel()` turns the pair into a `⚠ N of M` badge on the take row (`TakesList.svelte`, pattern from the model badge in #213) whenever both are present and differ. The take recipe panel (`recipe-summary.ts`) shows the same value next to "Batch Size" under Model & Sampling — `delivered_batch_size` isn't an editable `ParamControls` knob, so it gets an explicit registry-adjacent entry rather than falling into the generic "Other" catch-all.

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

**When unblocked:** ~10 lines of plumbing — add field to [`AceStepConfig`](../src/acestep_engine/models.py), [`GenerationParams`](../src/songmaker_cli/api_models/songs.py), [`AceStepProfile`](../src/songmaker_cli/acestep_capabilities.py), and the wire payload in [`acestep_engine/client.py`](../src/acestep_engine/client.py); add a tooltip in [`acestep-params.ts`](../frontend/src/lib/constants/acestep-params.ts) and a field definition in [`acestep-param-fields.ts`](../frontend/src/lib/constants/acestep-param-fields.ts), which [`ParamControls.svelte`](../frontend/src/lib/components/ParamControls.svelte) renders automatically.

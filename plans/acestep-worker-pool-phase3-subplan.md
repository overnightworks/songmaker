# Phase 3 Sub-plan — Scheduler in music-worker (cutover)

> Concrete implementation plan for Phase 3 of [acestep-worker-pool.md](acestep-worker-pool.md). Phase 3 is the **cutover**: the music-worker stops talking to ACE-Step directly and instead routes generation through the scheduler → acestep-worker → SSE pipeline. `acestep_manager.py` is deleted in this PR. Read end-to-end before starting; this captures decisions that aren't in the parent plan.

## State at start of Phase 3

- **Branch:** `feat/acestep-worker-pool` (Phase 1 = `c416194`, Phase 2 = `275518c`, both pushed)
- **What's already in place:**
  - acestep-worker container with `/load_model`, `/evict_model`, `/generate` (returns task_id), `/tasks/{id}/stream` (SSE), `/loaded_models`, `/health`
  - PG `acestep_workers` table + idempotent registration via `/api/internal/workers/register`
  - Redis worker state + queue depth keys, helpers in [src/songmaker_cli/acestep_state.py](../src/songmaker_cli/acestep_state.py)
  - Admin endpoints `/admin/workers`, `/admin/registry`, `/admin/workers/{id}/load_model` (arq job), `/admin/workers/{id}/evict_model` (sync proxy)
  - `load_model_on_worker` arq job in [jobs.py](../src/songmaker_cli/jobs.py) — established the httpx-via-internal-token pattern that the scheduler will reuse
- **What's still legacy and must die in Phase 3:**
  - `src/songmaker_cli/acestep_manager.py` — entire file
  - `music_worker._acestep_manager`, `_publish_acestep_status`, `publish_acestep_heartbeat` cron, `reinitialize_acestep` arq job
  - `/api/admin/acestep/status` and `/api/admin/acestep/reinitialize`
  - `AceStepStatusResponse`, `ReinitializeRequest` (api_models/settings.py)
  - `ACESTEP_STATUS_REDIS_KEY`, `ACESTEP_STATUS_TTL_SECONDS`, `ACESTEP_PORT`, `ACTIVE_MODEL_REDIS_KEY`, `ACTIVE_MODEL_TTL_SECONDS`, `ACESTEP_HEALTH_URL_TEMPLATE` (constants.py)
  - `arq_pool.get_active_model` and the health endpoint's `acestep_status` field
  - The music-worker compose block: GPU `deploy.resources`, `_models/acestep` mount, `ACESTEP_API_HOST`, `ACESTEP_API_PORT`, `HF_TOKEN` env

## Phase 3 goal (recap)

Route generation jobs through the new scheduler. After this PR, the music-worker is a thin orchestrator: it schedules to a worker, waits on SSE, and post-processes the worker-produced WAV. **Generation = worker; post-process = music-worker.**

The music-worker still imports `acestep_engine.models.AceStepConfig` to build the request payload. `acestep_engine` stays as a dependency. Only the **subprocess management** (`acestep_manager.py`) goes away.

## D1. Boundary contract (THE most important section)

Everything in Phase 3 hinges on this. Get it wrong and you'll find out at smoke-test time.

### Data flow

```
arq generate job (music-worker)
  │
  ├─ run_generation_job (now async)
  │     │
  │     ├─ load song/version from PG, build AceStepConfig (existing, unchanged)
  │     ├─ prepare repaint/cover source on shared volume (new tmp location)
  │     │
  │     └─ for each variant 1..N:
  │           │
  │           ├─ scheduler.dispatch_generation(ace_config, model_name, on_progress, on_heartbeat)
  │           │     │
  │           │     ├─ pick_worker (PG identities + Redis state, prefer-loaded then least-busy)
  │           │     ├─ INCR queue_depth atomically (Redis)
  │           │     ├─ try:
  │           │     │     POST /load_model (if mode not loaded)   ─→ acestep-worker
  │           │     │     POST /generate {config: ace_config}      ─→ acestep-worker
  │           │     │       returns {task_id}
  │           │     │     consume_task_stream(worker, task_id):
  │           │     │       GET /tasks/{task_id}/stream            ─→ acestep-worker (SSE)
  │           │     │         while events:
  │           │     │           progress → on_progress(fraction)   (callback updates DB job row)
  │           │     │           done     → return WorkerGenerationResult
  │           │     │           error    → raise WorkerTaskFailed
  │           │     │         on transport drop: reconnect to same task_id (≤5 attempts, expo backoff)
  │           │     └─ finally:
  │           │           DECR queue_depth
  │           │
  │           ├─ post_process_generation(result, ctx, generation_id, db_factory)
  │           │     │   (CPU-bound — wrapped in asyncio.to_thread)
  │           │     ├─ read worker WAV from shared audio volume
  │           │     ├─ splice repaint raw audio (if needed)
  │           │     ├─ master + write final stereo WAV
  │           │     ├─ encode MP3 with ID3 tags
  │           │     ├─ INSERT generation row in PG
  │           │     └─ delete worker temp WAV (in finally)
  │           │
  │           └─ track success/failure → _finalize_generation_job
  │
  └─ on whole-job exception: _update_job(failed)
```

### Worker `WorkerGenerationResult` schema (what `done` SSE event carries)

The worker's `/tasks/{id}/stream` `done` event already contains a `result` dict (see `task_store._Task.to_event` and `default_generate_runner.complete()` calls). Today the result is:

```python
{
    "mode": "sft",
    "audio_path": "/app/data/audio/worker_output/gen-abc123.wav",
    "seed": 42,
    "cot_caption": "",
    "cot_lyrics": "",
}
```

We promote this to a Pydantic model in `acestep_worker/models.py` (already has `TaskSnapshot`, `WorkerTaskEvent`):

```python
# new — in acestep_worker/models.py
class GenerationTaskResult(BaseModel):
    mode: str
    audio_path: str           # absolute path inside the shared volume
    seed: int
    cot_caption: str = ""
    cot_lyrics: str = ""
```

The scheduler validates the SSE `done` event payload via `GenerationTaskResult.model_validate(event.data["result"])`. The TaskSnapshot's `result` field is what gets serialized as `data` of the `done` event — see [task_store.py:46](../src/acestep_worker/task_store.py#L46): `WorkerTaskEvent(type="done", data=snap)` where `snap` is the serialized TaskSnapshot. So the actual access path is `event.data["result"]`.

### `scheduler.dispatch_generation` signature

```python
# src/songmaker_cli/scheduler.py
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.orm import Session

from acestep_engine.models import AceStepConfig

# GenerationTaskResultDTO is defined in this same file (see D2).

ProgressCallback = Callable[[float], Awaitable[None] | None]
HeartbeatCallback = Callable[[], Awaitable[None] | None]


class NoCapacityError(RuntimeError):
    """Raised when no online worker can serve the requested model."""


class WorkerTaskFailed(RuntimeError):
    """Raised when the worker emits an `error` SSE event."""


@dataclass
class DispatchOptions:
    max_sse_reconnects: int = 5
    load_model_timeout_seconds: float = 600.0
    generate_submit_timeout_seconds: float = 30.0
    sse_read_timeout_seconds: float | None = None  # None = no read timeout


async def dispatch_generation(
    *,
    ace_config: AceStepConfig,
    target_mode: str,
    on_progress: ProgressCallback | None = None,
    on_heartbeat: HeartbeatCallback | None = None,
    redis: Redis,
    db: Session,
    options: DispatchOptions = DispatchOptions(),
) -> GenerationTaskResultDTO:
    ...
```

The `db` Session is opened by the caller (`run_generation_job` via `db_factory()`) and passed in for the lifetime of one dispatch. The scheduler does not commit — it only reads worker identities. The `redis` parameter is typed as `redis.asyncio.Redis` (the base class that both `ArqRedis` and `fakeredis.aioredis.FakeRedis` inherit from), which is the honest contract: the scheduler only needs basic GET/SET/INCR/DECR.

**Why a callback for progress and not a return-of-events?** Because the music-worker still owns the DB job row. The callback updates that row (throttled, same as today's `_make_generation_progress_callback`). Returning events would force the caller to know the SSE shape, which is the scheduler's job to hide.

**Why both `on_progress` and `on_heartbeat`?** Today's progress callback also touches the job heartbeat every 30s on non-progress text — this prevents the stale-job reaper from killing in-flight generations. After cutover, the worker emits cleaner `progress` events (a float, not raw text), so the scheduler triggers `on_heartbeat` whenever an SSE event arrives — even if `on_progress` is throttled.

### `run_generation_job` changes (the most invasive edit)

Becomes `async def`. Replaces `generate_single` with `scheduler.dispatch_generation` + `post_process_generation`. New signature:

```python
async def run_generation_job(
    job_id: str, song_id: str, version_id: str, count: int,
    user_id: str,
    db_factory: sessionmaker[Session] | None = None,
    audio_dir: Path | None = None,
    data_dir: Path | None = None,
    seed: int | None = None,
    repaint_params: dict | None = None,
    cover_params: dict | None = None,
    redis: Redis | None = None,   # NEW: passed from music_worker.generate
) -> None:
```

The arq function `music_worker.generate` is already async — it just needs to `await run_generation_job(...)` directly instead of `asyncio.to_thread(run_generation_job, ...)`, and it passes `ctx["redis"]` as the `redis` argument. `ctx["redis"]` is an `ArqRedis` instance owned by the arq worker process — a different connection from the `arq_pool.py` singleton in the web container, but the same Redis server. Both satisfy the `redis.asyncio.Redis` base type the scheduler asks for.

### `post_process_generation` signature

```python
# src/songmaker_cli/jobs.py (replaces _run_single_generation)

def post_process_generation(
    *,
    worker_result: GenerationTaskResultDTO,
    ctx: GenerationContext,
    generation_id: str,
    db_factory: sessionmaker[Session],
) -> None:
    """Read the worker's WAV, master+encode, write generation row, delete worker temp.

    SYNCHRONOUS (CPU-bound). Caller wraps in `asyncio.to_thread` from the
    async run_generation_job. Mastering + MP3 encoding are libsndfile/lame
    work in C extensions — they release the GIL but they still block the
    asyncio event loop if called directly.
    """
```

This is the **only** place that touches `generate.py`'s post-processing primitives (decode, splice, master, write_stereo_wav, encode_mp3). It moves those calls *out* of `generate_single` (which gets deleted) and into `post_process_generation`.

### What gets deleted from `generate.py`

- `generate_single()` — entire function
- `_run_generation()` — entire function (the worker drives ACE-Step now)
- `_cleanup_partial_files()` — only used by `generate_single`
- **Kept** (moved/used by `post_process_generation`):
  - `DecodedAudio` dataclass
  - `GenerationResult` dataclass (renamed conceptually but the existing one fits — we still hand back mp3_path/wav_path/seed/duration/cot_*)
  - `_decode_audio()`
  - `_read_source_wav()`
  - `_splice_repaint_raw()`
  - `_write_output()`
  - `CROSSFADE_SECONDS` constant

The non-deleted functions all stay in `generate.py`. They become helpers for `post_process_generation` rather than internals of `generate_single`. **No new file**, no movement of code — just deletion of two top-level callers.

`post_process_generation` wires them together:

```python
def post_process_generation(*, worker_result, ctx, generation_id, db_factory):
    src_wav = Path(worker_result.audio_path)
    try:
        ace_result = _AceStepResultShim(
            wav_bytes=src_wav.read_bytes(),
            seed=worker_result.seed,
            cot_caption=worker_result.cot_caption,
            cot_lyrics=worker_result.cot_lyrics,
        )
        decoded = _decode_audio(ace_result)

        server_handles_crossfade = bool(
            ctx.ace_config.repaint_mode or ctx.ace_config.repaint_wav_crossfade_sec > 0
        )
        needs_splice = (
            ctx.ace_config.task_type == "repaint"
            and ctx.ace_config.src_audio
            and not server_handles_crossfade
        )
        if needs_splice:
            splice_src = ctx.raw_src_audio or ctx.ace_config.src_audio
            decoded = _splice_repaint_raw(decoded, ctx.ace_config, splice_src)

        mp3_path = audio_file_path(ctx.audio_dir, ctx.user_id, generation_id, ".mp3")
        wav_path = audio_file_path(ctx.audio_dir, ctx.user_id, generation_id, ".wav")
        raw_wav_path = audio_file_path(ctx.audio_dir, ctx.user_id, generation_id, ".raw.wav")
        write_stereo_wav(str(raw_wav_path), decoded.left, decoded.right, decoded.sample_rate)
        _write_output(decoded, worker_result.seed, mp3_path, wav_path, ctx.meta, ctx.album_meta)

        _persist_generation_row(
            db_factory, ctx, generation_id, worker_result, mp3_path, wav_path,
        )
    finally:
        try:
            src_wav.unlink()
        except OSError:
            log.warning("Failed to delete worker temp WAV: %s", src_wav)
```

`_AceStepResultShim` is a tiny local namedtuple/dataclass that satisfies `_decode_audio`'s expected `.wav_bytes` attribute — `_decode_audio` only reads `ace_result.wav_bytes`. Cleaner than refactoring `_decode_audio` to take raw bytes (which would invalidate its existing tests).

`_persist_generation_row` is the existing DB-write block from `_run_single_generation` lines 277-293, lifted out as a helper. Nothing else changes about the StoredGenerationParams build.

## D2. Worker DTO — where it lives (engine isolation)

The scheduler needs `GenerationTaskResultDTO` as a Pydantic model. Where to put it?

- **Not in `acestep_worker/models.py`** — the music-worker can't import from `acestep_worker` (engine isolation rule for the wrapper itself; though the rule is "engine packages don't import from songmaker_cli", the inverse is allowed today, but importing from `acestep_worker` from `songmaker_cli` couples the control plane to a peer container's source).
- **Not in `acestep_engine/models.py`** — `acestep_engine` is the HTTP client to the inner ACE-Step process, not the worker wrapper.
- **In `songmaker_cli/scheduler.py`** — same place as the scheduler. Defined locally as `GenerationTaskResultDTO(BaseModel)`. The worker's `acestep_worker.models.GenerationTaskResult` is a structurally identical twin (same fields, validated independently).

This is duplication, but it's the right kind: the worker owns its output schema, the scheduler owns the contract it expects, and a test asserts they match. Concretely:

```python
assert (
    GenerationTaskResult.model_fields.keys()
    == GenerationTaskResultDTO.model_fields.keys()
)
```

Same check pattern as the Phase 2 Redis prefix sync test. `.keys()` is the simplest comparison that catches added/removed/renamed fields. (Comparing `model_fields` directly compares `FieldInfo` objects, which is needlessly strict — if one side adds a default value and the other doesn't, the test fails for a non-bug.)

## D3. Async-all-the-way migration

`run_generation_job` becomes `async def`. CPU-bound work is wrapped in `asyncio.to_thread`. Specifically:

| Step | Sync or async | Wrap in to_thread? |
|---|---|---|
| `_load_song_meta` (DB read) | sync | yes (DB I/O via SQLAlchemy) |
| `_build_generation_context` (DB + AceStepConfig build) | sync | yes |
| `_apply_task_overrides` (path manipulation) | sync | no (microseconds) |
| `scheduler.dispatch_generation` (httpx + SSE) | **async** | n/a |
| `post_process_generation` (decode, splice, master, encode_mp3, DB INSERT) | sync | **yes** |
| `_finalize_generation_job` (DB UPDATE) | sync | yes |
| `_update_job` (DB UPDATE) | sync | yes |

The "wrap DB ops in to_thread" rule is conservative — SQLAlchemy sync sessions don't release the GIL on every query, but the small queries here run in microseconds and there's only one music-worker instance per host, so the overhead of `to_thread` isn't worth it for them. **Decision:** wrap only the genuinely-blocking calls: `_build_generation_context` and `post_process_generation`. Leave the small `_update_job` calls direct.

Why: `_update_job` is called from many places, including the existing `_make_generation_progress_callback`. Forcing all of those through `to_thread` cascades into making the callback async, which then forces the scheduler's progress wiring to be async-aware. Keep them sync, it's not worth the noise.

**The hard rule:** anything that decodes or encodes audio (mastering, MP3 encoding, scipy WAV reads, numpy splicing) MUST run inside `asyncio.to_thread`. These take 1–10 seconds and would block the event loop, freezing SSE consumption from the worker.

## D4. `_copy_to_tmp` → shared volume tmp dir

Today:

```python
def _copy_to_tmp(src_path: str) -> str:
    suffix = Path(src_path).suffix
    fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="songmaker_src_")
    os.close(fd)
    shutil.copy2(src_path, tmp_path)
    return tmp_path
```

`tempfile.mkstemp()` returns a path under `/tmp` (or wherever `TMPDIR` points). Each container has its own `/tmp` — the acestep-worker can't read what the music-worker wrote. Repaint and cover both depend on this for `src_audio`.

**Fix:** new helper in `jobs.py`:

```python
SHARED_TMP_DIRNAME = ".tmp"  # constant in constants.py


def _shared_tmp_dir(audio_dir: Path) -> Path:
    d = audio_dir / SHARED_TMP_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _copy_to_shared_tmp(src_path: str, audio_dir: Path) -> str:
    suffix = Path(src_path).suffix
    fd, tmp_path = tempfile.mkstemp(
        suffix=suffix, prefix="songmaker_src_", dir=_shared_tmp_dir(audio_dir),
    )
    os.close(fd)
    shutil.copy2(src_path, tmp_path)
    return tmp_path
```

The path returned is something like `/app/data/audio/.tmp/songmaker_src_xyz.wav`. Both containers see this exact path because `audiofiles:/app/data/audio` is mounted identically (verified — see D5).

**The cleanup logic in `run_generation_job`** at line 481-486 checks `tempfile.gettempdir()` to identify temp files. After the change, switch the prefix check to `str(audio_dir / SHARED_TMP_DIRNAME)`.

`_apply_task_overrides` calls `_copy_to_tmp` twice (once for src_wav, once for raw_wav). Both call sites switch to `_copy_to_shared_tmp(..., audio_dir=ctx.audio_dir)`. Pass `ctx.audio_dir` since it's already on the context.

**Test impact:** `test_jobs.py::test_apply_task_overrides_*` (the `_apply_task_overrides` tests) currently expect `result.ace_config.src_audio.startswith("/tmp/")`. Update to `startswith(str(audio_dir / ".tmp"))`. The `test_cover_does_not_convert_fractions` assertion at the end of test_jobs.py is exactly this.

## D5. Volume mount verification

Required mounts (Phase 3 docker-compose state):

```yaml
songmaker-music-worker:
  volumes:
    - audiofiles:/app/data/audio       # shared with web + acestep-worker

songmaker-acestep-worker-0:
  volumes:
    - ./_models/acestep:/app/_models/acestep  # local checkpoints
    - audiofiles:/app/data/audio              # shared with web + music-worker
```

Both `audiofiles:/app/data/audio` mounts use **identical container paths** — required for D4's shared tmp dir + the worker output dir + the scheduler reading the worker's output WAV. **Already true** in current compose. Verify nothing changes this in Phase 3.

The `_models/acestep` mount on the music-worker gets **removed** — the music-worker no longer needs ACE-Step weights. The acestep-worker keeps it.

## D6. Worker progress wiring (Phase 1 gap)

Today's [acestep_worker/wrapper.py:197 default_generate_runner](../src/acestep_worker/wrapper.py#L197):

```python
result = await asyncio.to_thread(client.generate, ace_config)
```

No `on_progress` argument. The worker emits zero `progress` events between `running` and `done`. The scheduler will sit blind for 5–10 minutes per generation.

**Fix:** wire `on_progress` through to `task_store.update_progress`. The progress text comes from `acestep_engine.client.AceStepClient.generate(on_progress=...)` which fires on each poll tick with raw progress text like `"8/50 [00:02<00:13]"`.

The diffusion-step parser (`_DIFFUSION_STEP_PATTERN`, `_parse_step_fraction` in [jobs.py:320](../src/songmaker_cli/jobs.py#L320)) **moves to the worker** — parse at the source.

New code in `acestep_worker/wrapper.py` (or a new tiny file `acestep_worker/progress.py` if it grows):

```python
import re

_DIFFUSION_STEP_PATTERN = re.compile(r"(\d+)/(\d+)\s*\[")


def parse_step_fraction(progress_text: str) -> float | None:
    m = _DIFFUSION_STEP_PATTERN.search(progress_text)
    if m:
        current, total = int(m.group(1)), int(m.group(2))
        if total > 0:
            return min(current / total, 1.0)
    return None
```

The runner becomes:

```python
async def default_generate_runner(task_store, task_id, *, mode, config, port, audio_output_dir):
    from acestep_engine.client import AceStepClient
    from acestep_engine.models import AceStepConfig
    from acestep_worker.progress import parse_step_fraction

    await task_store.mark_running(task_id)
    try:
        ace_config = AceStepConfig(**config)
        client = AceStepClient(host="http://127.0.0.1", port=port)

        loop = asyncio.get_running_loop()

        def _on_progress(text: str) -> None:
            fraction = parse_step_fraction(text)
            if fraction is None:
                return
            asyncio.run_coroutine_threadsafe(
                task_store.update_progress(task_id, fraction), loop,
            )

        result = await asyncio.to_thread(
            client.generate, ace_config, on_progress=_on_progress,
        )
        # ... existing complete() call
```

`asyncio.run_coroutine_threadsafe` is required because `_on_progress` is invoked from the worker thread (via `asyncio.to_thread`), which is not the event loop thread, so we can't call `await task_store.update_progress(...)` directly. `run_coroutine_threadsafe` is the standard bridge — fire-and-forget the future since we don't care about its return.

**`_parse_step_fraction` and `_DIFFUSION_STEP_PATTERN` are deleted from `jobs.py`.** The scheduler-side throttle logic (`_PROGRESS_THROTTLE_SECONDS`) now lives in the music-worker progress callback (`_make_generation_progress_callback` is rebuilt to take a float, not a text).

```python
# new in jobs.py — replaces existing _make_generation_progress_callback
def _make_generation_progress_callback(
    db_factory, job_id, variant_index, count,
) -> Callable[[float], None]:
    last_update = 0.0

    def _on_progress(step_fraction: float) -> None:
        nonlocal last_update
        now = time.monotonic()
        if now - last_update < _PROGRESS_THROTTLE_SECONDS:
            return
        combined = (variant_index + step_fraction) / count
        _update_job(db_factory, job_id, "running", progress=combined)
        last_update = now

    return _on_progress
```

The heartbeat path is split into a separate callback. The scheduler triggers it on **every** SSE event (progress or otherwise), so even a no-progress job stays alive.

**Test impact:** `test_jobs.py::test_parse_step_fraction*` tests get **moved** to `tests/acestep_worker/test_progress.py`. The `_parse_step_fraction` import and tests in test_jobs disappear.

## D7. `acestep_engine` stays in Dockerfile.worker

Per the user's explicit requirement: don't strip `acestep_engine` from `Dockerfile.worker`. The music-worker still imports `AceStepConfig` (from `acestep_engine.models`) to build the request payload that goes to the scheduler.

`Dockerfile.worker` is currently shared between `songmaker-music-worker` and `songmaker-scoring-worker` (both use `dockerfile: Dockerfile.worker` in compose). The scoring worker needs `--extra scoring --extra whisper`, which includes `huggingface_hub` for model downloads. **Verdict: Dockerfile.worker is unchanged in Phase 3.** No deps stripped, no HF mounts removed — the scoring worker still needs them.

The music-worker container gets smaller only via compose-level changes:
- Remove `deploy.resources.devices` (no GPU)
- Remove `_models/acestep` mount
- Remove `ACESTEP_API_HOST`, `ACESTEP_API_PORT`, `HF_TOKEN` env vars
- Add `SONGMAKER_INTERNAL_TOKEN` env var (scheduler needs it to call workers)

`HF_TOKEN` is still used by the scoring-worker for downloading whisper/audiobox models, so it stays in compose globally — just removed from the music-worker's env block.

## D8. `GenerationContext.client: AceStepClient` deletion

[jobs.py:69](../src/songmaker_cli/jobs.py#L69) — the `client` field on `GenerationContext` is dead after cutover. The scheduler builds its own httpx client per dispatch; the music-worker doesn't talk to ACE-Step directly.

Delete the field. Update `_build_generation_context` to no longer construct an `AceStepClient` (lines 154-161). The model name (used to be read from `client.server_info().model`) is now resolved differently:

**The model_name resolution problem.** Today, `_build_generation_context` calls `client.server_info()` to learn which ACE-Step model is currently loaded, then passes that as the `model` field on `AceStepConfig` and uses it to load presets. After cutover, the music-worker doesn't know which model the worker has loaded — that's the worker's state.

**Resolution:** `model_name` comes from the *requested* model (`req.model` in the API endpoint, passed through to the arq job and into `_build_generation_context`). If no model was explicitly requested, the music-worker falls back to a server-side default constant (`DEFAULT_MODEL_MODE`, see existing `resolve_model_mode` for the value). The scheduler is not in the business of picking defaults — that's the music-worker's job before it calls `dispatch_generation`.

`run_generation_job` already takes `requested_model` (passed via `music_worker.generate(...,  requested_model=None,...)` — wait, let me re-check the current signature).

Actually [music_worker.py:57-58](../src/songmaker_cli/music_worker.py#L57):

```python
async def generate(ctx, job_id, song_id, version_id, count, user_id, seed=None,
                   requested_model=None, repaint_params=None, cover_params=None):
```

`requested_model` IS already passed. But it's never threaded into `run_generation_job`. Lines 65-72 of `music_worker.generate` use it to call `mgr.switch_model(...)` directly. That code goes away.

**Phase 3 change:** `music_worker.generate` passes `requested_model` to `run_generation_job` as a new `target_model: str | None` parameter. `run_generation_job` then passes it to `_build_generation_context(..., target_model=...)`. `_build_generation_context` uses it as `model_name` (no `client.server_info()` call). If `target_model is None`, fall back to a constant `DEFAULT_MODEL_MODE = "sft"` (or whatever the existing default is — check `resolve_model_mode`).

Then `model_name` is passed to `dispatch_generation(target_mode=model_name, ...)`. The scheduler's `pick_worker` uses it to prefer-loaded.

## D9. Health endpoint cleanup

[health_api.py:175-182](../src/songmaker_cli/health_api.py#L175) currently does:

```python
acestep_model = await get_active_model()
if acestep_model is not None:
    acestep = "healthy"
else:
    from songmaker_cli.acestep_manager import AceStepManager
    mgr = AceStepManager()
    acestep = "healthy" if mgr.is_healthy() else "unknown"
```

After cutover, `get_active_model()` is gone (it reads `ACTIVE_MODEL_REDIS_KEY` which we delete) and `AceStepManager` is gone. Replacement: any online worker = healthy.

```python
# in health_api.py
from songmaker_cli.db.queries import list_worker_identities
from songmaker_cli.acestep_state import read_worker_state

worker_count = 0
online_count = 0
with ctx.db() as session:
    workers = list_worker_identities(session)
worker_count = len(workers)
for w in workers:
    if await read_worker_state(pool, w.id) is not None:
        online_count += 1

acestep = "healthy" if online_count > 0 else ("unknown" if worker_count == 0 else "unhealthy")
```

Add `acestep_workers_total: int` and `acestep_workers_online: int` to the health response model so the operator sees the new shape. Drop the old `acestep_model` field (a string model name) — it's replaced by the worker count. Frontend admin diagnostics that read `acestep_model` get updated in Phase 4 (not Phase 3); for Phase 3, leaving the field undefined breaks one frontend call site, which we accept as part of cutover.

## D10. Cleanup of stale constants and imports

Delete from `constants.py`:
- `ACESTEP_PORT` (line 87)
- `ACTIVE_MODEL_REDIS_KEY` (line 96)
- `ACTIVE_MODEL_TTL_SECONDS`
- `ACESTEP_STATUS_REDIS_KEY` (line 98)
- `ACESTEP_STATUS_TTL_SECONDS` (line 99)
- `ACESTEP_HEALTH_URL_TEMPLATE`

Verify nothing else imports them post-deletion (`grep -rn ACESTEP_PORT src/`).

Delete from `arq_pool.py`:
- `get_active_model()` function
- `ACTIVE_MODEL_REDIS_KEY` import

## D11. Frontend `admin.ts` cleanup

[frontend/src/lib/api/admin.ts:67-71](../frontend/src/lib/api/admin.ts) calls `/api/admin/acestep/status` and `/api/admin/acestep/reinitialize`. After Phase 3 these endpoints return 404.

**Decision:** delete the two functions in `admin.ts` and any direct callers in Svelte components in Phase 3. **This bleeds into the Phase 4 territory** but is unavoidable — leaving dead frontend functions pointing to 404 endpoints is worse than touching the frontend a bit early.

Grep for `acestep_status`, `acestep_reinitialize` in `frontend/src/` and remove call sites. The replacement panels (Worker Pool, Model Registry) come in Phase 4. For Phase 3, the admin UI loses the "ACE-Step status" widget — accepted regression for one phase.

## D12. Files Touched (Phase 3)

| File | Change |
|---|---|
| `src/songmaker_cli/scheduler.py` | **New** — `pick_worker`, `dispatch_generation`, `consume_task_stream`, `NoCapacityError`, `WorkerTaskFailed`, `DispatchOptions`, `GenerationTaskResultDTO` |
| `src/songmaker_cli/jobs.py` | `run_generation_job` → async, calls `dispatch_generation` + `post_process_generation`. Delete `_run_single_generation`, `_DIFFUSION_STEP_PATTERN`, `_parse_step_fraction`. Rebuild `_make_generation_progress_callback` to take a float. Add `_copy_to_shared_tmp`, `_shared_tmp_dir`, `post_process_generation`, `_persist_generation_row`. Delete `client: AceStepClient` field on `GenerationContext`. |
| `src/songmaker_cli/generate.py` | Delete `generate_single`, `_run_generation`, `_cleanup_partial_files`. Keep `_decode_audio`, `_read_source_wav`, `_splice_repaint_raw`, `_write_output`, `DecodedAudio`, `GenerationResult`, `CROSSFADE_SECONDS`. Remove `from acestep_engine import AceStepClient, AceStepError` (no longer needed). |
| `src/songmaker_cli/music_worker.py` | Delete `_acestep_manager`, `_acestep_lock`, `_require_acestep_manager`, `reinitialize_acestep`, `_publish_acestep_status`, `publish_acestep_heartbeat`. `generate` becomes `await run_generation_job(...)`. `on_startup` no longer instantiates `AceStepManager`. `cron_jobs` drops the heartbeat cron. `MusicWorkerSettings.functions` drops `reinitialize_acestep`. |
| `src/songmaker_cli/acestep_manager.py` | **Delete entirely.** |
| `src/songmaker_cli/admin_api.py` | Delete `reinitialize_acestep` endpoint, `acestep_status` endpoint, imports of `AceStepStatusResponse`, `ReinitializeRequest`, `ACESTEP_STATUS_REDIS_KEY`. |
| `src/songmaker_cli/api_models/settings.py` | Delete `AceStepStatusResponse`, `ReinitializeRequest`. |
| `src/songmaker_cli/api_models/__init__.py` | Drop `AceStepStatusResponse` from re-exports + `__all__`. |
| `src/songmaker_cli/generation_api.py` | `api_generate_song`, `api_repaint_generation`, `api_cover_generation`: replace `is_music_worker_healthy` check with "at least one online worker" check. Remove `list_active_models` model gate (the worker rejects unknown modes; we don't gate at the API). |
| `src/songmaker_cli/health_api.py` | Replace `get_active_model` + `AceStepManager` with worker-count-based health check. Update health response model (drop `acestep_model`, add `acestep_workers_total`/`_online`). |
| `src/songmaker_cli/arq_pool.py` | Delete `get_active_model`, `ACTIVE_MODEL_REDIS_KEY` import. |
| `src/songmaker_cli/constants.py` | Delete `ACESTEP_PORT`, `ACTIVE_MODEL_REDIS_KEY`, `ACTIVE_MODEL_TTL_SECONDS`, `ACESTEP_STATUS_REDIS_KEY`, `ACESTEP_STATUS_TTL_SECONDS`, `ACESTEP_HEALTH_URL_TEMPLATE`. Add `SHARED_TMP_DIRNAME`. |
| `src/acestep_worker/wrapper.py` | Wire `on_progress` through `default_generate_runner` to `task_store.update_progress` via `run_coroutine_threadsafe`. |
| `src/acestep_worker/progress.py` | **New** — `parse_step_fraction` (moved from jobs.py). |
| `src/acestep_worker/models.py` | Add `GenerationTaskResult` Pydantic model for the worker's `done` event payload. Update `default_generate_runner.complete()` call to validate against it. |
| `frontend/src/lib/api/admin.ts` | Delete `acestep_status`, `acestep_reinitialize` functions. |
| `frontend/src/lib/components/AdminPanel*.svelte` | Remove ACE-Step status widget calls (grep for usage). |
| `docker-compose.yml` | Music-worker: drop GPU `deploy.resources`, drop `_models/acestep` mount, drop `ACESTEP_API_HOST`/`ACESTEP_API_PORT`/`HF_TOKEN` env, add `SONGMAKER_INTERNAL_TOKEN` env. |
| `docs/architecture.md` | Replace music-worker-owns-acestep diagram with the worker pool diagram from the parent plan. Update text. |
| `docs/acestep.md` | Update "ACE-Step Server" section: scheduler dispatches to workers. Operator details (restart, metrics) deferred to Phase 6. |
| `tests/test_scheduler.py` | **New** — pick_worker policies (prefer-loaded, least-busy, no-workers), atomic INCR/DECR pairing, SSE reconnect on transport drop, error event raises WorkerTaskFailed, done event returns DTO. |
| `tests/test_jobs.py` | Rewrite all 9 `run_generation_job(` call sites to async + new mock targets (`scheduler.dispatch_generation`, `_post_process_generation`). Delete `_parse_step_fraction` tests. Move them to `tests/acestep_worker/test_progress.py`. |
| `tests/test_jobs.py` (cont.) | Update `_apply_task_overrides` test assertions to expect shared tmp dir prefix instead of `/tmp`. |
| `tests/test_music_worker.py` | Delete tests for `_acestep_manager`, `reinitialize_acestep`, `publish_acestep_heartbeat`. Update `test_music_worker_settings_functions` to expect `[generate, load_model_on_worker]` (no reinitialize). Update cron count from 2 → 1. |
| `tests/test_admin_api.py` | Delete `test_reinitialize_acestep_*` (4 tests) and `test_acestep_status_*` (2 tests). |
| `tests/test_generation_api.py` (or `test_api.py` — find by grep) | Add: 503 when no online workers. Update existing model-validation tests if any. |
| `tests/test_acestep_manager.py` | **Delete entirely.** |
| `tests/test_cli.py` | Delete `test_generate_single_*` (4 tests). |
| `tests/test_db.py` | No change (already updated for `acestep_workers` table). |
| `tests/acestep_worker/test_wrapper.py` | Add: progress callback fires on parsed step events. |
| `tests/acestep_worker/test_progress.py` | **New** — `parse_step_fraction` happy path, no-match, division-by-zero guard. |
| `frontend/src/lib/api/types.ts` | Regenerated by `scripts/generate_types.py`. |

## D13. Implementation order

Strict order — each step leaves the codebase importable and the tests passing for the things that aren't yet rewritten. **Don't try to be clever and parallelize.** Phase 3 is a cutover; one wrong step leaves the tree broken.

1. **Read CLAUDE.md and this sub-plan one more time** (1 min)
2. **`acestep_worker/progress.py`** + tests for `parse_step_fraction` (10 min)
3. **`acestep_worker/wrapper.py`** wire `on_progress` through `default_generate_runner`. Add `acestep_worker/models.py::GenerationTaskResult`. Run `pytest tests/acestep_worker/ -q` to confirm nothing regressed. (20 min)
4. **`tests/acestep_worker/test_wrapper.py`** add the progress-callback test. Run. (10 min)
5. **`src/songmaker_cli/scheduler.py`** new file. `pick_worker`, `dispatch_generation`, `consume_task_stream`, DTO, errors, `DispatchOptions`. (60 min)
6. **`tests/test_scheduler.py`** new file. Mock httpx + Redis. Cover all decision branches. (90 min)
7. **`src/songmaker_cli/constants.py`** add `SHARED_TMP_DIRNAME`. Don't delete the legacy ones yet. (1 min)
8. **`src/songmaker_cli/jobs.py`** add `_copy_to_shared_tmp`, `_shared_tmp_dir`, `post_process_generation`, `_persist_generation_row`. Don't touch `run_generation_job` or `generate_single` yet. (40 min)
9. **`src/songmaker_cli/jobs.py`** rewrite `run_generation_job` to async, use scheduler + post-process. Rebuild `_make_generation_progress_callback`. Delete `_run_single_generation`. (45 min)
10. **`src/songmaker_cli/music_worker.py`** delete acestep_manager wiring, change `generate` to `await run_generation_job(...)`. Drop reinitialize_acestep, _publish_acestep_status, publish_acestep_heartbeat, the heartbeat cron. (30 min)
11. **`src/songmaker_cli/generate.py`** delete `generate_single`, `_run_generation`, `_cleanup_partial_files`, the `AceStepClient` import. (15 min)
12. **`tests/test_jobs.py`** rewrite all 9 `run_generation_job(` call sites. Update `_apply_task_overrides` assertion paths. Delete parse_step_fraction tests. (90 min)
13. **`tests/test_music_worker.py`** prune deleted-feature tests, update settings assertions. (20 min)
14. **`tests/test_cli.py`** delete `test_generate_single_*`. (5 min)
15. **`src/songmaker_cli/acestep_manager.py`** delete the file. **`tests/test_acestep_manager.py`** delete the file. (1 min)
16. **`src/songmaker_cli/admin_api.py`** delete reinitialize + acestep_status endpoints + their imports. **`tests/test_admin_api.py`** delete the 6 corresponding tests. (15 min)
17. **`src/songmaker_cli/api_models/settings.py`** + `__init__.py` delete `AceStepStatusResponse`, `ReinitializeRequest`, drop from `__all__`. (5 min)
18. **`src/songmaker_cli/generation_api.py`** swap model gate + worker-online check. Update test (find via grep — likely `tests/test_api.py`). (20 min)
19. **`src/songmaker_cli/health_api.py`** rewrite acestep health to worker-count based. Update health response model. Update tests in `test_server.py` or wherever health is tested. (20 min)
20. **`src/songmaker_cli/arq_pool.py`** delete `get_active_model`. **`src/songmaker_cli/constants.py`** delete the legacy ACESTEP_* constants. Verify with grep nothing references them. (10 min)
21. **`frontend/src/lib/api/admin.ts`** + Svelte component cleanups. (10 min)
22. **`docker-compose.yml`** music-worker: strip GPU/_models/HF, add internal token. (10 min)
23. **`docs/architecture.md`** + `docs/acestep.md` updates. (30 min)
24. **`scripts/generate_types.py`** regen + commit. (2 min)
25. **Self-review pass** — `git diff HEAD~N` end-to-end. Read every diff. Look for dead imports, unused params, leftover references to deleted symbols. (30 min)
26. **Run checks**: `ruff check src/ tests/`, full `pytest tests/ --ignore=...`, frontend `pnpm check`. Fix everything. (30 min)
27. **Coverage**: `--cov=songmaker_cli.scheduler --cov=songmaker_cli.jobs --cov-report=term-missing`. Aim for 100% on new files. (10 min)
28. **Commit + push** in 3 commits per the split in D18. (5 min)
29. **End-to-end smoke test** is the user's job per Phase 3 conversation — I will not `docker compose up` until they say go.

Total wall clock estimate: 8–10 hours of focused work. Don't try to compress this.

## D14. Test strategy

### Critical tests (catch the most bugs)

1. **`test_scheduler.py::test_pick_worker_prefer_loaded`** — two online workers, target_mode loaded only on one. Returns the loaded one regardless of queue depth.
2. **`test_scheduler.py::test_pick_worker_falls_back_to_least_busy`** — two online workers, target_mode loaded on neither. Returns the one with lower queue_depth.
3. **`test_scheduler.py::test_pick_worker_no_workers_raises`** — empty PG. Raises NoCapacityError.
4. **`test_scheduler.py::test_pick_worker_skips_offline`** — PG row exists, Redis state missing → that worker is skipped (effectively dead). If that was the only one, raises.
5. **`test_scheduler.py::test_dispatch_increments_then_decrements_queue_depth`** — assert INCR before /generate, DECR after stream completes. Use a fake redis store to verify counter ends at zero.
6. **`test_scheduler.py::test_dispatch_decrements_on_failure`** — worker raises 500 → DECR still fires (the `finally` block).
7. **`test_scheduler.py::test_dispatch_loads_model_if_not_loaded`** — Redis state has `loaded: []`, target=`sft`. Mock httpx asserts POST /load_model called BEFORE POST /generate. If `loaded: ["sft"]` already → no /load_model call.
8. **`test_scheduler.py::test_consume_task_stream_done`** — mock SSE yields a `done` event with valid result. Returns the validated DTO.
9. **`test_scheduler.py::test_consume_task_stream_error`** — mock SSE yields an `error` event. Raises WorkerTaskFailed.
10. **`test_scheduler.py::test_consume_task_stream_progress_calls_callback`** — mock SSE yields several progress events. Asserts on_progress was called with the floats.
11. **`test_scheduler.py::test_consume_task_stream_reconnects_on_transport_error`** — first httpx.stream raises ConnectError, second yields `done`. Asserts the result is returned without error. Reconnect counter increments.
12. **`test_scheduler.py::test_consume_task_stream_gives_up_after_max_reconnects`** — all 6 attempts fail. Raises the underlying httpx error.
13. **`test_scheduler.py::test_dto_matches_worker_model_fields`** — imports both `acestep_worker.models.GenerationTaskResult` and `songmaker_cli.scheduler.GenerationTaskResultDTO`, asserts `GenerationTaskResult.model_fields.keys() == GenerationTaskResultDTO.model_fields.keys()`. Catches drift between worker output schema and scheduler expectations. Same pattern as Phase 2's prefix-sync test.

### Tests that would pass even if implementation is wrong (avoid)

- ❌ `test_dispatch_calls_pick_worker` (mocks pick_worker, asserts it was called — tests the test)
- ❌ `test_run_generation_job_returns_none` (vacuous)
- ❌ Mocking `dispatch_generation` and asserting it was called from `run_generation_job` without checking what happens to its return value

### Coverage expectation

- 100% on `scheduler.py` (new file)
- 100% on `acestep_worker/progress.py` (new file)
- The new code in `jobs.py` and `wrapper.py` should also hit 100%; existing code keeps whatever it had

## D15. Self-review checklist (before commit)

1. **Re-read every changed file via `git diff HEAD~N`**. No skipping.
2. **`grep -rn ACESTEP_PORT\|ACTIVE_MODEL_REDIS_KEY\|ACESTEP_STATUS\|acestep_manager\|AceStepManager src/ tests/`** — all hits should be in `acestep_engine/client.py` (which has its own `ACESTEP_PORT` env var) and nowhere else.
3. **`grep -rn generate_single src/`** — zero hits. `tests/` may still have a stray import — delete.
4. **`grep -rn _run_single_generation src/ tests/`** — zero hits.
5. **`grep -rn AceStepClient src/songmaker_cli/`** — zero hits in songmaker_cli (only in `acestep_engine/` and `acestep_worker/`).
6. **`grep -rn AceStepStatusResponse\|ReinitializeRequest`** — zero hits.
7. **No comments in new code** (per `feedback_code_standards.md`).
8. **Every endpoint that mutates DB calls `db.commit()`** — already true in Phase 2 endpoints, just verify nothing got dropped during refactor.
9. **The shared tmp dir cleanup** — `_apply_task_overrides` paths must be cleaned up in `run_generation_job`'s `finally`, even on early-failure paths. The existing logic at lines 481-486 covers this; just verify the prefix check matches the new dir.
10. **Worker WAV cleanup** — `post_process_generation`'s `finally` deletes the worker's temp WAV. If `post_process_generation` raises before the `try` block (parameter validation, etc.), the cleanup doesn't fire. Verify this can't happen by reading the code.
11. **`scripts/generate_types.py`** ran at the end and produced a valid TS file with no diff issues.
12. **Full project test suite passes** — not just new tests. Same `--ignore` set as Phase 2.

## D16. Things to watch out for

### Watchpoint 1: SSE consumption blocks the event loop indefinitely

`async for line in resp.aiter_lines()` is awaitable but if the worker stops sending data without closing the connection, it blocks forever. **Mitigation:** httpx `Timeout(read=None)` is intentional (no read timeout — generations take 5–10 min), but rely on transport-level keepalives + the worker's heartbeat (every event is also a heartbeat). If a worker dies silently, the OS-level TCP timeout (~2 minutes) eventually fires and `aiter_lines` raises TransportError → reconnect logic kicks in. Document this in the scheduler module docstring.

### Watchpoint 2: `asyncio.run_coroutine_threadsafe` from a thread that has no loop

The progress callback fires from `asyncio.to_thread`'s thread. That thread doesn't own an event loop. `asyncio.get_running_loop()` called from inside the callback would fail. **Mitigation:** capture the loop via `loop = asyncio.get_running_loop()` *before* calling `asyncio.to_thread(...)`, then `asyncio.run_coroutine_threadsafe(..., loop)`. Standard pattern. Test it explicitly in `test_wrapper.py` to make sure it doesn't regress.

### Watchpoint 3: SSE event payload shape — `event.data["result"]` vs `event.data`

Today's task_store builds `WorkerTaskEvent(type="done", data=snap)` where `snap` is the full TaskSnapshot dict. So `event.data` is the TaskSnapshot, and the actual result is `event.data["result"]`. **Easy to get wrong.** Write the scheduler against the actual shape, not what intuition suggests. Verify by reading the test_task_store.py "done event" test or by running the worker and printing the payload.

### Watchpoint 4: Repaint with `raw_src_audio` — two tmp files, not one

`_apply_task_overrides` for repaint creates **two** tmp copies (src_wav and raw_wav). Both must land on the shared volume. The `tmp_copies` list in `run_generation_job` already collects both — just verify the new prefix check matches.

### Watchpoint 5: DB session lifetime in `post_process_generation`

`post_process_generation` runs in `asyncio.to_thread`. Inside, it calls `_persist_generation_row(db_factory, ...)` which opens a fresh session via `db_factory()`. This is fine (sessions are thread-bound; `db_factory()` creates a new one). **Don't pass an open session into `to_thread`** — pass the factory.

### Watchpoint 6: `health_api` async context for Redis read

The new health check reads Redis (`read_worker_state`). The endpoint is already async, but the existing code doesn't have the arq pool dependency. Check whether `get_app_context().pool` exists or whether you need to add `pool: ArqRedis = Depends(get_arq_pool_dep)`. Probably the latter — add the dep.

### Watchpoint 7: `requested_model` parameter rename / threading

`music_worker.generate(..., requested_model=None, ...)` is the arq function. The API endpoint enqueues `pool.enqueue_job("generate", job.id, song_id, version.id, count, user.id, seed, model, ...)` — see [generation_api.py:243](../src/songmaker_cli/generation_api.py#L243). The arg order is positional. If you rename the parameter in `music_worker.generate`, the positional binding still works — but if you reorder, you break it silently. **Don't reorder.** Just thread `requested_model` through to `run_generation_job` as a kwarg.

### Watchpoint 8: arq function signature change is wire-incompatible

`run_generation_job`'s parameter changes (adding `target_model` and `pool`) don't affect arq because arq sees only the wrapper `music_worker.generate`. The wrapper's signature is unchanged. The arq queue can be drained by the in-flight version of the worker before the new code rolls out. **Phase 3 has no rollback**, but it's worth knowing the arq protocol stays stable.

### Watchpoint 9: Migration files and `acestep_engine` dependency

`acestep_engine` is a top-level package in this repo, not a PyPI dependency. It's a local namespace package. Removing its imports from `songmaker_cli/generate.py` doesn't change `pyproject.toml`. The Dockerfile.worker `uv sync` step still picks it up. No wheel/install changes needed.

### Watchpoint 10: `ctx["redis"]` vs `arq_pool` in the music-worker

Inside an arq job, `ctx["redis"]` is the worker's Redis connection (a `redis.asyncio.Redis` from `arq.connections`). It's separate from the global `_pool` in `arq_pool.py`. Both connect to the same Redis instance, both work for our INCR/DECR/GET. **Use `ctx["redis"]`** in the music-worker arq job — it's the natural connection for that process, and it's already passed to other code paths (`_publish_acestep_status` uses it). Don't introduce a second connection by calling `get_arq_pool()` from inside the worker.

The web container side keeps using `get_arq_pool_dep` because it's in FastAPI dependency-injection land.

### Watchpoint 11: Don't simplify the diffusion progress regex

`_DIFFUSION_STEP_PATTERN = re.compile(r"(\d+)/(\d+)\s*\[")` is tuned for tqdm output. ACE-Step also emits LM chunk text like `"LM chunk 1/1"` which the regex avoids by requiring the trailing `[`. **Don't simplify the regex** — the bracket is load-bearing.

## D17. What is NOT in Phase 3 (deferred)

- **Frontend Worker Pool / Model Registry panels** → Phase 4
- **`download_model_on_worker` arq job** → Phase 5
- **Worker `/restart` endpoint, `/metrics` integration** → Phase 6
- **Concurrent in-flight generations on one worker** → Phase 6 (today's `MUSIC_MAX_JOBS=2` allows two simultaneous music-worker arq jobs, each dispatching to potentially the same worker; the worker's task_store handles concurrent tasks fine, just verify there's no GPU contention surprise)
- **mTLS / k8s / multi-host** → out of scope
- **Replacing the single-token internal auth with per-worker tokens** → out of scope

If you find yourself implementing any of these in Phase 3, **stop**.

## D18. Branching + commits

Phase 3 commits go on `feat/acestep-worker-pool`. Suggested split:

1. **Worker progress wiring** — `acestep_worker/progress.py`, wrapper changes, models.py, tests. Self-contained, keeps `default_generate_runner` working before the scheduler exists.
2. **Scheduler + tests** — new `scheduler.py`, `test_scheduler.py`. Doesn't touch `jobs.py` yet, so the existing `run_generation_job` still runs unchanged.
3. **Cutover** — the big one. `jobs.py` rewrite, `music_worker.py` strip, `generate.py` strip, `acestep_manager.py` deletion, admin_api/api_models/health_api/arq_pool/constants cleanup, generation_api worker-online check, frontend admin.ts cleanup, docker-compose, docs, all test rewrites.

Or one giant commit if the splits feel artificial. The user's preference is "fewer intermediate test runs, more parallelism" per `feedback_speed.md`, so don't over-fragment. **Recommended: 3 commits** (the splits above are natural review boundaries).

Push to `origin/feat/acestep-worker-pool` after each commit.

## D19. Quick context for next session's first message

If you're a new agent picking this up: read `CLAUDE.md`, then [acestep-worker-pool.md](acestep-worker-pool.md), then this file. Phase 1 is `c416194`, Phase 2 is `275518c`, both pushed. Branch is `feat/acestep-worker-pool`. Run `git log --oneline -5` to see current state.

The biggest single risk in Phase 3 is the boundary between `dispatch_generation` and `post_process_generation` — get the data flow (D1) and the worker DTO (D2) right before writing any code, and the rest follows mechanically.

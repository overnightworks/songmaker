# No Silent Fallbacks — v2

**Status:** In progress (branch `refactor/no-silent-fallbacks` open, no W1 commits yet)
**Date:** 2026-04-09
**Supersedes:** `plans/no-silent-fallbacks.md` (deleted; was a one-shot audit, this is the full cleanup)
**Driver:** 2026-04-08 incident — `resolve_model_mode(None)` silently returned `'turbo'` for every generation after `available_models` was truncated. Audit revealed the root pattern is endemic, not a one-off.
**Companion plan:** [architecture-review-findings.md](architecture-review-findings.md) — full context on the 12 review findings that motivated this work, including the 6 that already shipped via `chore/architecture-quick-wins`.

## How to pick this up in a fresh session

If you (a Claude agent or a human) are reading this for the first time and continuing the work:

### 1. Verify the starting state

```bash
git checkout refactor/no-silent-fallbacks
git log --oneline -10
# Should show "be046a9 refactor(workers): introduce WorkerBase class" near the top
# along with the other 5 quick-wins commits and the docs commit.

# Confirm migrations are up to date:
docker compose exec -T postgres psql -U songmaker -d songmaker -c "SELECT version_num FROM alembic_version;"
# Should report b2c3d4e5f6a7

# Confirm the test suite is green before you start:
.venv/bin/python -m pytest tests/ -q --no-cov
# Should report 1252 passed, 5 skipped (as of 2026-04-09)

# Confirm linter is clean:
.venv/bin/ruff check src/ tests/
```

### 2. Read these files in order

1. **`CLAUDE.md`** (auto-loaded) — project conventions, especially "Code Patterns" and "Known Technical Debt".
2. **This plan** — the workstreams, decisions, and Pydantic model design.
3. **[plans/architecture-review-findings.md](architecture-review-findings.md)** — context on what already shipped (B3, B5, B6, B10, B11) and what's deferred (B1, B8, B9). Sections marked "✓ COVERED" reference this plan.
4. **[src/acestep_engine/models.py](../src/acestep_engine/models.py)** — the `AceStepConfig` dataclass is the source of truth for which generation params are required (only `prompt` and `lyrics` have no default).
5. **[src/songmaker_cli/worker_base.py](../src/songmaker_cli/worker_base.py)** — the `WorkerBase` class introduced in B5 is where `Settings` will be injected in W1. Read it to understand the new class shape.

### 3. Decisions are locked in — do NOT re-prompt the user

The user already answered every open question. Do not ask them again. The locked decisions are in the next section. If you discover a NEW question that genuinely wasn't covered (e.g. "this Pydantic field needs a min/max constraint, what value?"), then ask. Otherwise execute.

### 4. Re-run the audit before W1 (sanity check)

The audit findings in this plan were generated 2026-04-09 against the pre-quick-wins codebase. Line numbers may have shifted by a few lines after B5/B10. Before starting W1, verify the current state with quick greps:

```bash
# Count remaining env reads (should be ~73; W1 reduces this to ~3)
grep -rn "os\.environ\|os\.getenv" src/ | grep -v __pycache__ | wc -l

# Confirm the 4 import-time footguns from CLAUDE.md still exist (they should until W1 lands):
grep -n "CLAUDE_CHAT_MODEL\|CLAUDE_SCORING_MODEL" src/songmaker_cli/constants.py
grep -n "_IMPORT_TIME_REDIS_URL\|self._import_time_redis_url" src/songmaker_cli/worker_base.py

# Sanity-check the dict-as-domain hot spots:
grep -n "generation_params\.get\|generation_params\[" src/ -r | grep -v __pycache__
grep -n "next(iter(" src/ -r | grep -v __pycache__
```

If any grep returns surprisingly few hits, something has already been fixed — update this plan before duplicating work.

### 5. Execute workstreams in order

W1 → W2 → W3 → W4 → W5. Each is a single commit on this branch. Do **not** reorder; later workstreams depend on earlier types existing.

### 6. After all 5 commits land

```bash
# Run the full check suite (per the completion criteria at the bottom of this plan)
.venv/bin/ruff check src/ tests/
.venv/bin/python -m pytest tests/ -n auto -q --cov=songmaker_cli --cov=audio_engine --cov=acestep_engine

# Push and merge:
git push -u origin refactor/no-silent-fallbacks
# Open a PR or fast-forward merge — match the user's preference (last time it was ff merge).

# Redeploy (no migrations expected unless W2 added one for the migration script):
timeout 300 docker compose up -d --build --wait
docker compose logs migrate | tail -20  # confirm clean
```

### Important context on what changed in the quick-wins PR (commits 5655163..be046a9)

The 6 commits ahead of the original audit's reference point made these changes that affect this plan:

- **B5 (`refactor(workers): introduce WorkerBase class`)** — `worker_base.py` is now a real class. Module-level globals `_db_factory`, `_db_engine`, `_db_lock`, `JOB_TIMEOUT_SECONDS`, `DRAIN_TIMEOUT_SECONDS`, `_audio_dir()`, `_data_dir()`, `_get_db_factory()`, `common_startup`, `common_shutdown`, `recover_on_startup`, `make_cleanup_cron`, and `audit_orphaned_files` are now methods on `WorkerBase`. `_IMPORT_TIME_REDIS_URL` in `music_worker.py` and `scoring_worker.py` is gone — the snapshot moved to `WorkerBase.__init__` as `self._import_time_redis_url`. **W1's injection point becomes `WorkerBase.__init__(settings: Settings)` instead of patching module globals.**

- **B10 (`fix(jobs): drop PID liveness fallback, make heartbeat_at NOT NULL`)** — `STALE_JOB_THRESHOLD_SECONDS` in `db/queries/jobs.py:135` still reads `os.environ.get(...)` at module load. Still in scope for W1.

- **B6** — `Generation.version_id` now has an index. Doesn't affect this plan.

- **B3** — `ScorerProcess._pipe_lock` now serializes scoring calls. Doesn't affect this plan; the `SCORING_MAX_JOBS` env var is still in scope for W1.

- **B11** — `plans/` was reorganized. References in this plan to other plans use the new paths.

- **`load_model_on_worker` and `download_model_on_worker` in `jobs.py`** now take `db_factory` as a keyword-only argument (the B5 refactor passed this through). When W1 adds `Settings`, both functions should also take `settings` as a kwarg, OR be wrapped on `MusicWorker` to access `self._settings`.

The audit file/line references in workstreams below may be off by a few lines after these commits. If a grep doesn't find what the plan claims is there, just re-grep for the symbol — the conceptual reference is what matters.

## Goal

Eliminate every silent fallback in `src/`. After this lands:

1. Every env var is read once, validated at startup, and accessed via a typed `Settings` object. No `os.environ.get()` outside `settings.py`.
2. Every domain dict (`generation_params`, `repaint_params`, `cover_params`, preset params, AceStep config) is a Pydantic model with explicit required fields. JSON columns validate on read and write.
3. Every internal function signature reflects what the boundary actually guarantees. No `Optional` types lying about non-null DB columns. No `dict | None` where a typed model belongs.
4. The 20 silent-fallback smell sites are either deleted (because Pydantic now makes them impossible), replaced with an explicit raise, or replaced with a named constant.
5. CI fails on new instances of the smell patterns.

## Non-goals

- Refactoring `jobs.py` into smaller modules (separate plan: `plans/jobs-module-split.md`)
- Renaming/redesigning the worker pool architecture
- Frontend type tightening (already CI-gated via `generate_types.py --check`)
- Test rewrites beyond what's needed to compile against the new types

## Decisions (locked in)

1. **Scope:** all of `src/` — `songmaker_cli`, `acestep_engine`, `audio_engine`, `acestep_worker`. Tests out of scope until end.
2. **Settings library:** `pydantic-settings.BaseSettings`.
3. **Strictness:** full strict. No half-cleanups.
4. **Worker `max_jobs`:** keep configurable via `Settings` (`MUSIC_MAX_JOBS=2`, `SCORING_MAX_JOBS=1` defaults preserved). Note: scoring-side Pipe race (review item B3) is a separate fix.
5. **Required-vs-default:** anything without a sensible production default is **required** (raises at startup if missing). Confirmed required: `SESSION_SECRET`, `DATABASE_URL`, `REDIS_URL`, `SONGMAKER_INTERNAL_TOKEN`, `WORKER_ID` (acestep workers only), and the Anthropic credential path actually in use.
6. **`StoredGenerationParams` strictness:** ACE-Step is the truth. See "AceStep truth" section below for the field-by-field split.
7. **PR shape:** one big branch (`refactor/no-silent-fallbacks`), 5 sequential commits matching the workstreams below. Single PR to main at the end.
8. **Test strategy:** during workstreams 1–4, mark broken tests `xfail` with a TODO referencing this plan. Workstream 5 is the test cleanup pass.
9. **Backwards compat:** one-shot migration script validates and reports/fixes every existing `Version.generation_params` and `Generation.generation_params` row. Runs as part of W2.

## AceStep truth (what's actually required)

From [src/acestep_engine/models.py:11-58](../src/acestep_engine/models.py#L11-L58), the `AceStepConfig` dataclass:

**Strictly required (no default):**
- `prompt: str`
- `lyrics: str`

**Has a default in AceStepConfig (named constant, fine to fall back to):**
- `bpm=120`, `audio_duration=60`, `key_scale=""`, `time_signature=""`, `vocal_language="en"`
- `seed=-1`, `inference_steps=8`, `guidance_scale=0.0`, `shift=3.0`, `thinking=True`
- `lm_temperature=0.85`, `lm_top_k=0`, `lm_top_p=0.9`, `lm_cfg_scale=2.0`, `lm_negative_prompt=""`
- `infer_method="ode"`, `batch_size=1`, `task_type="text2music"`, `model=""`
- `lm_repetition_penalty=1.0`, `use_cot_caption=True`, `use_cot_language=True`
- `constrained_decoding=False`, `use_adg=False`, `cfg_interval_start=0.0`, `cfg_interval_end=1.0`
- `timesteps=""`

**Conditionally required by task_type (must be set when task_type matches):**
- `task_type="repaint"` requires: `src_audio_path`, `repainting_start`, `repainting_end`, `repaint_mode`, `repaint_strength`
- `task_type="repaint"` optional: `repaint_latent_crossfade_frames`, `repaint_wav_crossfade_sec`
- `task_type="cover"` requires: `src_audio_path`, `audio_cover_strength`
- `task_type="cover"` optional: `cover_noise_strength`, `reference_audio_path`

This gives us a clean discriminated-union shape for the new Pydantic models.

## Pydantic model design

Replaces today's loose `StoredGenerationParams` (17 Optional fields, [api_models/songs.py:92-108](../src/songmaker_cli/api_models/songs.py#L92-L108)) and the dict-typed `repaint_params`/`cover_params` arq kwargs.

```python
# api_models/generation_params.py (new file)

class BaseGenerationParams(BaseModel):
    """Fields stored on Version.generation_params and Generation.generation_params.
    Mirrors AceStepConfig field-for-field for the non-task-conditional knobs.
    Required fields are AceStep-required. Everything else falls back to AceStepConfig
    defaults at build time — explicit, named, reviewable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Strictly required by AceStep
    prompt: str
    lyrics: str

    # Songmaker-required (we always know which model the user picked)
    model_mode: ModelMode

    # Optional knobs — None means "use AceStep default for this field"
    bpm: int | None = None
    audio_duration: int | None = None
    key_scale: str | None = None
    time_signature: str | None = None
    vocal_language: str | None = None
    inference_steps: int | None = None
    guidance_scale: float | None = None
    shift: float | None = None
    thinking: bool | None = None
    lm_temperature: float | None = None
    lm_top_k: int | None = None
    lm_top_p: float | None = None
    lm_cfg_scale: float | None = None
    lm_negative_prompt: str | None = None
    infer_method: Literal["ode", "sde"] | None = None
    lm_repetition_penalty: float | None = None
    use_cot_caption: bool | None = None
    use_cot_language: bool | None = None
    constrained_decoding: bool | None = None
    use_adg: bool | None = None
    cfg_interval_start: float | None = None
    cfg_interval_end: float | None = None
    timesteps: str | None = None


class Text2MusicParams(BaseGenerationParams):
    task_type: Literal["text2music"] = "text2music"


class RepaintParams(BaseGenerationParams):
    task_type: Literal["repaint"] = "repaint"
    src_generation_id: str  # Songmaker resolves to src_audio_path
    repainting_start: float
    repainting_end: float
    repaint_mode: Literal["conservative", "balanced", "aggressive"]
    repaint_strength: float
    repaint_latent_crossfade_frames: int | None = None
    repaint_wav_crossfade_sec: float | None = None


class CoverParams(BaseGenerationParams):
    task_type: Literal["cover"] = "cover"
    src_generation_id: str
    audio_cover_strength: float
    cover_noise_strength: float | None = None


GenerationParamsRequest = Annotated[
    Text2MusicParams | RepaintParams | CoverParams,
    Field(discriminator="task_type"),
]
```

**Why this shape:**
- `Optional[X] = None` on the knobs means "user didn't specify, use AceStep default at build time." The default is the named constant in `AceStepConfig`, not a runtime fallback. Visible in code review.
- `extra="forbid"` means a typo'd key fails immediately instead of being silently dropped. This alone would have caught 2026-04-08.
- `frozen=True` prevents in-place mutation across the merge layers.
- Discriminator on `task_type` makes "repaint without `repainting_start`" a 422 at the API boundary, not a runtime error in the worker.
- `Literal["ode", "sde"]`, `Literal["conservative", ...]` move the validators in `_sanitize_params` (config.py:203) into the type system.

`build_ace_config()` becomes:

```python
def build_ace_config(
    params: GenerationParamsRequest,
    *,
    seed: int | None = None,
    user_defaults: BaseGenerationParams | None = None,
    preset: BaseGenerationParams | None = None,
) -> AceStepConfig:
    """Resolve a typed params object → AceStepConfig.
    Layering: params > preset > user_defaults > model_mode defaults > AceStepConfig defaults.
    Each layer is a typed object; the merge is field-by-field with explicit fallback rules."""
```

No more `dict.update()`. No more `cli_overrides`. The CLI builds a `BaseGenerationParams` and passes it through the same path.

## Workstream 1 — Settings consolidation

**Goal:** Every env read happens once, in `settings.py`, validated by Pydantic. The 33 import-time reads stop existing.

**New file:** `src/songmaker_cli/settings.py`

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".server.env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    # Required (no defaults — startup fails if missing)
    database_url: str
    redis_url: str
    session_secret: SecretStr
    songmaker_internal_token: SecretStr

    # Required for acestep workers only (separate WorkerSettings subclass)
    # worker_id, acestep_inner_port, vram_budget_gb, etc.

    # Operational defaults — named, reviewable
    request_timeout_seconds: int = 30
    arq_job_timeout: int = 900
    arq_drain_timeout: int = 300
    music_max_jobs: int = 2
    scoring_max_jobs: int = 1
    database_pool_size: int = 5
    database_max_overflow: int = 10
    stale_job_threshold_seconds: int = 360

    # Auth & rate limit defaults
    session_max_age_seconds: int = 60 * 60 * 24 * 30
    session_absolute_max_age_seconds: int = 60 * 60 * 24 * 90
    login_rate_limit: int = 5
    generation_rate_limit_user: int = 3
    generation_rate_limit_admin: int = 30
    scoring_rate_limit_user: int = 10
    scoring_rate_limit_admin: int = 100
    chat_rate_limit_user: int = 30
    chat_rate_limit_admin: int = 300
    max_queue_depth: int = 100
    max_user_active_jobs: int = 10
    login_lockout_threshold: int = 15
    login_lockout_window_seconds: int = 3600
    ip_rate_limit: int = 120
    max_request_body_bytes: int = 1_048_576
    max_upload_body_bytes: int = 52_428_800
    soft_delete_retention_days: int = 30
    log_format: Literal["text", "json"] = "text"

    # ACE-Step
    acestep_startup_timeout_seconds: int = 300
    acestep_shutdown_grace_seconds: int = 15
    acestep_shutdown_kill_seconds: int = 5
    acestep_health_poll_seconds: float = 2.0
    acestep_poll_timeout: float = 600.0

    # Claude
    claude_chat_model: str = "claude-opus-4-6"
    claude_scoring_model: str = "claude-opus-4-6"
    anthropic_api_key: SecretStr | None = None  # CLI mode allowed if None

    # Optional infra
    cors_origin: str | None = None
    allowed_hosts: str = ""
    trusted_proxies: str = ""
    admin_username: str | None = None  # auto-setup hook
    admin_password: SecretStr | None = None
    hf_token: SecretStr | None = None
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

A separate `WorkerSettings(Settings)` adds the acestep-worker-only fields (`worker_id`, `acestep_inner_port`, `vram_budget_gb`, `acestep_checkpoint_dir`, `audio_output_dir`, `acestep_log_dir`, `gpu_id`, `control_plane_url`).

**Files modified (delete env reads, replace with `get_settings().foo`):**

| File | Reads to delete |
|---|---|
| [constants.py](../src/songmaker_cli/constants.py#L29-L67) | `RESTORE_WINDOW`, `CLAUDE_CHAT_MODEL`, `CLAUDE_SCORING_MODEL` (the documented footguns) |
| [auth.py](../src/songmaker_cli/auth.py#L18-L57) | All 16 rate-limit / session / lockout constants + `TRUSTED_PROXIES` parser |
| [worker_base.py](../src/songmaker_cli/worker_base.py) | Module-level: `JOB_TIMEOUT_SECONDS`, `DRAIN_TIMEOUT_SECONDS`, `build_redis_settings`. Inside `WorkerBase`: `self._import_time_redis_url` (snapshot in `__init__`), `audio_dir()` reading `AUDIO_DIR`, `data_dir()` reading `DATA_DIR`, `on_startup()` reading `REDIS_URL` for the mismatch warning. **Inject `Settings` into `WorkerBase.__init__` and access via `self._settings`.** |
| [music_worker.py](../src/songmaker_cli/music_worker.py) | `MusicWorker.max_jobs = int(os.environ.get("MUSIC_MAX_JOBS", "2"))` at class definition. Move this to read from `settings.music_max_jobs` after instantiation, OR (cleaner) make `max_jobs` a `ClassVar[int]` set lazily in `MusicWorkerSettings` after `get_settings()` resolves. |
| [scoring_worker.py](../src/songmaker_cli/scoring_worker.py) | `ScoringWorker.max_jobs` (same pattern as music). Plus `device = os.environ.get("SCORING_DEVICE", _SCORING_DEVICE_DEFAULT)` inside `ScoringWorker.score()` — move to `settings.scoring_device`. |
| [server.py](../src/songmaker_cli/server.py#L42-L267) | `REQUEST_TIMEOUT_SECONDS`, `ALLOWED_HOSTS`, `redis_url`, `CORS_ORIGIN`, `HOST` |
| [logging_config.py](../src/songmaker_cli/logging_config.py#L17) | `LOG_FORMAT` |
| [middleware/rate_limit.py](../src/songmaker_cli/middleware/rate_limit.py#L16) | `IP_RATE_LIMIT` |
| [middleware/body_size.py](../src/songmaker_cli/middleware/body_size.py#L9-L10) | `MAX_REQUEST_BODY_BYTES`, `MAX_UPLOAD_BODY_BYTES` |
| [db/engine.py](../src/songmaker_cli/db/engine.py#L29-L68) | `DATABASE_URL`, `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW` |
| [db/queries/jobs.py](../src/songmaker_cli/db/queries/jobs.py#L135-L136) | `STALE_JOB_THRESHOLD_SECONDS` |
| [internal_api.py](../src/songmaker_cli/internal_api.py#L30) | `verify_internal_token` |
| [admin_api.py](../src/songmaker_cli/admin_api.py#L340) | `_post_to_worker` token |
| [chat_api.py](../src/songmaker_cli/chat_api.py#L66-L228) | `env_key`, `api_key` |
| [lifecycle.py](../src/songmaker_cli/lifecycle.py#L18-L19) | `ADMIN_USERNAME`, `ADMIN_PASSWORD` |
| [scheduler.py](../src/songmaker_cli/scheduler.py#L153) | `_internal_headers` token |
| [arq_pool.py](../src/songmaker_cli/arq_pool.py#L30) | `init_arq_pool` redis_url |
| [acestep_worker/__main__.py](../src/acestep_worker/__main__.py#L39-L120) | All 13 reads → `WorkerSettings` |
| [acestep_worker/subprocess_runner.py](../src/acestep_worker/subprocess_runner.py#L21-L24) | All 4 timeout constants |
| [acestep_worker/downloads.py](../src/acestep_worker/downloads.py#L62) | `HF_TOKEN` |
| [acestep_engine/client.py](../src/acestep_engine/client.py#L55-L70) | `ACESTEP_POLL_TIMEOUT`, `_default_host`, `_default_port` |
| [scoring/lyrical_coherence.py](../src/songmaker_cli/scoring/lyrical_coherence.py#L97) | `api_key` |
| [scoring/audiobox_aesthetics.py](../src/songmaker_cli/scoring/audiobox_aesthetics.py#L59-L60) | `CUDA_VISIBLE_DEVICES` (this one stays — it's a deliberate temporary mutation, but moves behind a `settings.scoring_force_cpu` flag) |
| [config.py](../src/songmaker_cli/config.py#L25-L33) | `load_env_file` is gone; `Settings` loads `.server.env` automatically |

**Acceptance:**
- `grep -rn "os.environ" src/` returns only `settings.py`, the audiobox CUDA mutation, and any `os.environ.copy()` for subprocess env-scrubbing.
- `grep -rn "os.getenv" src/` returns nothing.
- Startup with a missing required env var raises a clear `ValidationError` listing which fields are missing.
- `Settings` is constructible in tests via `Settings(database_url=..., redis_url=..., ...)` without monkey-patching `os.environ`.

**Special handling for arq's class-level attributes (the load-bearing fix):**

arq inspects `MusicWorkerSettings.redis_settings`, `MusicWorkerSettings.max_jobs`, `MusicWorkerSettings.queue_name` at class definition time. These cannot be `None`-then-set-later — arq needs them resolved before its event loop starts.

Today (after B5):
```python
class MusicWorkerSettings:
    redis_settings = build_redis_settings()  # reads REDIS_URL at module import
    max_jobs = MusicWorker.max_jobs           # reads MUSIC_MAX_JOBS at class def of MusicWorker
```

After W1, the load-bearing pattern is to resolve `Settings()` ONCE at module import time, before defining the class:

```python
# music_worker.py
from songmaker_cli.settings import get_settings

_settings = get_settings()  # one-shot, lru_cached. .server.env loaded by BaseSettings.
_music_worker = MusicWorker(_settings)

class MusicWorkerSettings:
    functions = [_music_worker.generate, ...]
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    max_jobs = _settings.music_max_jobs
    queue_name = MusicWorker.queue_name
    ...
```

This works because `BaseSettings` reads `.server.env` during `Settings()` construction, which happens at the first call to `get_settings()` — and that first call is now at import time of `music_worker.py`, before arq inspects the class. The `lru_cache` on `get_settings()` ensures the same instance is used everywhere afterwards.

The CLAUDE.md "Known Technical Debt" entry about `WorkerSettings.redis_settings` resolving at import time is then resolvable via documentation: yes, it still resolves at import time, but now from a validated `Settings` object whose `.server.env` is loaded automatically by Pydantic. The old footgun (`os.environ.get("REDIS_URL", "redis://localhost:6379/0")` returning the fallback if `.server.env` hadn't been processed yet) is gone because `Settings()` reads `.server.env` itself.

**Engine package isolation (Risk 4):** `acestep_engine/client.py` cannot import from `songmaker_cli.settings` without breaking the one-way dependency rule. Create `src/acestep_engine/settings.py` with a minimal `EngineSettings(BaseSettings)` containing only `acestep_poll_timeout`, `default_host`, `default_port`. The engine package owns its own settings.

## Workstream 2 — Pydantic for `generation_params` (the 2026-04-08 surface)

**Goal:** Every place that touches a generation params dict becomes typed. JSON columns validate on read and write. The four HIGH-severity dict-as-domain findings collapse here.

**Changes:**

1. **New file** `src/songmaker_cli/api_models/generation_params.py` with the `BaseGenerationParams` / `Text2MusicParams` / `RepaintParams` / `CoverParams` shapes from the design section above.

2. **DB validators** on `Version.generation_params` and `Generation.generation_params` ([db/models.py:116, :141](../src/songmaker_cli/db/models.py#L116)):
   - SQLAlchemy `validates` decorator that runs `BaseGenerationParams.model_validate(value)` on assignment and stores `.model_dump(mode="json")`.
   - Read path: `db/queries/songs.py` and `db/queries/generations.py` return `BaseGenerationParams`, not `dict`.

3. **Rewrite `build_ace_config`** ([config.py:166](../src/songmaker_cli/config.py#L166)) to take the typed object instead of `meta: SongMeta` + `cli_overrides: dict`. Layering becomes field-by-field with explicit `... if x is not None else ...` rules. The `_sanitize_params` validators ([config.py:203](../src/songmaker_cli/config.py#L203)) become Pydantic field validators on `BaseGenerationParams`.

4. **Replace `repaint_params` / `cover_params` arq dicts:**
   - [generation_api.py:330-345, 405-413](../src/songmaker_cli/generation_api.py#L330): construct `RepaintParams` / `CoverParams` instead of dicts. Pass through arq as `params.model_dump(mode="json")`.
   - [music_worker.py:45-46](../src/songmaker_cli/music_worker.py#L45): rehydrate via `RepaintParams.model_validate(payload)` at the worker entrypoint.
   - [jobs.py:523-528](../src/songmaker_cli/jobs.py#L523) `_apply_task_overrides`: deleted. Replaced by typed merge in `build_ace_config`.

5. **Replace `_load_preset_params`** ([jobs.py:139-160](../src/songmaker_cli/jobs.py#L139)) returning `dict | None` → returns `BaseGenerationParams | None`.

6. **Claude chat messages** ([chat_api.py:215-225](../src/songmaker_cli/chat_api.py#L215), [claude/provider.py:104-107](../src/songmaker_cli/claude/provider.py#L104)): `list[dict[str, str]]` → `list[ChatMessage]` Pydantic model with `role: Literal["user", "assistant", "system"]` and `content: str`. New file `api_models/chat.py`.

7. **`Score.value` JSON column** ([db/models.py:205](../src/songmaker_cli/db/models.py#L205)): each scorer already has a typed result class in `scoring/models.py`. The DB validator dispatches on the `name` column to validate the JSON against the right scorer model.

8. **`Album.colors`** ([db/models.py:65](../src/songmaker_cli/db/models.py#L65)): tiny `AlbumColors(BaseModel)` with named hex fields. JSON column gets a validator.

9. **`GenerationPreset.params`** ([db/models.py:236](../src/songmaker_cli/db/models.py#L236)): stores `BaseGenerationParams.model_dump()`. Validator on assignment.

10. **`User.default_generation_config`** ([db/models.py](../src/songmaker_cli/db/models.py)): same — typed via `BaseGenerationParams`.

**Migration script:** `scripts/migrate_generation_params.py`

```python
"""Validate every Version.generation_params and Generation.generation_params row.

For each row:
- Try BaseGenerationParams.model_validate(row.generation_params)
- If valid: write back the canonical dump (normalizes key order, drops unknowns)
- If invalid: log row id + the validation error to a report file
- With --fix: drop unknown keys, fill missing required from latest version, re-validate
- With --dry-run (default): only report

Run order:
1. ./scripts/migrate_generation_params.py --dry-run > /tmp/report.txt
2. Human reviews the report — this is where 2026-04-08 leftover corruption surfaces
3. ./scripts/migrate_generation_params.py --fix
4. Re-run --dry-run; should report zero issues
"""
```

The script also covers `GenerationPreset.params`, `User.default_generation_config`, `Album.colors`, and `Score.value`. Same dry-run/fix pattern.

**Acceptance:**
- All four HIGH dict-as-domain findings from the audit are gone.
- `grep -rn "generation_params\.get(" src/` returns nothing.
- `grep -rn "generation_params\[" src/` returns nothing.
- Round-trip test: write a `Text2MusicParams`, store, reload, assert equality.
- Migration script runs clean against the dev DB.
- An invalid params dict at the API boundary returns 422 with the offending field name.

## Workstream 3 — Kill the silent-fallback smell sites

**Goal:** Walk the 20 audit findings (10 HIGH, 7 MEDIUM, 3 LOW) and apply one of: delete, raise, or named-constant.

**HIGH (10):**

| File:Line | Today | Fix |
|---|---|---|
| [config.py:180-181](../src/songmaker_cli/config.py#L180) `(global_defaults or {}).get(...)`, `preset_params or {}` | dict-fallback chain | **Deleted** by W2 — `build_ace_config` now takes typed objects, no dict fallback possible |
| [jobs.py:151,159](../src/songmaker_cli/jobs.py#L151) `_load_preset_params` returning None | silent | **Deleted** by W2 — returns `BaseGenerationParams \| None`, callers handle explicitly |
| [jobs.py:300](../src/songmaker_cli/jobs.py#L300) `meta.generation_params.get("key_scale", "")` | empty-string fallback | **Deleted** by W2 — becomes `meta.generation_params.key_scale or ""` with the `or ""` made explicit and named via constant `KEY_SCALE_UNSET = ""` if it must stay |
| [scheduling.py:298,329](../src/songmaker_cli/scheduling.py#L298) `data.get("result") or {}` | masks worker errors | **Raise** — if `result` is missing/null, the worker contract is broken; raise `WorkerProtocolError` |
| [scheduling.py:306,337](../src/songmaker_cli/scheduling.py#L306) `data.get("error") or "worker error"` | masks real errors | **Raise** the actual missing-error case; if `error` field is empty string, log and propagate empty (don't substitute generic) |
| [db/queries/playlists.py:78](../src/songmaker_cli/db/queries/playlists.py#L78) `(max_pos[0] + 1) if max_pos else 0` | iteration-order risk | **Named constant** — `INITIAL_PLAYLIST_POSITION: Final = 0`, comment explaining the empty-playlist case |
| [db/queries/songs.py:123](../src/songmaker_cli/db/queries/songs.py#L123) track_number init | same pattern | **Named constant** — `INITIAL_TRACK_NUMBER: Final = 1` |
| [db/queries/generations.py:54](../src/songmaker_cli/db/queries/generations.py#L54) gen_number init | same pattern | **Named constant** — `INITIAL_GENERATION_NUMBER: Final = 1` |
| [api_helpers.py:142](../src/songmaker_cli/api_helpers.py#L142) `_ENV_RATE_LIMITS.get(job_type, (10, 100, ""))` | hardcoded fallback for unknown job type | **Raise** `ValueError(f"unknown job_type: {job_type}")` — new job types must be added explicitly |
| [settings_api.py:182](../src/songmaker_cli/settings_api.py#L182) `get_builtin_defaults().get(model.id, {})` | empty fallback | **Raise** — if a model has no defaults, that's a registration bug; raise `ConfigError` |
| [scoring/bpm_accuracy.py:54](../src/songmaker_cli/scoring/bpm_accuracy.py#L54) `meta.generation_params.get("bpm")` | None on missing | **Deleted** by W2 — becomes `meta.generation_params.bpm` (typed `int \| None`); the `None` here is explicit, not silent |
| [scoring/text_accuracy.py:49](../src/songmaker_cli/scoring/text_accuracy.py#L49) `vocal_language or None` | silent auto-detect | **Deleted** by W2 — typed `vocal_language: str \| None`; if None, log "auto-detecting language for generation X" so the choice is loud |

**MEDIUM (7):**

| File:Line | Fix |
|---|---|
| [api_models/songs.py:130](../src/songmaker_cli/api_models/songs.py#L130) `colors=album.colors or {}` | Deleted by W2 (typed `AlbumColors`) |
| [api_models/settings.py:65](../src/songmaker_cli/api_models/settings.py#L65) `params=preset.params or {}` | Deleted by W2 (typed preset params) |
| [api_models/playlists.py:55](../src/songmaker_cli/api_models/playlists.py#L55) `(playlist.entries or [])` | DB relationship default — keep but make explicit: if `entries` is None at this point it's an ORM bug, log a warning |
| [health_api.py:135,145](../src/songmaker_cli/health_api.py#L135) `loaded_counts or {}`, `queue_depths or {}` | Worker metrics — these can legitimately be missing (worker offline). Replace with `WorkerMetrics(BaseModel)` with `Field(default_factory=dict)` and document |
| Inconsistent timestamp Optionals in `api_models/auth.py:56,83-84,106,126`, `api_models/settings.py:56-57`, `api_models/songs.py:286-288` | **W4 territory** — covered there |

**LOW (3):** [admin_api.py:331-332](../src/songmaker_cli/admin_api.py#L331), [scoring/lyrical_coherence.py:103-105](../src/songmaker_cli/scoring/lyrical_coherence.py#L103), [middleware/csrf.py:87](../src/songmaker_cli/middleware/csrf.py#L87) — defensive guards on optional external data. **Keep as-is** but each gets a comment explaining why the fallback is correct (the rule is "no silent fallbacks", not "no fallbacks at all" — these are explicit, named, and on cosmetic/optional fields).

**Acceptance:**
- The CI grep checks from W5 pass.
- A unit test for each "raise" path verifies it actually raises with a useful message.

## Workstream 4 — Tighten Optional types

**Goal:** Interior types stop lying about what the boundary guarantees. Mypy/pyright catches the next class of bug.

**Changes:**

1. **Timestamp fields** ([api_models/auth.py:56,83-84,106,126](../src/songmaker_cli/api_models/auth.py#L56), [api_models/settings.py:56-57](../src/songmaker_cli/api_models/settings.py#L56)): every `created_at`, `updated_at`, `attempted_at` whose underlying DB column has `default=_utcnow` becomes `str` (no Optional). The corresponding `from_orm` methods drop the `if x else None` branches.

2. **`_best_generation` return type** ([api_models/songs.py:351](../src/songmaker_cli/api_models/songs.py#L351)): `object | None` → `Generation | None`.

3. **`run_generation_job` parameters** ([jobs.py:482-498](../src/songmaker_cli/jobs.py#L482)): `db_factory: sessionmaker | None = None` (with runtime assertions) → required parameters. Same for `audio_dir`, `data_dir`, `redis`. Callers in `music_worker.py` pass them explicitly (they have them).

4. **`gen_params_to_dict` parameter** ([api_helpers.py:158](../src/songmaker_cli/api_helpers.py#L158)): `object | None` → `BaseGenerationParams | None`. Function name becomes `gen_params_to_json` for clarity since it's a serializer.

5. **`SongSummaryResponse` mixed defaults** ([api_models/songs.py:286-288](../src/songmaker_cli/api_models/songs.py#L286)): pick one rule — **None means missing, empty string is a valid value**. `bpm: int | None`, `audio_duration: int | None`, `key_scale: str | None`. Frontend handles None as "—" in display.

6. **`StoredGenerationParams`** ([api_models/songs.py:92-108](../src/songmaker_cli/api_models/songs.py#L92)): deleted, replaced by `BaseGenerationParams` from W2.

7. **API request `GenerationParams`** ([api_models/songs.py:44-63](../src/songmaker_cli/api_models/songs.py#L44)): replaced by `Text2MusicParams` / `RepaintParams` / `CoverParams` from W2. The 12 Optional knob fields stay Optional (None = use default) but are now backed by the discriminated union and `extra="forbid"`.

**Acceptance:**
- `mypy src/` (or `pyright src/`) passes with no `Optional`-related errors that the old types were hiding.
- `from_orm` methods have no `if x else None` branches on DB-default columns.
- The smell-pattern grep from W5 catches no new instances.

## Workstream 5 — Tests + CI enforcement

**Goal:** Tests pass against the new types. CI fails the build on new instances of the smell patterns.

**Test fixes:**
- Walk every `xfail` mark added during W1–W4. For each, fix the test to construct typed objects instead of dicts and pass `Settings(...)` instead of monkey-patching `os.environ`.
- New helper in `tests/conftest.py`: `def make_settings(**overrides) -> Settings` that constructs a `Settings` object with sensible test defaults (sqlite URL, fakeredis URL, dummy secrets).
- Round-trip tests for the migration script: seed a DB with corrupt rows, run `--fix`, assert clean.
- Property test for `BaseGenerationParams`: hypothesis-generate dicts, assert that `model_validate` either succeeds or raises `ValidationError` (never silent corruption).
- Negative test for each W3 "raise" path.

**CI checks:** new file `scripts/check_no_silent_fallbacks.py`, called from `.github/workflows/ci.yml`:

```python
"""Fail CI on silent-fallback smell patterns in src/.

Each rule is a regex with a list of allowlisted file:line locations
(for the few legitimate cases). Adding a new instance requires either
fixing the code or explicitly allowlisting with a justification comment.
"""

RULES = [
    Rule(
        name="env-read-outside-settings",
        pattern=r"os\.(environ\.get|environ\[|getenv)\(",
        allowlist={"src/songmaker_cli/settings.py", "src/songmaker_cli/scoring/audiobox_aesthetics.py:60"},
    ),
    Rule(
        name="next-iter-fallback",
        pattern=r"next\(iter\(",
        allowlist=set(),
    ),
    Rule(
        name="dict-get-domain-fallback",
        # .get(key, <literal>) on variables named like config/params/state/defaults.
        # Matches when the second arg starts with a string quote, list/dict literal,
        # or a digit — i.e. a literal default, not a sentinel like None.
        pattern=r"(config|params|state|defaults|settings)\.get\([^,)]+,\s*([\"'\[{]|\d)",
        allowlist=set(),
    ),
    Rule(
        name="dict-any-in-signature",
        # dict[str, Any] / Dict[str, Any] in function defs (excluding **kwargs)
        pattern=r"def\s+\w+\([^)]*:\s*(dict|Dict)\[str,\s*Any\]",
        allowlist=set(),
    ),
    Rule(
        name="optional-on-default-utcnow-column",
        # Specific timestamp field names with Optional type
        pattern=r"(created_at|updated_at|attempted_at):\s*(str|datetime)\s*\|\s*None",
        allowlist=set(),
    ),
]
```

CI invocation: `python scripts/check_no_silent_fallbacks.py src/`. Exit nonzero on any unallowlisted match.

**Acceptance:**
- Full test suite green (`pytest tests/ -n auto`).
- 100% coverage on `settings.py`, `api_models/generation_params.py`, the migration script, and the smell-checker.
- CI workflow runs the smell checker; intentionally adding `os.environ.get(...)` to a non-allowlisted file fails the build in a test PR.

## Sequencing within the branch

One branch `refactor/no-silent-fallbacks`, five commits:

1. **`feat: introduce Settings(BaseSettings) and migrate env reads`** — W1 in full. All tests not directly affected stay green; affected ones get `xfail` marks.
2. **`refactor: Pydantic models for generation_params + migration script`** — W2 in full. Run migration on dev DB. More `xfail` marks on params-touching tests.
3. **`refactor: kill silent-fallback smell sites`** — W3 in full.
4. **`refactor: tighten Optional types in interior signatures`** — W4 in full. Mypy/pyright passes.
5. **`test: fix tests for typed config + add CI smell checker`** — W5. All `xfail` marks removed. CI gate added. Coverage back to target.

Each commit individually compiles and passes type checks. Tests are amber on commits 1–4 (only the explicitly `xfail`-marked ones), green on commit 5.

PR description references this plan and the 2026-04-08 incident.

## Out of scope / explicitly deferred

- **`jobs.py` split** — `plans/jobs-module-split.md` is the right place; this cleanup will make it easier.
- **B3 scorer subprocess Pipe race** — the `SCORING_MAX_JOBS=1` default keeps it safe; defer to a separate fix.
- **`worker_base.py` rename** — cosmetic, not a correctness issue.
- **Frontend `types.ts` changes** — `generate_types.py` will pick up the new Pydantic models automatically; if any frontend code breaks, fix in this same branch but track separately in the PR description.
- **B8 stuck-`QUEUED` recovery** — separate plan; needs a product call on user messaging.
- **B9 backpressure UI** — product call.

## Risks

1. **Migration script finds more 2026-04-08 corruption.** Likely. The dry-run pass exists for exactly this. If serious corruption is found, decide row-by-row before `--fix`.
2. **`extra="forbid"` on `BaseGenerationParams` rejects fields the frontend silently sends today.** Smoke-test the full generate→repaint→cover→preset flow against a dev frontend before merging. The CI `types.ts` check helps but doesn't catch runtime-only field-name drift.
3. **Test churn.** Every test that monkey-patches `os.environ` or constructs a `dict` for generation params needs updating. Estimated >20 tests. The `xfail`-then-fix-at-end strategy contains the blast radius but commit 5 will be the largest commit.
4. **`acestep_engine.client._default_host` / `_default_port`** are read at runtime by the engine package. If we move them into `WorkerSettings`, the engine package starts depending on `songmaker_cli.settings` — violating the engine isolation rule. **Fix:** the engine package gets its own minimal `EngineSettings(BaseSettings)` in `acestep_engine/settings.py`. Engine isolation preserved.
5. **`Settings` is constructed at module import in some places** (the worker `WorkerSettings` arq class is the load-bearing one). The `lru_cache get_settings()` pattern handles this — first call constructs, all subsequent calls share. Workers must call `get_settings()` once at startup before any code that depends on it runs.

## Completion criteria

This plan is done when:

1. `grep -rn "os.environ\|os.getenv" src/ | grep -v settings.py | grep -v audiobox_aesthetics` is empty.
2. `grep -rn "next(iter(" src/` is empty.
3. The 4 HIGH dict-as-domain findings from the audit are gone (verified by re-running the audit).
4. The 10 HIGH silent-fallback findings are gone or replaced with named raises.
5. `python scripts/check_no_silent_fallbacks.py src/` exits 0.
6. `pytest tests/ -n auto -q --cov=songmaker_cli --cov=audio_engine --cov=acestep_engine` passes with target coverage.
7. `python scripts/migrate_generation_params.py --dry-run` reports zero issues against a freshly-migrated dev DB.
8. The CLAUDE.md "Known Technical Debt" entries for `WorkerSettings.redis_settings`, `CLAUDE_CHAT_MODEL`, and `CLAUDE_SCORING_MODEL` are deleted (or rewritten to say "now resolved via `Settings(BaseSettings)`, see settings.py").

## Verification appendix — concrete commands

Copy-paste these to verify each workstream as you go.

### After W1 (Settings consolidation)

```bash
# 1. Settings file exists and is the only place env is read
test -f src/songmaker_cli/settings.py && echo OK
test -f src/acestep_engine/settings.py && echo OK  # engine isolation

# 2. No env reads outside settings files (should print only settings.py + audiobox CUDA mutation)
grep -rn "os\.environ\|os\.getenv" src/ | grep -v __pycache__ | grep -v "settings\.py" | grep -v "audiobox_aesthetics.py:60"
# Expected: empty output (or very small allowlist)

# 3. Settings is constructible in tests with explicit kwargs
.venv/bin/python -c "
from songmaker_cli.settings import Settings
s = Settings(database_url='sqlite:///:memory:', redis_url='redis://localhost:6379/0', session_secret='x'*64, songmaker_internal_token='t')
print(s.music_max_jobs, s.scoring_max_jobs)
"

# 4. Required fields raise on missing
.venv/bin/python -c "
from songmaker_cli.settings import Settings
import os
for k in ('DATABASE_URL', 'REDIS_URL', 'SESSION_SECRET', 'SONGMAKER_INTERNAL_TOKEN'):
    os.environ.pop(k, None)
try:
    Settings()
    print('FAIL: should have raised')
except Exception as e:
    print('OK:', type(e).__name__)
"

# 5. arq workers still start
docker compose up -d --build --wait
docker compose logs songmaker-music-worker | tail -5  # should show "generate worker ready"
docker compose logs songmaker-scoring-worker | tail -5 # should show "score worker ready"

# 6. CLAUDE.md technical-debt entries are gone (or rewritten)
grep -n "resolved at import time\|REDIS_URL" CLAUDE.md
```

### After W2 (Pydantic for generation_params)

```bash
# 1. New file exists
test -f src/songmaker_cli/api_models/generation_params.py && echo OK

# 2. No more dict-style access on generation_params
grep -rn "generation_params\.get\|generation_params\[" src/ | grep -v __pycache__
# Expected: empty

# 3. Round-trip test passes
.venv/bin/python -c "
from songmaker_cli.api_models.generation_params import Text2MusicParams
p = Text2MusicParams(prompt='test', lyrics='test', model_mode='turbo')
data = p.model_dump(mode='json')
p2 = Text2MusicParams.model_validate(data)
assert p == p2
print('OK')
"

# 4. Unknown key rejected (extra='forbid')
.venv/bin/python -c "
from songmaker_cli.api_models.generation_params import Text2MusicParams
try:
    Text2MusicParams(prompt='x', lyrics='y', model_mode='turbo', typo_field=42)
    print('FAIL: should have rejected typo_field')
except Exception as e:
    print('OK:', type(e).__name__)
"

# 5. Migration script exists and dry-runs clean against dev DB
test -f scripts/migrate_generation_params.py && echo OK
.venv/bin/python scripts/migrate_generation_params.py --dry-run
# Review output for any rows flagged as invalid before running --fix
```

### After W3 (smell sites)

```bash
# 1. No next(iter(...)) anywhere
grep -rn "next(iter(" src/ | grep -v __pycache__
# Expected: empty

# 2. The 10 HIGH findings are gone (re-grep each one)
grep -n "preset_params or {}\|global_defaults or {}" src/songmaker_cli/config.py
grep -n 'data\.get("result") or' src/songmaker_cli/scheduling.py
grep -n 'data\.get("error") or' src/songmaker_cli/scheduling.py
grep -n '_ENV_RATE_LIMITS\.get' src/songmaker_cli/api_helpers.py
grep -n 'get_builtin_defaults\(\)\.get' src/songmaker_cli/settings_api.py
# Expected: all empty (or matched by the W3 fix patterns)

# 3. Named constants exist for the legitimate fallbacks
grep -n "INITIAL_PLAYLIST_POSITION\|INITIAL_TRACK_NUMBER\|INITIAL_GENERATION_NUMBER" src/songmaker_cli/db/queries/
```

### After W4 (Optional tightening)

```bash
# 1. Type checker passes
.venv/bin/mypy src/  # or pyright if you prefer

# 2. Timestamp Optionals on default=_utcnow columns are gone
grep -n "created_at.*Optional\|created_at.*| None\|updated_at.*Optional\|updated_at.*| None" src/songmaker_cli/api_models/
# Expected: empty for the columns we tightened

# 3. _best_generation has the right type
grep -A 1 "_best_generation" src/songmaker_cli/api_models/songs.py
# Expected: returns Generation | None, not object | None

# 4. run_generation_job parameters are required
grep -A 5 "def run_generation_job" src/songmaker_cli/jobs.py
# Expected: no `= None` on db_factory, audio_dir, data_dir, redis
```

### After W5 (tests + CI)

```bash
# 1. Smell checker exists and passes against current src/
test -f scripts/check_no_silent_fallbacks.py && echo OK
.venv/bin/python scripts/check_no_silent_fallbacks.py src/
# Expected: exit 0

# 2. Smell checker actually catches a smell when injected
echo 'foo = os.environ.get("HACK", "default")' >> src/songmaker_cli/api_helpers.py
.venv/bin/python scripts/check_no_silent_fallbacks.py src/ && echo "FAIL: should have caught the new env read"
git checkout src/songmaker_cli/api_helpers.py

# 3. Full test suite green
.venv/bin/python -m pytest tests/ -n auto -q --cov=songmaker_cli --cov=audio_engine --cov=acestep_engine

# 4. CI config calls the smell checker
grep -n "check_no_silent_fallbacks" .github/workflows/ci.yml
```

### Deploy after merge

```bash
# Backup first if W2 added a migration:
BACKUP_DIR=/home/felix-hummert/backups/songmaker ./scripts/backup.sh

# Merge to main (user prefers fast-forward):
git checkout main && git merge --ff-only refactor/no-silent-fallbacks && git push origin main

# Redeploy (auto-runs alembic via the migrate service):
timeout 300 docker compose up -d --build --wait

# Verify migrations applied (if any new ones):
docker compose logs migrate | tail -20
docker compose exec -T postgres psql -U songmaker -d songmaker -c "SELECT version_num FROM alembic_version;"

# Smoke test: generate a song end-to-end
# (manual via the web UI or CLI)
```

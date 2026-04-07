# Phase 8 Sub-plan — Bake the inner ACE-Step venv into the image, narrow the bind mount

> Concrete implementation plan for [Phase 8 of acestep-worker-pool.md](acestep-worker-pool.md#phase-8--image-architecture-refactor-bake-the-inner-ace-step-venv-narrow-the-bind-mount). Read end-to-end before starting; the parent section locks the eight high-level decisions but leaves the **chosen option (A vs B vs C)** and the **exact diff** to this sub-plan. This sub-plan picks **Option B** with rationale, lays out the full Dockerfile / compose / `subprocess_runner.py` / `pyproject.toml` / `.env` changes, and defines the smoke test that is the deliverable for this phase.

## READ THIS FIRST — discrepancies vs. parent plan section

I verified every claim in the Phase 8 section of [acestep-worker-pool.md](acestep-worker-pool.md) against the code on disk at commit `2f33400`. The parent section is **factually correct on the verified mechanism** (wrapper venv at `/app/.venv` baked, inner venv at `/app/_models/acestep/.venv` clobbered on every fresh start, bind mount full directory, subprocess invoked with `cwd=checkpoint_dir`). No commit is needed to fix the parent plan.

What the parent plan **does not capture** (and which influence the option choice):

1. **The upstream ACE-Step `pyproject.toml` uses a custom PyTorch index (`pytorch-cu128`)** with explicit `[[tool.uv.index]]` and `[tool.uv.sources]` blocks. See [_models/acestep/pyproject.toml:60-91](../_models/acestep/pyproject.toml#L60-L91). Folding ACE-Step deps into the wrapper's `acestep-worker` extra (Option A) would require either duplicating that index machinery in our root [pyproject.toml](../pyproject.toml) or losing CUDA 12.8 wheels and falling back to PyPI torch (which doesn't ship `+cu128` builds). Either is a real refactor, not a small extras-bump.

2. **The upstream pyproject has a path-source dep on `nano-vllm` at `acestep/third_parts/nano-vllm`** ([_models/acestep/pyproject.toml:79](../_models/acestep/pyproject.toml#L79)). For Option A this would need to be vendored into our repo or replaced with a registry version. For Option B it just rides along with the directory copy.

3. **Upstream's `_get_project_root()` is `dirname(dirname(__file__))`** of `acestep/api_server.py` ([_models/acestep/acestep/api_server.py:100-102](../_models/acestep/acestep/api_server.py#L100-L102)). It is then joined with `"checkpoints"` ([_models/acestep/acestep/api/startup_model_init.py:64](../_models/acestep/acestep/api/startup_model_init.py#L64)) and with `"examples"` (api_server.py:135-136) at module-import time. **The upstream code is hard-coded to be run from a source tree** — if installed as a wheel into site-packages, `_get_project_root()` returns site-packages, where neither `checkpoints/` nor `examples/` exist, and `api_server.py` crashes during the SIMPLE_EXAMPLE_DATA pre-load. This rules out a "wheel install + drop the source tree" Option A variant. **The source tree must remain on disk somewhere**, with `checkpoints/` resolvable as a sibling of `acestep/`.

4. **`.dockerignore` line 8 currently excludes `_models/` from the build context entirely** ([_models/.dockerignore](../.dockerignore#L8)). Whichever option bakes anything from `_models/acestep/` into the image must update `.dockerignore` to allow the source tree (but not `.venv/` or `checkpoints/`) into the build context.

5. **Upstream pyproject.toml uses `requires-python = ">=3.11,<3.13"`** which is compatible with our `python:3.12-slim` base image. ✓ no Python version conflict.

6. **`_models/acestep/` content audit** (decision #3 in the parent plan):
   - `acestep/` (14 MB) — the importable package source, **needed at runtime**
   - `checkpoints/` (83 GB) — model weights, must stay a bind mount
   - `.venv/` (84 KB — broken host shim, see parent plan)
   - `.git/` (~50 MB — host clone state, NOT needed)
   - `.cache/`, `gradio_outputs/`, `manual_uv_sync.log`, `acestep-*.stderr.log` — host runtime artifacts, NOT needed
   - `pyproject.toml`, `uv.lock`, `README.md` — needed for `uv sync` to work
   - `examples/` — needed (loaded by api_server.py at import)
   - `openrouter/` — listed in `[tool.hatch.build.targets.wheel] packages`, needed
   - `assets/`, `ui/`, `scripts/`, `docs/`, `*.sh`, `*.bat`, `*.py` (cli.py, train.py, etc.), `requirements*.txt` — likely unused at runtime by `acestep-api`, but small (~few MB total). **Decision:** copy them anyway via a directory-level COPY with the heavy excludes — easier than a precise allowlist, and a few MB is irrelevant next to the multi-GB torch layer.

## State at start of Phase 8

- **Branch:** `feat/acestep-worker-pool` (head `2f33400`, the parent plan section rewrite)
- **Phases 1–7 are shipped and stable.** This is the only remaining blocker before the worker pool branch can merge to `main` cleanly.
- **What's already in place:**
  - Wrapper FastAPI app, model cache, heartbeat, registry — all baked into `/app/.venv` via [docker/acestep-worker.Dockerfile:17](../docker/acestep-worker.Dockerfile#L17) (`uv sync --frozen --no-dev --extra acestep-worker`)
  - The wrapper extra in [pyproject.toml:52-57](../pyproject.toml#L52-L57) is intentionally minimal (`fastapi`, `uvicorn`, `redis[hiredis]`, `huggingface_hub`)
  - Subprocess invocation in [src/acestep_worker/subprocess_runner.py:128-135](../src/acestep_worker/subprocess_runner.py#L128-L135): `cmd = [*uv, "run", "acestep-api", "--port", str(port)]` with `cwd=checkpoint_dir` and `env` from `build_env(...)`
  - `DEFAULT_CHECKPOINT_DIR = Path("/app/_models/acestep")` at [src/acestep_worker/__main__.py:24](../src/acestep_worker/__main__.py#L24)
  - Bind mount `./_models/acestep:/app/_models/acestep` at [docker-compose.yml:144](../docker-compose.yml#L144)
- **What's broken:** the inner ACE-Step venv is shadowed by the host's broken shim venv (84K of just `python` symlinks pointing at host Python). On every fresh container start, `uv run acestep-api` triggers a 5–15 minute re-resync of ~3-4 GB of torch + cudnn + diffusers wheels into `/app/_models/acestep/.venv`, which times out at the documented `ARQ_JOB_TIMEOUT=300`s default. The current workaround in [.env:26](../.env#L26) is `ARQ_JOB_TIMEOUT=1800`, which the parent plan flags for rollback.

## Decision matrix — Option A vs B vs C

**Picked: Option B — bake a separate inner venv into the image, narrow the bind mount to just `checkpoints/`.**

| Concern | A (single shared venv) | **B (two venvs, both baked)** | C (full base-image hierarchy) |
|---|---|---|---|
| Diff size | medium-large (rewrite wrapper extra) | **medium (one Dockerfile + compose + 2 small src changes)** | large (all four services) |
| Risk: dep conflicts | high — wrapper deps merge with upstream's torch+cu128+nano-vllm+gradio | **low — venvs stay isolated** | low |
| Risk: custom torch index | needs duplicating in root pyproject | **handled by upstream's own pyproject inside the image** | handled per-base-image |
| Risk: `_get_project_root()` source-tree assumption | **breaks** unless we COPY the source anyway | **handled — source tree lives at `/opt/acestep`** | handled |
| Image size | ~7 GB (one venv) | ~7 GB (two venvs but wrapper is ~80 MB on top of acestep base) | ~7 GB (base) + thin leaves |
| Build cache | one combined `uv sync` invalidates on any wrapper or upstream dep change | **two separate `uv sync` layers; wrapper changes don't invalidate the upstream layer** | best (per-base layer cached across services) |
| Time to ship | ~3 hours | **~2-3 hours** | ~1 day |

**Why A is rejected:** Folding ~50 upstream deps into the wrapper's `acestep-worker` extra requires duplicating the upstream's `[[tool.uv.index]] pytorch-cu128` block in our root pyproject (because `uv` extras can't carry their own index sources at the extras level), AND vendoring or registry-replacing `nano-vllm` (currently a path source). On top of that, the `_get_project_root()` problem means we'd still need to keep the upstream source tree on disk somewhere. So Option A is "Option B plus a complicated wrapper extras refactor that buys us nothing." Reject.

**Why C is rejected:** the user explicitly said no 1-day refactors for a 1-hour blocker. Phase 7 D1 ("split Dockerfile.worker") and the three-base-image hierarchy can be revisited as a separate phase after Phase 8 is in production for a few days.

**Open question for Option B (parent plan #5 — local-dev backward compatibility):** developers running the wrapper directly on the host (without Docker) would still hit the same broken-host-`.venv` problem. **Decision:** the wrapper has never been runnable directly on the host (it requires Redis, GPU, the control-plane URL, etc. — all docker-only assumptions). The supported local-dev path is `docker compose up songmaker-acestep-worker-0`. No backward-compat shim is needed. Document this in passing in the commit message.

## Surprise found during exploration

**The upstream ACE-Step source tree at `_models/acestep/` is a git clone (has its own `.git/`)**, not a submodule and not vendored. This means:

- The build context will pull from the host's working copy of that clone, not a pinned ref. **Decision:** acceptable — the same is already true for the host bind mount today, and Phase 8 doesn't change the upstream pinning story. A future phase (or Phase 7 leftover) could pin via submodule or wheel build, but that's out of scope.
- `.git/` must be excluded from the COPY (it's ~50 MB of host-only state). Already handled by adding `_models/acestep/.git/` to `.dockerignore`.

## Concrete diffs

### `.dockerignore`

Replace the blanket `_models/` exclude with a precise list of host-only artifacts.

```diff
-# ACE-Step (mounted as volume, not copied)
-_models/
+# ACE-Step source tree is COPYed into the image at /opt/acestep so the inner
+# subprocess venv can be baked at build time. Only host-runtime artifacts and
+# the heavy weights are excluded; weights are bind-mounted at runtime.
+_models/acestep/.venv/
+_models/acestep/.git/
+_models/acestep/.cache/
+_models/acestep/checkpoints/
+_models/acestep/gradio_outputs/
+_models/acestep/manual_uv_sync.log
+_models/acestep/acestep-*.stderr.log
+_models/acestep/acestep_stderr.log
```

### `docker/acestep-worker.Dockerfile` (full new file)

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

RUN useradd --create-home --shell /bin/bash songmaker
RUN install -d -o songmaker -g songmaker /app /opt/acestep
USER songmaker

# ---- Layer 1: wrapper venv (small, fast to rebuild) ----------------------
COPY --chown=songmaker pyproject.toml uv.lock ./
RUN mkdir -p src/acestep_worker && touch src/acestep_worker/__init__.py && \
    uv sync --frozen --no-dev --extra acestep-worker && \
    rm -rf src/acestep_worker/__init__.py

# ---- Layer 2: inner ACE-Step venv at /opt/acestep/.venv ------------------
# COPY only the upstream source tree's lockfile + manifest first so the heavy
# dep download caches independently of churn in acestep/ source files.
COPY --chown=songmaker _models/acestep/pyproject.toml _models/acestep/uv.lock _models/acestep/README.md /opt/acestep/
WORKDIR /opt/acestep
# nano-vllm is a path-source dep at acestep/third_parts/nano-vllm — we need
# at least its pyproject + source visible before `uv sync` will resolve.
COPY --chown=songmaker _models/acestep/acestep/third_parts/ /opt/acestep/acestep/third_parts/
RUN uv sync --frozen --no-dev --no-install-project

# Now COPY the rest of the upstream source so the editable project install
# can finish. This layer invalidates on any upstream source change but the
# heavy wheel layer above stays cached.
COPY --chown=songmaker _models/acestep/ /opt/acestep/
RUN uv sync --frozen --no-dev

# ---- Layer 3: wrapper source code (cheapest layer) -----------------------
WORKDIR /app
COPY --chown=songmaker src/acestep_engine/ src/acestep_engine/
COPY --chown=songmaker src/acestep_worker/ src/acestep_worker/
RUN uv sync --frozen --no-dev --extra acestep-worker

ENV HF_HUB_DISABLE_XET=1
ENV PYTHONUNBUFFERED=1
ENV ACESTEP_SRC_DIR=/opt/acestep

ENTRYPOINT ["uv", "run", "python", "-m", "acestep_worker"]
```

**Notes on the build order:**
- The wrapper venv layer (Layer 1) stays first so wrapper dep changes don't invalidate the multi-GB ACE-Step layer.
- Layer 2 splits the heavy `uv sync` into two steps so that source-only edits in `_models/acestep/acestep/` don't re-trigger the wheel download. The `--no-install-project` first pass is the standard uv pattern.
- `git` is added to apt because `uv sync` may need it for any git-source deps in the upstream lockfile. (Cheap insurance — if the lockfile has no git deps the binary is still tiny.)
- `/opt/acestep` is owned by `songmaker` so the unprivileged user can write to it. The bind-mounted `checkpoints/` subdirectory inherits its host-side ownership at runtime — this is unchanged from today.

### `docker-compose.yml` — `songmaker-acestep-worker-0` block

```diff
     environment:
       WORKER_ID: "acestep-worker-0"
       WORKER_HOST: "songmaker-acestep-worker-0"
       WORKER_PORT: "8001"
       GPU_ID: "0"
       VRAM_BUDGET_GB: "${ACESTEP_WORKER_VRAM_GB:-22}"
       ACESTEP_STARTUP_TIMEOUT_SECONDS: "${ACESTEP_STARTUP_TIMEOUT_SECONDS:-300}"
-      ACESTEP_CHECKPOINT_DIR: "/app/_models/acestep"
+      ACESTEP_CHECKPOINT_DIR: "/opt/acestep"
       AUDIO_OUTPUT_DIR: "/app/data/audio/worker_output"
-      ACESTEP_LOG_DIR: "/app/_models/acestep"
+      ACESTEP_LOG_DIR: "/opt/acestep/logs"
       REDIS_URL: redis://redis:6379/0
       CONTROL_PLANE_URL: "${ACESTEP_WORKER_CONTROL_PLANE_URL:-http://songmaker-web:8080}"
       SONGMAKER_INTERNAL_TOKEN: "${SONGMAKER_INTERNAL_TOKEN:-}"
       HF_TOKEN: "${HF_TOKEN:-}"
       HF_HUB_DISABLE_XET: "1"
     volumes:
-      - ./_models/acestep:/app/_models/acestep
+      - ./_models/acestep/checkpoints:/opt/acestep/checkpoints
       - audiofiles:/app/data/audio
```

**Why the bind mount target moved from `/app/_models/acestep` → `/opt/acestep/checkpoints`:** the upstream `_get_project_root()` resolves to `dirname(dirname(__file__))` which after the editable install at `/opt/acestep` is `/opt/acestep`. The upstream then joins that with `"checkpoints"` ([startup_model_init.py:64](../_models/acestep/acestep/api/startup_model_init.py#L64)). So the weights must be visible at `/opt/acestep/checkpoints/`. Narrowing the mount to just that directory means the host's broken `.venv` and the host's source tree no longer shadow the baked image content.

**Why `ACESTEP_LOG_DIR` moves to `/opt/acestep/logs`:** the old default pointed at the bind-mount root. After narrowing the mount, we need a writable in-image path. `/opt/acestep` is owned by `songmaker` so a `logs/` subdirectory works without extra Dockerfile setup (it's `mkdir`d on demand by `start_acestep_subprocess` via `log_dir.mkdir(parents=True, exist_ok=True)` in [subprocess_runner.py:125](../src/acestep_worker/subprocess_runner.py#L125)).

### `src/acestep_worker/__main__.py`

```diff
 DEFAULT_VRAM_BUDGET_GB = 22.0
-DEFAULT_CHECKPOINT_DIR = Path("/app/_models/acestep")
+DEFAULT_CHECKPOINT_DIR = Path("/opt/acestep")
 DEFAULT_AUDIO_DIR = Path("/app/data/audio/worker_output")
-DEFAULT_LOG_DIR = Path("/app/_models/acestep")
+DEFAULT_LOG_DIR = Path("/opt/acestep/logs")
 DEFAULT_ACESTEP_INNER_PORT = 8101
```

That's the only change — every other env var (`ACESTEP_CHECKPOINT_DIR`, `ACESTEP_LOG_DIR`) is set explicitly in compose, so the defaults only matter for unit tests and developer-mode invocations.

### `src/acestep_worker/subprocess_runner.py`

**No change to `start_acestep_subprocess`'s function signature, cmd construction, or cwd plumbing** — the existing `cwd=checkpoint_dir` is exactly right for Option B once `checkpoint_dir` resolves to `/opt/acestep`. The `uv run acestep-api` invocation will find `/opt/acestep/.venv` (baked, populated, owned by songmaker) and skip the resync entirely.

The only thing worth touching here is **dropping the `STARTUP_TIMEOUT_SECONDS` ceiling** that masks regressions. Currently it's read from `ACESTEP_STARTUP_TIMEOUT_SECONDS` and defaults to 300. After Option B the actual subprocess startup is ~30s. **Decision:** leave the env var alone (300s is plenty of headroom), but drop the docker-compose `ACESTEP_STARTUP_TIMEOUT_SECONDS` override line entirely — see the compose diff above which intentionally keeps the line at the documented 300 default. If a future regression slow-walks startup past 300s we want it to fail loudly, not silently.

Wait, the existing compose line is `ACESTEP_STARTUP_TIMEOUT_SECONDS: "${ACESTEP_STARTUP_TIMEOUT_SECONDS:-300}"` which already defaults to 300. **Keep as-is.** No change needed.

### `pyproject.toml`

**No change** to the wrapper's `acestep-worker` extra. Option B keeps the wrapper extra minimal — that's its whole point versus Option A.

### `.env`

```diff
-ARQ_JOB_TIMEOUT=1800
+# ARQ_JOB_TIMEOUT removed — defaults to 300s after the Phase 8 venv fix.
+# See plans/acestep-worker-pool-phase8-subplan.md.
```

**Critical:** this rollback must land in the **same commit** as the venv fix per parent plan decision #6. If the rollback ships separately and the venv fix has any startup-time regression, `ARQ_JOB_TIMEOUT=1800` would be the lifeline.

(`.env` is gitignored. The "rollback" here is local — but the compose default of 300 is what matters for any other dev environment, and the line above removes the override.)

### Tests — `tests/acestep_worker/test_subprocess_runner.py`

The existing tests at [tests/acestep_worker/test_subprocess_runner.py:162-219](../tests/acestep_worker/test_subprocess_runner.py#L162-L219) all pass `checkpoint_dir=tmp_path` and mock `subprocess.Popen`. They don't actually run uv. **None of them need updates** because the function signature and cmd construction don't change.

**One new test** is worth adding to lock in the post-fix invariant:

```python
def test_start_acestep_subprocess_uses_cwd(tmp_path: Path) -> None:
    proc = MagicMock()
    proc.pid = 4242
    proc.poll.return_value = None
    captured: dict = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return proc

    with (
        patch("acestep_worker.subprocess_runner.find_uv", return_value=["uv"]),
        patch("subprocess.Popen", side_effect=fake_popen),
        patch("acestep_worker.subprocess_runner.wait_for_health"),
    ):
        start_acestep_subprocess(
            "sft",
            port=8101,
            checkpoint_dir=tmp_path,
            vram_budget_gb=24.0,
        )

    assert captured["cwd"] == tmp_path
    assert captured["cmd"] == ["uv", "run", "acestep-api", "--port", "8101"]
```

This is the contract test that the parent plan's verified mechanism (`cwd` matters for venv discovery) is upheld.

## Files Touched

| File | Change |
|---|---|
| `.dockerignore` | Replace `_models/` with precise excludes (`.venv/`, `.git/`, `checkpoints/`, host runtime artifacts) |
| `docker/acestep-worker.Dockerfile` | Full rewrite: add Layer 2 that COPYs upstream source to `/opt/acestep` and runs `uv sync` against it. Add `git` to apt. Set `ACESTEP_SRC_DIR=/opt/acestep` env. |
| `docker-compose.yml` | Narrow bind mount to `./_models/acestep/checkpoints:/opt/acestep/checkpoints`. Move `ACESTEP_CHECKPOINT_DIR` to `/opt/acestep`. Move `ACESTEP_LOG_DIR` to `/opt/acestep/logs`. |
| `src/acestep_worker/__main__.py` | `DEFAULT_CHECKPOINT_DIR` and `DEFAULT_LOG_DIR` move to `/opt/acestep` and `/opt/acestep/logs`. |
| `tests/acestep_worker/test_subprocess_runner.py` | Add `test_start_acestep_subprocess_uses_cwd` to lock in the cmd + cwd invariant. |
| `.env` | Remove `ARQ_JOB_TIMEOUT=1800`. Add a one-line comment pointing at this sub-plan. |
| `plans/acestep-worker-pool.md` | (Optional, end of phase) Mark Phase 8 status as DONE in the phase index. |
| `docs/acestep.md` | (Optional, end of phase) One-paragraph addendum: "the inner subprocess venv is now baked at `/opt/acestep/.venv`; only weights are bind-mounted." |

**Not touched (per "things to NOT do"):** model_cache.py, heartbeat schema, scheduler, admin endpoints, frontend, alembic, pyproject.toml.

## Implementation order with HARD checkpoints

### Step 1 — Pre-flight
- Confirm host has `_models/acestep/pyproject.toml`, `_models/acestep/uv.lock`, `_models/acestep/acestep/third_parts/nano-vllm/` present (✓ verified during exploration).
- `unset VIRTUAL_ENV && uv run ruff check src/ tests/` — baseline must pass.
- `docker compose down -v` to clear any cached state from previous attempts.

### Step 2 — `.dockerignore` first
- Edit `.dockerignore` per the diff above.
- **HARD checkpoint:** `docker build -f docker/acestep-worker.Dockerfile --target stage-that-just-COPYs --progress=plain -t throwaway . 2>&1 | grep -i 'transferring context'` — verify the build context size jumps from "few MB" (with `_models/` excluded) to "~150 MB" (with the upstream source allowed). If it's still tiny, the .dockerignore edit didn't take effect.
- If the context size is `>500 MB`, the `.dockerignore` is letting through `checkpoints/` or `.git/` — fix before continuing.

### Step 3 — Dockerfile rewrite
- Replace [docker/acestep-worker.Dockerfile](../docker/acestep-worker.Dockerfile) with the full content above.
- **HARD checkpoint:** `timeout 1200 docker compose build songmaker-acestep-worker-0 --progress=plain 2>&1 | tee /tmp/phase8-build.log`
  - Expected: completes within 20 minutes on a fast connection. The first build pulls ~3-4 GB of torch wheels (one-time).
  - Verify in the log: `Successfully built` line at the end. No `error: ` lines.
  - Specifically grep for `error: distribution` (uv's dep-conflict signature) and `Failed to fetch` (network/index issues).
- **HARD checkpoint:** `docker run --rm --entrypoint=ls songmaker-songmaker-acestep-worker-0 /opt/acestep/.venv/bin | grep acestep-api` — confirms the upstream venv is populated and the entry point script exists. If this fails, the `uv sync` step in Layer 2 didn't actually install the project.

### Step 4 — compose + worker default updates
- Edit `docker-compose.yml` per the diff above.
- Edit [src/acestep_worker/__main__.py](../src/acestep_worker/__main__.py) per the diff above.
- Edit `.env` to remove `ARQ_JOB_TIMEOUT=1800`.
- **HARD checkpoint:** `unset VIRTUAL_ENV && uv run ruff check src/ tests/` passes.

### Step 5 — Test addition + suite
- Add `test_start_acestep_subprocess_uses_cwd` to [tests/acestep_worker/test_subprocess_runner.py](../tests/acestep_worker/test_subprocess_runner.py).
- **HARD checkpoint:** `unset VIRTUAL_ENV && uv run pytest tests/acestep_worker/ -q` passes (specifically the new test plus the existing 100% coverage on `subprocess_runner.py`).
- **HARD checkpoint:** `unset VIRTUAL_ENV && uv run pytest tests/ -q --ignore=tests/test_scorers.py --ignore=tests/test_scorers_extended.py` passes — full suite excluding GPU tests.

### Step 6 — Frontend smoke (defensive)
- `cd frontend && pnpm check && pnpm lint && pnpm test` — Phase 8 doesn't touch frontend, but run anyway to confirm no transitive breakage from the compose env var renames.

### Step 7 — End-to-end smoke test (THE deliverable)
- `docker compose down -v`
- `timeout 600 docker compose up -d --build --wait songmaker-acestep-worker-0 songmaker-music-worker songmaker-web`
- **HARD checkpoint:** all three containers report healthy within 60 s. If `songmaker-acestep-worker-0` doesn't go healthy: `docker compose logs songmaker-acestep-worker-0 --tail 100` and diagnose. Most likely cause if it fails here: the entry point can't find `/opt/acestep` or the songmaker user can't write to `/opt/acestep/logs`.
- **HARD checkpoint (THE checkpoint for this phase):**
  ```
  time docker compose exec songmaker-acestep-worker-0 \
    curl -X POST -H 'Content-Type: application/json' \
    -d '{"mode":"sft"}' http://localhost:8001/load_model
  ```
  Expected: returns `{"status":"ok",...}` in **<90 seconds wall-clock**, down from 5+ minutes pre-fix. If this is still slow, check `docker compose exec songmaker-acestep-worker-0 ls /opt/acestep/.venv/lib/python3.12/site-packages/torch` — if it's missing, the bind mount is shadowing the baked venv.
- **HARD checkpoint:** Redis heartbeat:
  ```
  docker compose exec redis redis-cli GET 'songmaker:acestep:worker:acestep-worker-0'
  ```
  Expected: JSON containing `"loaded":[{"mode":"sft","size_gb":6.0}]` within 5 s of the load completing.
- **Regression test for Phase 6 PR 2 D6:** with sft loaded, start a real generation against sft from the main UI. While it's running, hit Load → xl-base via the admin tab. Expected: load fails with `"all eligible models are in use or pinned"` and the running generation completes unharmed. If this regresses, **stop and investigate** — Phase 8 should not touch any of the refcount/pin code.

If all checkpoints pass: commit + push. If any fails: diagnose and fix in the same commit (no ship-broken-then-fix-up cycle).

## Watchpoints

1. **`uv sync` dep conflicts inside `/opt/acestep`.** The upstream lockfile is pinned (we use `--frozen`) so this should be deterministic. If `uv sync` fails with a resolver error, it means the upstream `uv.lock` was modified relative to its `pyproject.toml`. Diagnose with `(cd _models/acestep && uv lock --check)` on the host before retrying the docker build.
2. **The `nano-vllm` path source.** The Dockerfile copies `_models/acestep/acestep/third_parts/` before the first `uv sync` step. If that path doesn't exist or doesn't contain a `pyproject.toml`, `uv sync` fails with "package not found". `find _models/acestep/acestep/third_parts/nano-vllm -name pyproject.toml` to verify before building.
3. **Bind mount narrowing breaking some other path under `_models/acestep/`.** The upstream code's only references to paths joined with `_get_project_root()` are `examples/` (resolved at module-import → satisfied by the COPYed source) and `checkpoints/` (resolved at runtime → satisfied by the narrowed bind mount). Anything else (e.g., `assets/`, `ui/`, `gradio_outputs/`) is referenced only by code paths we don't hit (`acestep-cli`, gradio UI, training scripts). If a real generation triggers a `FileNotFoundError` for some other path under `_models/acestep/`, that's a missing source-tree subdirectory — re-add it to the COPY and document.
4. **`/opt/acestep/logs` write permissions.** The Dockerfile chowns `/opt/acestep` to `songmaker` so the subprocess runner's `log_dir.mkdir(parents=True, exist_ok=True)` should succeed. If it doesn't, the symptom is the subprocess starts but writes nothing to `acestep-sft.stderr.log`.
5. **Rolling-restart safety.** Phases 1–7 already established that the worker and the web container are independent containers with their own images. Phase 8 only modifies `acestep-worker.Dockerfile` and the worker's compose entry — the web image's `Dockerfile` and the music-worker's `Dockerfile.worker` are untouched. A partial deploy where only `acestep-worker-0` is recreated is safe: it re-registers via `internal_api`, picks up its identity, and the web container's view is unaffected. **No worker↔web protocol change in Phase 8.**
6. **`ARQ_JOB_TIMEOUT` rollback ordering.** The rollback MUST land in the same commit as the venv fix. If git status shows it as a separate file in a separate commit at any point, squash before pushing.
7. **The `.env` is gitignored.** Editing `.env` is a no-op for the repo, but it's still important — it removes the workaround from the developer's local environment so the next `docker compose up` actually exercises the documented default. The change is "user-visible" via the commit message even though there's no diff.
8. **Build cache thrash.** If iterating on the Dockerfile, the multi-GB Layer 2 will rebuild on any `_models/acestep/pyproject.toml` change. Avoid touching that file during the iteration loop. Wrapper-only changes (`src/acestep_worker/`) only invalidate Layer 3 and rebuild in seconds.

## Smoke test plan (recap with wall-clock expectations)

| Step | Command | Expected wall-clock |
|---|---|---|
| 1 | `docker compose down -v` | <10 s |
| 2 | `timeout 600 docker compose up -d --build --wait songmaker-acestep-worker-0 songmaker-music-worker songmaker-web` | First build: 10-20 min (one-time torch download). Cached rebuild: <60 s. |
| 3 | `docker compose ps` — confirm three containers `(healthy)` | n/a |
| 4 | Hard refresh browser, open /settings/users → ACE-Step admin tab | n/a |
| 5 | Click Load → sft on the worker card | **<90 s wall-clock** (down from 5+ min) — THIS is the gate |
| 6 | `docker compose exec redis redis-cli GET 'songmaker:acestep:worker:acestep-worker-0'` | <5 s after step 5 completes — should show `"loaded":[{"mode":"sft",...}]` |
| 7 | Start a real generation against sft from the main UI | ~30-90 s for the generation itself |
| 8 | While step 7 is running, click Load → xl-base in the admin tab | Should fail immediately with `"all eligible models are in use or pinned"` |
| 9 | Confirm step 7's generation completes unharmed | n/a |

Total smoke test wall clock from a clean state on a fast connection: **~25-35 minutes** on the first run (dominated by the one-time torch wheel download), **~5 minutes** on subsequent runs (no rebuild needed).

## Self-review checklist (before commit)

- [ ] `.dockerignore` excludes `.git/`, `.venv/`, `checkpoints/`, all `*.stderr.log`, `gradio_outputs/`, `.cache/`, `manual_uv_sync.log`
- [ ] Dockerfile builds cleanly from a fresh `docker compose build --no-cache`
- [ ] `/opt/acestep/.venv/bin/acestep-api` exists in the built image (Step 3 checkpoint)
- [ ] `subprocess_runner.py` is **unchanged** (Option B's whole point — no source code changes to the runner)
- [ ] `__main__.py` defaults updated; no other Python source touched
- [ ] `pyproject.toml` `acestep-worker` extra is **unchanged** (no Option A drift)
- [ ] `tests/acestep_worker/test_subprocess_runner.py` has the new cwd-invariant test
- [ ] `.env` no longer has `ARQ_JOB_TIMEOUT=1800` (and it's the same commit)
- [ ] All checks pass: `ruff check`, `pytest -q --ignore=tests/test_scorers*`, `pnpm check && pnpm lint && pnpm test`
- [ ] Smoke test loads sft in <90 s
- [ ] Smoke test D6 regression (load contention with active job) still rejects
- [ ] No frontend, scheduler, model_cache, heartbeat, or admin_api files touched

## Rollback plan

If the new image has a startup regression that survives the smoke test gate, the recovery path is:

1. `git revert <commit-sha>` — single commit, clean revert
2. `docker compose build songmaker-acestep-worker-0`
3. `docker compose up -d --force-recreate songmaker-acestep-worker-0`
4. Restore `ARQ_JOB_TIMEOUT=1800` in `.env` for the developer-local environment

The bind mount on the host (`./_models/acestep/checkpoints/`) is unchanged structurally — only the container-side mountpoint moves. After a revert, the container will once again look for `/app/_models/acestep/checkpoints/` and the host will once again provide it. No data migration, no `down -v`, no model re-download.

## What is NOT in Phase 8 (deferred)

- Splitting `Dockerfile.worker` for music-worker and scoring-worker (Phase 7 D1, deferred indefinitely per the parent plan once Option B is picked)
- Three-base-image hierarchy (Option C — separate future phase if/when image-build time becomes the bottleneck)
- Pinning the upstream ACE-Step version (currently the host clone, possibly stale — Phase 9+ candidate)
- Multi-host worker deployment (parent plan known tech debt)
- CI image registry pushes
- Removing the `acestep-worker` extra entirely in favor of installing the upstream package directly into `/app/.venv` (Option A — explicitly rejected)

## Branching + commits

**Single backend commit.** This is one logical change: bake the inner venv, narrow the bind mount, drop the workaround. Splitting the Dockerfile rewrite from the compose edit from the `__main__.py` default change would leave the branch in a half-broken state at intermediate commits (Dockerfile builds for a layout the runtime doesn't use yet, or vice versa). One commit, one revert.

Suggested commit message:

```
feat(phase8): bake inner ACE-Step venv at /opt/acestep, narrow bind mount

- Dockerfile: COPY upstream source tree to /opt/acestep, run `uv sync`
  there to bake /opt/acestep/.venv with all torch + diffusers + nano-vllm
  deps at build time
- compose: narrow ./_models/acestep:/app/_models/acestep to
  ./_models/acestep/checkpoints:/opt/acestep/checkpoints — host's broken
  shim .venv no longer shadows the baked one
- worker: DEFAULT_CHECKPOINT_DIR moves to /opt/acestep, DEFAULT_LOG_DIR
  to /opt/acestep/logs
- subprocess_runner: unchanged (cwd plumbing was already correct)
- .env: drop ARQ_JOB_TIMEOUT=1800 workaround — fresh-container model
  load is now <90s (down from 5+ minutes), well within the documented
  300s default
- tests: add cwd invariant test for start_acestep_subprocess

Closes phase 8 of plans/acestep-worker-pool.md.
```

Push the sub-plan as a separate prior commit:
```
docs(phase8): add sub-plan with locked design decision
```

## Quick context for next session

If this gets handed off mid-implementation:

- Branch `feat/acestep-worker-pool`, commit base `2f33400`.
- The sub-plan locks **Option B** (two venvs, both baked, narrow bind mount). Do not switch to A or C without re-reading the decision matrix above.
- The Dockerfile is the biggest change — the wrapper image goes from ~500 MB to ~7 GB. This is intentional and unavoidable for any option that fixes the bug.
- The smoke test gate is "sft loads in <90 s on a fresh container." Don't ship without hitting it.
- The `ARQ_JOB_TIMEOUT` rollback MUST be in the same commit as the venv fix (parent plan decision #6).
- If `uv sync` inside `/opt/acestep` fails during the build, run `(cd _models/acestep && uv lock --check)` on the host first to confirm the upstream lockfile is in sync.
- The host bind mount narrowing (`checkpoints/` only) is the part most likely to surprise — anything in `_models/acestep/` that wasn't `checkpoints/` is now COPYed into the image instead of bind-mounted. Developers who edit `_models/acestep/` source files will need to rebuild the image to see their changes (acceptable: that subdirectory is the upstream submodule, not Songmaker code).

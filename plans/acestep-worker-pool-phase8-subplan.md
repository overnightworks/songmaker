# Phase 8 Sub-plan — Image hierarchy refactor: gpu-torch-base + acestep-base, split Dockerfile.worker, bake the inner venv

> Concrete implementation plan for [Phase 8 of acestep-worker-pool.md](acestep-worker-pool.md#phase-8--image-architecture-refactor-bake-the-inner-ace-step-venv-narrow-the-bind-mount). Read end-to-end before starting; the parent section sketches the three options (A/B/C) but leaves the choice and the exact diff to this sub-plan. This sub-plan picks **Option C in its "C1" reframing** — the full base-image hierarchy that the parent plan describes, **minus** the aspirational "deduplicate torch between scoring and acestep" benefit (which doesn't materialise in practice — see the Surprises section). C1 still does Phase 7 D1 ("split `Dockerfile.worker`") and still folds the venv-clobber fix into the same change, but it does **not** force a torch version unification across the codebase.

## READ THIS FIRST — what changed since the previous draft of this sub-plan

This document was first drafted for **Option B** at commit `41c3591` (`docs(phase8): add sub-plan with locked design decision`). The user reviewed it, asked for Option C instead, and after a round of clarifying questions explicitly chose the **C1** variant: full base-image hierarchy with each service getting the deps it actually needs, and **no** torch-version unification. This rewrite supersedes the Option B draft commit-for-commit; the file is the same path but the content is fundamentally different.

The Option B mechanical fix (bake the inner ACE-Step venv, narrow the bind mount, drop the `ARQ_JOB_TIMEOUT=1800` workaround) is still present inside C1 — it's the leaf-level change to the new `acestep-worker.Dockerfile`. C1 wraps it in the wider hierarchy refactor.

## Discrepancies vs parent plan section (no commit needed)

I verified every claim in the Phase 8 section of [acestep-worker-pool.md](acestep-worker-pool.md) against the code on disk at commit `2f33400`. The verified-mechanism block (wrapper venv at `/app/.venv` baked, inner venv at `/app/_models/acestep/.venv` clobbered on every fresh start, bind mount full directory, subprocess invoked with `cwd=checkpoint_dir`) is **factually correct**. No parent-plan correction commit is needed.

What the parent plan **misframes** about Option C (and which moved us from "True C with torch unification" to C1):

1. **The parent plan claims Option C "deduplicates the torch layer between scoring and acestep".** It doesn't, in practice. Today scoring and acestep don't share a torch build at all:
   - Scoring extras pin `torch>=2.2,<3` and the resolved lockfile is `torch==2.5.1+cu121` (PyPI).
   - Upstream ACE-Step pins `torch==2.10.0+cu128` from a custom `[[tool.uv.index]] pytorch-cu128` (https://download.pytorch.org/whl/cu128).
   - **Scoring runs on CPU at runtime** ([docker-compose.yml:184](../docker-compose.yml#L184) sets `SCORING_DEVICE=cpu` and the service has no GPU `deploy:` block). So scoring never even *uses* its CUDA wheels — they're carried for nothing.
   - Forcing them onto a shared `torch==2.10.0+cu128` would change scoring's runtime stack for symbolic value only and adds real risk surface (audiobox checkpoint compat, librosa/numba/scipy chain). C1 explicitly **does not** do that.

2. **The parent plan claims `faster-whisper` and `audiobox-aesthetics` would benefit from a shared GPU base.** They wouldn't:
   - `faster-whisper` and its `ctranslate2` backend **don't depend on torch at all**. They use bundled CUDA runtime libs and `onnxruntime`. Verified by reading [uv.lock](../uv.lock) — neither pulls torch as a dep.
   - `audiobox-aesthetics 0.0.4` declares unpinned `torch`/`torchaudio`. It runs on CPU here. The "shared GPU base" buys nothing.

3. **The parent plan implies a `scoring-base` image is part of the hierarchy.** It would be — but it would NOT inherit from `gpu-torch-base`. It's structurally a separate branch of the tree (CPU torch + audiobox + whisper). C1 keeps it as its own self-contained leaf Dockerfile rather than a dedicated base image (one consumer, no reuse story today). If a future audiobox-on-GPU worker shows up, that's when we'd extract a `scoring-base`.

4. **The parent plan does not mention that `Dockerfile.worker` is shared by music-worker AND scoring-worker today.** It is ([docker-compose.yml:91-95](../docker-compose.yml#L91-L95) and [docker-compose.yml:160-166](../docker-compose.yml#L160-L166)). Phase 7 D1's "split Dockerfile.worker" was deferred → Phase 8. C1 does this split: music-worker gets a tiny dedicated Dockerfile (server extras only, no torch, no scoring), scoring-worker gets one too (server + scoring + whisper extras).

The verified-mechanism block of the parent plan is unchanged and correct. The decisions block (#1–#8) are still load-bearing; this sub-plan answers each one.

## State at start of Phase 8

- **Branch:** `feat/acestep-worker-pool` (head before this sub-plan rewrite: `41c3591`, the Option B draft of this same file)
- **Phases 1–7 are shipped and stable.** This is the only remaining blocker before merging the worker-pool branch to `main`.
- **Image inventory today:**
  | Service | Dockerfile | Extras installed | Has torch? | Image size (rough) |
  |---|---|---|---|---|
  | songmaker-web | `Dockerfile` (multi-stage with frontend) | `server` | No | ~500 MB |
  | songmaker-music-worker | `Dockerfile.worker` (shared) | `server + scoring + whisper` | Yes (cu121, 3-4 GB unused) | ~5 GB |
  | songmaker-scoring-worker | `Dockerfile.worker` (shared) | `server + scoring + whisper` | Yes (cu121, runs on CPU) | ~5 GB |
  | songmaker-acestep-worker-0 | `docker/acestep-worker.Dockerfile` | `acestep-worker` (wrapper only — fastapi/uvicorn/redis/huggingface_hub) | No (in the wrapper venv); inner subprocess venv re-syncs from scratch every fresh start due to broken host bind-mounted `.venv` | ~500 MB image but ~3-4 GB downloaded on first `/load_model` per fresh container |
- **What's broken:** the inner ACE-Step subprocess uses a separate venv at `/app/_models/acestep/.venv` (the bind-mounted host shim, 84K of just symlinks to host Python). On every fresh container, `uv run acestep-api` detects the broken venv, deletes it, and re-resyncs ~3-4 GB of torch + cudnn + diffusers wheels into the host's mount path. Wall clock: 5-15 min on a fast connection, longer than the documented `ARQ_JOB_TIMEOUT=300` so [.env:26](../.env#L26) currently has the `ARQ_JOB_TIMEOUT=1800` workaround.
- **Phase 7 D1 ("split Dockerfile.worker")** was marked SUPERSEDED → Phase 8 in [plans/acestep-worker-pool-phase7-subplan.md](acestep-worker-pool-phase7-subplan.md) and is folded into this phase.

## C1 — design

### Image hierarchy

```
                          python:3.12-slim
                                 │
        ┌────────────────────────┼────────────────────────┐
        ▼                        ▼                        ▼
  gpu-torch-base           (direct leaves with no shared base)
  songmaker/gpu-torch        ┌──────────┬──────────────┬──────────┐
  -base:latest               ▼          ▼              ▼          ▼
  - torch 2.10+cu128    music-worker  scoring-worker  web      (other future
  - torchaudio 2.10     server        server+scoring  server    leaves)
  - cudnn/cublas         only         +whisper       only
  - cu128 runtime        no torch     PyPI torch     no torch
        │
        ▼
  acestep-base
  songmaker/acestep-base:latest
  - upstream ACE-Step source at /opt/acestep
  - /opt/acestep/.venv populated via `uv sync --frozen`
    against the upstream pyproject.toml + uv.lock
  - diffusers, transformers, nano-vllm, gradio, etc.
        │
        ▼
  acestep-worker
  - songmaker_cli wrapper code
  - acestep_engine source
  - ENTRYPOINT: python -m acestep_worker
```

**Key properties:**
- `gpu-torch-base` is the only image with the heavy CUDA stack. Today exactly one consumer (`acestep-base`). Tomorrow's potential consumers: an audiobox-on-GPU scoring worker, a whisper-on-GPU worker, anything else cu128. Justified now by the explicit "future GPU workers" rationale in the parent plan, not by current dedup.
- `acestep-base` bakes the upstream ACE-Step source tree at `/opt/acestep` and runs `uv sync --frozen` against the upstream `pyproject.toml`/`uv.lock` so `/opt/acestep/.venv` is fully populated at image-build time. **This is the venv-clobber fix.** The bind mount on the leaf only carries `checkpoints/`, no longer the source tree or the `.venv`.
- `music-worker` and `scoring-worker` are direct leaves of `python:3.12-slim`. No GPU base. No shared parent. They're not torch-poor variants of the GPU base; they're a different branch of the tree.
- `web` is unchanged structurally — already minimal, already on `python:3.12-slim`, only `--extra server`.

### What C1 buys vs. Option B

| Concern | Option B | **C1** |
|---|---|---|
| Venv clobber fix | ✅ via single-Dockerfile bake | ✅ via the `acestep-base` layer |
| Bind mount narrowing | ✅ | ✅ |
| `ARQ_JOB_TIMEOUT` rollback | ✅ | ✅ |
| Music-worker stops carrying unused scoring/torch wheels | ❌ (still on shared `Dockerfile.worker`) | ✅ (~5 GB → ~500 MB) |
| `Dockerfile.worker` split (Phase 7 D1) | ❌ deferred | ✅ done |
| `acestep-base` reusable for future GPU workers | ❌ inline layer | ✅ named base image |
| Files touched | ~6 | ~12-14 |
| Build orchestration complexity | none (compose handles it) | NEW: `scripts/build_images.sh` to order base→leaf builds |
| Implementation time | 2-3 hrs | ~6-10 hrs (includes scoring smoke + dockerfile splitting) |

### What C1 explicitly does NOT do (vs. parent plan's full Option C)

1. **No torch unification across the codebase.** `pyproject.toml` and `uv.lock` are unchanged. Scoring stays on `torch==2.5.1+cu121` (CPU at runtime). The acestep stack stays on `torch==2.10.0+cu128`. They live in separate venvs in separate images and never see each other.
2. **No `scoring-base` named image.** Single consumer today, no reuse story. If/when we get a second torch-on-CPU worker, extract it then.
3. **No image registry pushes (no GHCR, no tagging scheme).** Local-only base image builds for the first cut. Defer registry to a later phase. The build script tags as `songmaker/<name>:latest` in the local docker daemon.
4. **No CI changes.** CI doesn't currently build the worker images at all (it runs `pytest` and `pnpm` against the source tree, not against built images). C1 doesn't add image-building to CI. Smoke test is local.

## Surprises found during exploration (must read)

1. **`scoring-worker` runs on CPU.** [docker-compose.yml:184](../docker-compose.yml#L184) sets `SCORING_DEVICE=cpu` and the service has no GPU `deploy:` block. The cu121 wheels in its image are never exercised at runtime. C1 doesn't fix this (scoring stack stays as-is) but this finding is what killed the "shared GPU base for scoring + acestep" framing.
2. **`faster-whisper 1.2.1` and `ctranslate2 4.7.1` don't depend on torch.** Verified in [uv.lock](../uv.lock). `ctranslate2` ships its own bundled CUDA libs in the manylinux wheel; `faster-whisper` only depends on `ctranslate2`, `av`, `tokenizers`, `onnxruntime`. The whisper transcription path is torch-independent.
3. **`audiobox-aesthetics 0.0.4` has unpinned `torch`/`torchaudio`.** Accepts any version. So scoring's torch version is not pinned by audiobox — it's pinned by our `pyproject.toml` extras (`torch>=2.2,<3`).
4. **Music-worker's import chain works without torch.** [src/songmaker_cli/jobs.py:51-52](../src/songmaker_cli/jobs.py#L51-L52) imports `PipelineConfig` and `get_scorer_process` at module load. Both come through `songmaker_cli.scoring.{pipeline,subprocess_runner}`. Neither imports torch at module level — `pipeline.py` uses `TYPE_CHECKING` for numpy and only imports stdlib + dataclasses + parser/models; `subprocess_runner.py` (the scoring one, line 69 and 94) imports `torch` only **inside** functions, lazily, at the moment a scorer subprocess is spawned. **Music-worker only registers `[generate, load_model_on_worker, download_model_on_worker]`** ([src/songmaker_cli/music_worker.py:87](../src/songmaker_cli/music_worker.py#L87)) — it never registers `run_scoring_job`, never calls `get_scorer_process()`, and therefore never triggers a torch import at runtime. **Conclusion:** music-worker can run with `--extra server` only; the `songmaker_cli.scoring` package on the Python path is enough for the import chain to succeed.
5. **The upstream ACE-Step `pyproject.toml` uses a custom `[[tool.uv.index]] pytorch-cu128` and a path source `nano-vllm = { path = "acestep/third_parts/nano-vllm" }`** ([_models/acestep/pyproject.toml:60-91](../_models/acestep/pyproject.toml#L60-L91)). This stays self-contained inside the `acestep-base` image build (where `uv sync` runs against the upstream lockfile from inside `/opt/acestep`). It does **not** leak into the root `pyproject.toml`.
6. **Upstream `_get_project_root() = dirname(dirname(__file__))`** of `acestep/api_server.py` ([_models/acestep/acestep/api_server.py:100-102](../_models/acestep/acestep/api_server.py#L100-L102)), then joined with `"checkpoints"` ([_models/acestep/acestep/api/startup_model_init.py:64](../_models/acestep/acestep/api/startup_model_init.py#L64)) and `"examples"` (api_server.py:135-136) at module-import time. **The upstream is hard-coded to be run from a source tree, not from an installed wheel.** This is why `acestep-base` must COPY the entire upstream source into `/opt/acestep` and run `uv sync` there in editable mode — installing as a wheel into site-packages would make `_get_project_root()` resolve to site-packages, where neither `checkpoints/` nor `examples/` exists.
7. **`.dockerignore` excludes `_models/` entirely** ([.dockerignore:8](../.dockerignore#L8)). C1 must allowlist the upstream source (but not `.venv/`, `checkpoints/`, `.git/`, host runtime artifacts) to make it visible to the `acestep-base` build context.
8. **`_models/acestep/` content audit:** `acestep/` (14 MB upstream Python source — needed), `checkpoints/` (83 GB weights — bind-mounted, never copied), `.venv/` (84K broken host shim — excluded), `.git/` (~50 MB host clone state — excluded), `pyproject.toml`/`uv.lock`/`README.md` (needed by uv sync), `examples/` (loaded by api_server at import time — needed), `openrouter/` (in hatch build packages — needed), plus `assets/`, `ui/`, `scripts/`, `docs/`, various scripts — small enough to copy with a directory-level COPY plus heavy excludes rather than precise allowlisting.
9. **`Dockerfile.worker` is referenced from exactly two places in non-doc files**: [docker-compose.yml:93](../docker-compose.yml#L93) (music-worker) and [docker-compose.yml:163](../docker-compose.yml#L163) (scoring-worker). Once both compose entries are migrated to the new dockerfiles, `Dockerfile.worker` can be deleted in the same commit. (Plan files also reference it, but those are historical.)
10. **`scripts/download_models.sh` is referenced from CLAUDE.md** for downloading ACE-Step weights. After C1 the download path is unchanged — weights still land at `_models/acestep/checkpoints/` on the host, still bind-mounted into the `acestep-worker` container. No script change needed.

## Decision matrix (locked: C1)

| Concern | A (single shared venv) | B (two venvs, both baked) | **C1 (this plan)** | C2 (C1 + torch unification) |
|---|---|---|---|---|
| Fixes venv clobber | ✅ | ✅ | ✅ | ✅ |
| Diff size | medium-large | medium | **large** | very large |
| Risk: dep conflicts in wrapper extra | high | low | **low** | medium |
| Risk: scoring regressions | low | low | **low** | medium-high (audiobox+torch 2.10 unverified) |
| Risk: dockerfile-shared regression | n/a | n/a | **medium** (splitting Dockerfile.worker exposes any hidden assumption that scoring/music share a stack) | medium |
| Build orchestration | none | none | **NEW build script** | NEW build script |
| Music-worker bloat fix (~5 GB → ~500 MB) | no | no | **yes** | yes |
| Phase 7 D1 done | no | no | **yes** | yes |
| Reusable `acestep-base` layer | no | no | **yes** | yes |
| Implementation time | 2-3h | 2-3h | **6-10h** | 8-12h |

**Picked: C1.** Rejected:
- **A**: structurally blocked by upstream's custom torch index, `nano-vllm` path source, and `_get_project_root()` source-tree assumption (parent plan's verified mechanism).
- **B**: minimum viable fix, but leaves Phase 7 D1 undone and the music-worker on the bloated shared `Dockerfile.worker`.
- **C2**: torch unification buys symbolic consistency for real risk; scoring is CPU-only so the unification has zero functional payoff.

## Architecture: build orchestration

`docker compose build` doesn't natively express "build base image, THEN build leaf images that `FROM` it." Compose's `build:` blocks are processed in parallel. Three options for handling this:

1. **`scripts/build_images.sh`** — plain shell script: build bases with `docker build`, then run `docker compose build` for the leaves. **Picked.** Simplest, reviewable, no new tools.
2. `docker buildx bake` with a `bake.hcl` declaring the dependency graph. Modern, but adds buildx as a hard dep and changes the dev workflow.
3. Multi-stage builds that inline the base into each leaf Dockerfile. Defeats the "named reusable base" point.

The script:
```bash
#!/usr/bin/env bash
# scripts/build_images.sh
# Build the songmaker image hierarchy in dependency order, then build the
# docker compose leaf services that depend on the bases.
#
# Usage:
#   scripts/build_images.sh           # build everything (bases + leaves)
#   scripts/build_images.sh bases     # build base images only
#   scripts/build_images.sh leaves    # build compose leaves only (assumes bases exist)

set -euo pipefail

cd "$(dirname "$0")/.."

build_bases() {
    echo ">>> Building gpu-torch-base..."
    docker build \
        -f docker/base/gpu-torch-base.Dockerfile \
        -t songmaker/gpu-torch-base:latest \
        .

    echo ">>> Building acestep-base..."
    docker build \
        -f docker/base/acestep-base.Dockerfile \
        -t songmaker/acestep-base:latest \
        .
}

build_leaves() {
    echo ">>> Building compose leaf services..."
    docker compose build
}

case "${1:-all}" in
    bases) build_bases ;;
    leaves) build_leaves ;;
    all) build_bases && build_leaves ;;
    *) echo "Unknown target: $1"; exit 1 ;;
esac
```

The new documented workflow becomes:
```bash
scripts/build_images.sh && timeout 120 docker compose up -d --wait
```

**CLAUDE.md update:** the existing "Always use `--wait` with `docker compose up -d`" guidance ([CLAUDE.md "Docker" section](../CLAUDE.md#docker)) needs a one-line addition: "If you've changed any Dockerfile in `docker/base/`, run `scripts/build_images.sh` first." Otherwise compose will fail with `manifest unknown` for the `FROM songmaker/acestep-base:latest` line.

## Concrete diffs

### `pyproject.toml`

**No change.** C1 explicitly does not unify torch versions. The wrapper extras stay exactly as they are.

### `uv.lock`

**No change.** Same reason.

### `.dockerignore`

Replace the blanket `_models/` exclude with precise excludes for the host-only artifacts. The upstream ACE-Step source must be visible to the `acestep-base` build context.

```diff
-# ACE-Step (mounted as volume, not copied)
-_models/
+# ACE-Step source tree is COPYed into the acestep-base image at /opt/acestep so
+# the inner subprocess venv can be baked at build time. Only host-runtime
+# artifacts and the heavy weights are excluded; weights are bind-mounted at
+# runtime by the acestep-worker leaf service.
+_models/acestep/.venv/
+_models/acestep/.git/
+_models/acestep/.cache/
+_models/acestep/checkpoints/
+_models/acestep/gradio_outputs/
+_models/acestep/manual_uv_sync.log
+_models/acestep/acestep-*.stderr.log
+_models/acestep/acestep_stderr.log
```

### `docker/base/gpu-torch-base.Dockerfile` (NEW)

```dockerfile
# songmaker/gpu-torch-base:latest
#
# CUDA-enabled torch base image. Pre-creates the venv at /opt/acestep/.venv
# with torch 2.10.0+cu128 + torchvision + torchaudio installed from the
# upstream PyTorch index. Downstream `acestep-base` COPYs the upstream source
# tree on top, then runs `uv sync --frozen` against the upstream lockfile —
# which sees the existing venv with torch already installed and only installs
# the delta (diffusers/transformers/nano-vllm/gradio/etc).
#
# This is the heavy layer (~6-7 GB after install). Anything downstream stays
# light so the cache survives unrelated changes.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN useradd --create-home --shell /bin/bash songmaker
RUN install -d -o songmaker -g songmaker /opt/acestep

USER songmaker
WORKDIR /opt/acestep

# Pre-create the venv at the path acestep-base will COPY the upstream source
# into. Downstream `uv sync` discovers /opt/acestep/.venv, sees torch already
# installed at the upstream-pinned version, and only installs the delta deps.
RUN uv venv --python 3.12 .venv \
    && uv pip install --python .venv \
        --index-url https://download.pytorch.org/whl/cu128 \
        torch==2.10.0+cu128 \
        torchvision==0.25.0+cu128 \
        torchaudio==2.10.0+cu128

ENV ACESTEP_SRC_DIR=/opt/acestep
ENV PYTHONUNBUFFERED=1
```

**Honest framing on cross-image dedup:** Docker doesn't dedup bytes across unrelated images at the file level. The benefit of `gpu-torch-base` is **build-time layer cache reuse on rebuilds** — when only `_models/acestep/acestep/*.py` changes, the torch layer in `gpu-torch-base` stays cached and downstream rebuilds skip the multi-GB torch reinstall. The runtime image size of `acestep-worker` is unchanged versus Option B; what changes is rebuild speed and architectural cleanliness. This is documented honestly in the parent plan's update note (see Branching section below).

### `docker/base/acestep-base.Dockerfile` (NEW)

```dockerfile
# songmaker/acestep-base:latest
FROM songmaker/gpu-torch-base:latest

USER songmaker
WORKDIR /opt/acestep

# Layer 1: lockfile + manifest only — caches independently of source churn.
COPY --chown=songmaker _models/acestep/pyproject.toml _models/acestep/uv.lock _models/acestep/README.md ./

# Layer 2: nano-vllm path-source dep — required for `uv sync` to resolve.
COPY --chown=songmaker _models/acestep/acestep/third_parts/ ./acestep/third_parts/

# Layer 3: heavy delta install. torch is already installed in the inherited
# venv at the upstream-pinned 2.10.0+cu128, so this only pulls the missing
# pieces (diffusers, transformers, gradio, peft, nano-vllm, etc.). The
# --no-install-project flag defers the editable project install to layer 5.
RUN uv sync --frozen --no-dev --no-install-project

# Layer 4: full upstream source. Invalidates only on upstream source edits.
COPY --chown=songmaker _models/acestep/ ./

# Layer 5: editable install of the upstream project so the `acestep-api`
# entry point exists and `_get_project_root()` resolves to /opt/acestep at
# runtime.
RUN uv sync --frozen --no-dev

ENV HF_HUB_DISABLE_XET=1
```

### `docker/acestep-worker.Dockerfile` (REWRITE)

```dockerfile
# songmaker-acestep-worker — leaf image
FROM songmaker/acestep-base:latest

USER songmaker
WORKDIR /app

# Wrapper venv at /app/.venv installs only fastapi/uvicorn/redis/huggingface_hub
# from the songmaker root pyproject's `acestep-worker` extra. This venv is
# completely independent from /opt/acestep/.venv (different concerns: HTTP
# wrapper vs ACE-Step model subprocess). The wrapper image stays small.
COPY --chown=songmaker pyproject.toml uv.lock ./
RUN mkdir -p src/acestep_worker && touch src/acestep_worker/__init__.py && \
    uv sync --frozen --no-dev --extra acestep-worker && \
    rm -rf src/acestep_worker/__init__.py

COPY --chown=songmaker src/acestep_engine/ src/acestep_engine/
COPY --chown=songmaker src/acestep_worker/ src/acestep_worker/
RUN uv sync --frozen --no-dev --extra acestep-worker

ENTRYPOINT ["uv", "run", "python", "-m", "acestep_worker"]
```

### `docker/music-worker.Dockerfile` (NEW — replaces `Dockerfile.worker` for music)

```dockerfile
# songmaker-music-worker — minimal arq worker, no torch, no scoring/whisper
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

RUN useradd --create-home --shell /bin/bash songmaker
RUN chown songmaker:songmaker /app
USER songmaker

COPY --chown=songmaker pyproject.toml uv.lock ./
RUN mkdir -p src/songmaker_cli && touch src/songmaker_cli/__init__.py && \
    uv sync --frozen --no-dev --extra server && \
    rm -rf src/songmaker_cli/__init__.py

COPY --chown=songmaker src/ src/
COPY --chown=songmaker alembic.ini ./
RUN uv sync --frozen --no-dev --extra server

ENTRYPOINT ["uv", "run", "arq"]
```

**Why this is safe:** music-worker only registers `[generate, load_model_on_worker, download_model_on_worker]` ([src/songmaker_cli/music_worker.py:87](../src/songmaker_cli/music_worker.py#L87)). It never invokes `run_scoring_job` or `get_scorer_process()`. The `from songmaker_cli.scoring.{pipeline,subprocess_runner} import ...` lines in [jobs.py:51-52](../src/songmaker_cli/jobs.py#L51-L52) succeed without torch because neither module imports torch at module load (verified — `pipeline.py` only pulls stdlib + parser + models; scoring `subprocess_runner.py` imports torch lazily inside functions at lines 69, 94, 102).

### `docker/scoring-worker.Dockerfile` (NEW — replaces `Dockerfile.worker` for scoring)

```dockerfile
# songmaker-scoring-worker — arq worker with scoring + whisper extras
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

RUN useradd --create-home --shell /bin/bash songmaker
RUN chown songmaker:songmaker /app
USER songmaker

COPY --chown=songmaker pyproject.toml uv.lock ./
RUN mkdir -p src/songmaker_cli && touch src/songmaker_cli/__init__.py && \
    uv sync --frozen --no-dev --extra server --extra scoring --extra whisper && \
    rm -rf src/songmaker_cli/__init__.py

ENV HF_HUB_CACHE=/app/.cache/huggingface/hub
RUN --mount=type=secret,id=hf_token,env=HF_TOKEN uv run python -c "\
from faster_whisper import WhisperModel; \
WhisperModel('large-v3', device='cpu', compute_type='int8')"
RUN --mount=type=secret,id=hf_token,env=HF_TOKEN uv run python -c "\
from audiobox_aesthetics.infer import AesPredictor; \
import os; os.environ['CUDA_VISIBLE_DEVICES'] = ''; \
AesPredictor(checkpoint_pth='default')"

COPY --chown=songmaker src/ src/
COPY --chown=songmaker alembic.ini ./
RUN uv sync --frozen --no-dev --extra server --extra scoring --extra whisper

ENTRYPOINT ["uv", "run", "arq"]
```

This is `Dockerfile.worker` verbatim with two changes: (1) the comment header is updated from "GPU worker: runs arq + manages ACE-Step subprocess" (no longer accurate post-Phase 3 cutover), (2) it lives at `docker/scoring-worker.Dockerfile` instead of the repo root.

### `Dockerfile.worker` — DELETE

After both new dockerfiles land and compose is updated to reference them, delete the old shared file. Verify with `grep -rn "Dockerfile.worker" --include='*.yml' --include='*.yaml' --include='*.sh' --include='*.py'` that there are zero remaining non-doc references.

### `scripts/build_images.sh` (NEW)

```bash
#!/usr/bin/env bash
# Build the songmaker image hierarchy in dependency order, then build the
# docker compose leaf services that depend on the bases.
#
# Usage:
#   scripts/build_images.sh           # build everything (bases + leaves)
#   scripts/build_images.sh bases     # build base images only
#   scripts/build_images.sh leaves    # build compose leaves only

set -euo pipefail

cd "$(dirname "$0")/.."

build_bases() {
    echo ">>> Building songmaker/gpu-torch-base..."
    docker build \
        -f docker/base/gpu-torch-base.Dockerfile \
        -t songmaker/gpu-torch-base:latest \
        .

    echo ">>> Building songmaker/acestep-base..."
    docker build \
        -f docker/base/acestep-base.Dockerfile \
        -t songmaker/acestep-base:latest \
        .
}

build_leaves() {
    echo ">>> Building docker compose leaf services..."
    docker compose build
}

case "${1:-all}" in
    bases)  build_bases ;;
    leaves) build_leaves ;;
    all)    build_bases && build_leaves ;;
    *)      echo "Unknown target: $1"; exit 1 ;;
esac
```

`chmod +x scripts/build_images.sh` after creation.

### `docker-compose.yml` — three service blocks change

```diff
   songmaker-music-worker:
     build:
       context: .
-      dockerfile: Dockerfile.worker
-      secrets:
-        - hf_token
+      dockerfile: docker/music-worker.Dockerfile
     command: ["songmaker_cli.music_worker.MusicWorkerSettings"]
```

```diff
   songmaker-acestep-worker-0:
     build:
       context: .
       dockerfile: docker/acestep-worker.Dockerfile
     restart: unless-stopped
     ...
     environment:
       ...
-      ACESTEP_CHECKPOINT_DIR: "/app/_models/acestep"
+      ACESTEP_CHECKPOINT_DIR: "/opt/acestep"
       AUDIO_OUTPUT_DIR: "/app/data/audio/worker_output"
-      ACESTEP_LOG_DIR: "/app/_models/acestep"
+      ACESTEP_LOG_DIR: "/opt/acestep/logs"
       ...
     volumes:
-      - ./_models/acestep:/app/_models/acestep
+      - ./_models/acestep/checkpoints:/opt/acestep/checkpoints
       - audiofiles:/app/data/audio
```

```diff
   songmaker-scoring-worker:
     build:
       context: .
-      dockerfile: Dockerfile.worker
+      dockerfile: docker/scoring-worker.Dockerfile
       secrets:
         - hf_token
     command: ["songmaker_cli.scoring_worker.ScoringWorkerSettings"]
```

The `secrets` block stays on scoring-worker (it needs HF_TOKEN to preload whisper + audiobox at build time). Music-worker no longer needs it.

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

### `src/acestep_worker/subprocess_runner.py`

**No code change.** The existing `cwd=checkpoint_dir` plumbing is exactly right once `checkpoint_dir` resolves to `/opt/acestep`. The `uv run acestep-api` invocation finds `/opt/acestep/.venv` (baked, populated, owned by songmaker) and skips the resync entirely. This is the venv-clobber fix.

### `tests/acestep_worker/test_subprocess_runner.py` — add cwd invariant test

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

### `.env` — drop the workaround

```diff
-ARQ_JOB_TIMEOUT=1800
+# ARQ_JOB_TIMEOUT removed — defaults to 300s after Phase 8. See
+# plans/acestep-worker-pool-phase8-subplan.md.
```

### `CLAUDE.md` — update the Docker section

Add one line to the existing Docker section:

```diff
 ## Docker

 Always use `--wait` with `docker compose up -d` but wrap it in `timeout` ...

+If you've changed any Dockerfile under `docker/base/`, run
+`scripts/build_images.sh` first to rebuild the base images. Otherwise compose
+will fail with `manifest unknown` for `FROM songmaker/acestep-base:latest`.
```

## Files Touched

| File | Change |
|---|---|
| `.dockerignore` | Replace `_models/` with precise excludes (`.venv/`, `.git/`, `checkpoints/`, host runtime artifacts) |
| `docker/base/gpu-torch-base.Dockerfile` | NEW — torch 2.10+cu128 venv at `/opt/acestep/.venv` |
| `docker/base/acestep-base.Dockerfile` | NEW — upstream ACE-Step source + delta deps install |
| `docker/acestep-worker.Dockerfile` | REWRITE — `FROM songmaker/acestep-base:latest`, adds wrapper venv + entry point |
| `docker/music-worker.Dockerfile` | NEW — replaces `Dockerfile.worker` for music; server extras only |
| `docker/scoring-worker.Dockerfile` | NEW — replaces `Dockerfile.worker` for scoring; server + scoring + whisper |
| `Dockerfile.worker` | DELETE (after compose is migrated) |
| `scripts/build_images.sh` | NEW + chmod +x; orchestrates base→leaf builds |
| `docker-compose.yml` | Music + scoring services point to new dockerfiles; acestep service env paths + bind mount narrowed |
| `src/acestep_worker/__main__.py` | `DEFAULT_CHECKPOINT_DIR` → `/opt/acestep`; `DEFAULT_LOG_DIR` → `/opt/acestep/logs` |
| `tests/acestep_worker/test_subprocess_runner.py` | Add `test_start_acestep_subprocess_uses_cwd` invariant test |
| `.env` | Remove `ARQ_JOB_TIMEOUT=1800` workaround |
| `CLAUDE.md` | One-line addition to the Docker section about the new build script |
| `plans/acestep-worker-pool.md` | (Optional, end of phase) Mark Phase 8 status as DONE |
| `docs/acestep.md` | (Optional, end of phase) Note new image hierarchy |

**Not touched (per "things to NOT do"):** `pyproject.toml`, `uv.lock`, `model_cache.py`, heartbeat schema, scheduler, admin endpoints, frontend, alembic, web `Dockerfile`, `subprocess_runner.py` source.

## Implementation order with HARD checkpoints

### Step 1 — Pre-flight
- `git status` — confirm clean working tree.
- `unset VIRTUAL_ENV && uv run ruff check src/ tests/` — baseline must pass.
- `docker compose down -v` — clear any cached state from previous attempts.
- Verify host has `_models/acestep/{pyproject.toml,uv.lock,acestep/third_parts/nano-vllm/}` (already verified during exploration).

### Step 2 — `.dockerignore` first
- Edit `.dockerignore` per the diff above.
- **HARD checkpoint:** `du -sh $(git ls-files _models/acestep/ 2>/dev/null) 2>/dev/null | tail -1` — ensure the to-be-COPYed surface is reasonable. Or simply build the gpu-torch-base in step 3 and observe the build context size in the `transferring context: ` line — should be ~150 MB (upstream source minus checkpoints/.venv/.git).

### Step 3 — Create the base images
- Create `docker/base/` directory.
- Write `docker/base/gpu-torch-base.Dockerfile`.
- Write `docker/base/acestep-base.Dockerfile`.
- **HARD checkpoint A:** `timeout 1500 docker build -f docker/base/gpu-torch-base.Dockerfile -t songmaker/gpu-torch-base:latest . --progress=plain 2>&1 | tee /tmp/phase8-gpu-base.log`
  - Expected: completes in 5-15 min (multi-GB torch + cudnn download). Look for `Successfully tagged songmaker/gpu-torch-base:latest`.
  - Verify the venv: `docker run --rm songmaker/gpu-torch-base:latest /opt/acestep/.venv/bin/python -c "import torch; print(torch.__version__)"` should print `2.10.0+cu128`.
- **HARD checkpoint B:** `timeout 1500 docker build -f docker/base/acestep-base.Dockerfile -t songmaker/acestep-base:latest . --progress=plain 2>&1 | tee /tmp/phase8-acestep-base.log`
  - Expected: completes in 5-15 min on top of gpu-torch-base. Most of the time is spent installing diffusers/transformers/peft/nano-vllm/gradio.
  - Specifically grep the log for `error: distribution` (uv conflict signature) and `Failed to fetch`.
  - Verify the entry point exists: `docker run --rm songmaker/acestep-base:latest ls /opt/acestep/.venv/bin/acestep-api`.
  - Verify `_get_project_root()` resolves correctly: `docker run --rm songmaker/acestep-base:latest /opt/acestep/.venv/bin/python -c "import os, acestep.api_server as a; print(os.path.dirname(os.path.dirname(a.__file__)))"` should print `/opt/acestep`.

### Step 4 — Rewrite the leaf dockerfiles
- Rewrite `docker/acestep-worker.Dockerfile` to `FROM songmaker/acestep-base:latest`.
- Write `docker/music-worker.Dockerfile`.
- Write `docker/scoring-worker.Dockerfile`.
- **DO NOT delete `Dockerfile.worker` yet.** Keep it until compose is migrated and the new dockerfiles all build cleanly.
- **HARD checkpoint:** `docker build -f docker/acestep-worker.Dockerfile -t songmaker-acestep-worker:dev . --progress=plain 2>&1 | tail -30` — should be very fast (just the wrapper extras install on top of acestep-base).
- **HARD checkpoint:** `docker build -f docker/music-worker.Dockerfile -t songmaker-music-worker:dev . --progress=plain 2>&1 | tail -30` — should complete in 1-2 min (small wrapper, no torch).
- **HARD checkpoint:** `docker build -f docker/scoring-worker.Dockerfile --secret id=hf_token,env=HF_TOKEN -t songmaker-scoring-worker:dev . --progress=plain 2>&1 | tail -30` — should complete in 5-10 min (whisper + audiobox model preload).

### Step 5 — Build orchestration script
- Write `scripts/build_images.sh` per the listing above.
- `chmod +x scripts/build_images.sh`.
- **HARD checkpoint:** `scripts/build_images.sh leaves` runs cleanly and re-builds the compose leaves using the cached bases (no multi-GB redownload).

### Step 6 — Compose migration
- Edit `docker-compose.yml` for music-worker, scoring-worker, acestep-worker per the diffs.
- Edit `src/acestep_worker/__main__.py` defaults.
- Edit `.env` to remove `ARQ_JOB_TIMEOUT=1800`.
- Edit `CLAUDE.md` Docker section.
- **HARD checkpoint:** `unset VIRTUAL_ENV && uv run ruff check src/ tests/` passes.

### Step 7 — Delete the old shared file
- `git rm Dockerfile.worker`
- **HARD checkpoint:** `grep -rn "Dockerfile.worker" --include='*.yml' --include='*.yaml' --include='*.sh' --include='*.py'` returns nothing. Plan files still reference it (historical) — that's fine and intentional.

### Step 8 — Test addition + suite
- Add `test_start_acestep_subprocess_uses_cwd` to `tests/acestep_worker/test_subprocess_runner.py`.
- **HARD checkpoint:** `unset VIRTUAL_ENV && uv run pytest tests/acestep_worker/ -q` passes.
- **HARD checkpoint:** `unset VIRTUAL_ENV && uv run pytest tests/ -q --ignore=tests/test_scorers.py --ignore=tests/test_scorers_extended.py` passes (full suite minus GPU scoring tests).

### Step 9 — Frontend smoke (defensive)
- `cd frontend && pnpm check && pnpm lint && pnpm test` — Phase 8 doesn't touch frontend, but run anyway to catch any compose env var rename ripple effect.

### Step 10 — End-to-end smoke test (THE deliverable)
- `docker compose down -v`
- `scripts/build_images.sh` (full bases + leaves rebuild from a clean state)
- `timeout 600 docker compose up -d --wait songmaker-acestep-worker-0 songmaker-music-worker songmaker-scoring-worker songmaker-web`
- **HARD checkpoint:** all four containers report healthy within 60 s. Diagnose any that don't with `docker compose logs <name> --tail 100`.
- **HARD checkpoint (THE checkpoint for this phase):**
  ```
  time docker compose exec songmaker-acestep-worker-0 \
    curl -X POST -H 'Content-Type: application/json' \
    -d '{"mode":"sft"}' http://localhost:8001/load_model
  ```
  Expected: returns `{"status":"ok",...}` in **<90 seconds wall-clock**, down from 5+ minutes pre-fix. If still slow, check `docker compose exec songmaker-acestep-worker-0 ls /opt/acestep/.venv/lib/python3.12/site-packages/torch` — if missing, the bind mount or COPY ordering broke.
- **HARD checkpoint:** Redis heartbeat:
  ```
  docker compose exec redis redis-cli GET 'songmaker:acestep:worker:acestep-worker-0'
  ```
  Should show `"loaded":[{"mode":"sft","size_gb":6.0}]` within 5 s.
- **HARD checkpoint (Phase 6 PR 2 D6 regression):** with sft loaded, start a real generation against sft from the main UI. While it's running, click Load → xl-base in the admin tab. Expected: load fails with `"all eligible models are in use or pinned"` and the running generation completes unharmed.
- **HARD checkpoint (scoring smoke — proves the scoring split didn't break anything):** after the generation completes, verify scoring runs against it (the existing post-generation scoring path). Watch `docker compose logs songmaker-scoring-worker --tail 50` for `Scoring complete` or equivalent. If scoring fails, the new scoring-worker dockerfile is broken — diagnose before committing.
- **HARD checkpoint (music-worker smoke — proves the torch removal didn't break anything):** the generation in the previous step is what exercises music-worker. If it succeeded, music-worker imports cleanly without torch on the path. Confirm via `docker compose logs songmaker-music-worker --tail 50` showing the job state transitions.

If all checkpoints pass: commit + push. If any fails: diagnose and fix in the same commit.

## Test strategy

- **Unit tests:** the existing `tests/acestep_worker/` suite is unchanged structurally — `subprocess_runner.py`'s function signatures don't change, so all existing tests pass. The one new test is the cwd-invariant test (above).
- **CI tests excluded from run:** `test_scorers.py` and `test_scorers_extended.py` stay excluded per CLAUDE.md (require GPU extras locally). Phase 8's scoring smoke is the live container running a real scoring job, not the unit test files.
- **Frontend tests:** unchanged, run for defensive coverage only.
- **Integration coverage gap:** there is no automated test that asserts "music-worker can import jobs.py without torch installed." The smoke test (step 10) is the integration test for that property. If it regresses in a future change, the smoke test catches it. Adding a unit test for this would require a separate Python venv without torch — disproportionate effort for a one-shot guarantee that the dockerfile bakes in.

## Smoke test plan (recap with wall-clock expectations)

| Step | Command | Expected wall-clock (cold) |
|---|---|---|
| 1 | `docker compose down -v` | <10 s |
| 2 | `scripts/build_images.sh` from clean state | 20-40 min (multi-GB torch + cudnn + diffusers download, one-time) |
| 3 | `timeout 600 docker compose up -d --wait songmaker-acestep-worker-0 songmaker-music-worker songmaker-scoring-worker songmaker-web` | 1-3 min (containers start; scoring-worker has 120 s `start_period`) |
| 4 | `docker compose ps` — confirm four containers `(healthy)` | n/a |
| 5 | Load → sft from admin UI | **<90 s wall-clock** (THE gate; down from 5+ min pre-fix) |
| 6 | `redis-cli GET 'songmaker:acestep:worker:acestep-worker-0'` shows `loaded:[{sft,...}]` | <5 s after step 5 |
| 7 | Start a real generation against sft | 30-90 s |
| 8 | While step 7 runs, click Load → xl-base | Should fail immediately with "all eligible models are in use or pinned" (Phase 6 D6) |
| 9 | Confirm step 7's generation completes unharmed | n/a |
| 10 | Confirm post-generation scoring runs (logs in scoring-worker) | 10-30 s after generation completes |

Total cold smoke test wall clock: **~30-50 minutes** (dominated by the one-time base image builds). Subsequent runs from cached bases: **~5 minutes**.

## Self-review checklist

- [ ] `pyproject.toml` and `uv.lock` are **unchanged** (no torch unification — C1, not C2)
- [ ] `gpu-torch-base` venv at `/opt/acestep/.venv` contains `torch==2.10.0+cu128`
- [ ] `acestep-base` `_get_project_root()` resolves to `/opt/acestep`
- [ ] `acestep-worker` leaf is small (<50 MB on top of `acestep-base`)
- [ ] `music-worker` image has no torch — `docker run --rm songmaker-music-worker:dev uv run python -c "import torch"` should fail with `ModuleNotFoundError`
- [ ] `scoring-worker` image still loads whisper + audiobox at build time (the secret-mounted RUN steps)
- [ ] `Dockerfile.worker` deleted; no non-doc references remain
- [ ] `subprocess_runner.py` unchanged
- [ ] Bind mount in compose narrowed to `./_models/acestep/checkpoints:/opt/acestep/checkpoints`
- [ ] `ACESTEP_CHECKPOINT_DIR` and `ACESTEP_LOG_DIR` env vars updated in compose
- [ ] `__main__.py` defaults updated
- [ ] `.env` no longer has `ARQ_JOB_TIMEOUT=1800`
- [ ] CLAUDE.md Docker section mentions `scripts/build_images.sh`
- [ ] `scripts/build_images.sh` is executable
- [ ] All ruff/pytest/pnpm checks pass
- [ ] Smoke test loads sft in <90 s
- [ ] Phase 6 D6 race regression check passes
- [ ] Scoring smoke (post-generation scoring runs) passes
- [ ] No frontend, scheduler, model_cache, heartbeat, or admin_api files touched

## Watchpoints

1. **`uv sync` in `acestep-base` failing with conflict error.** The upstream `uv.lock` is pinned (`--frozen`), so this should be deterministic. If it fails, run `(cd _models/acestep && uv lock --check)` on the host first to confirm the lockfile matches its pyproject. Common failure: a recent host edit to `_models/acestep/pyproject.toml` without re-locking.
2. **The `nano-vllm` path source.** The Dockerfile copies `_models/acestep/acestep/third_parts/` before the first `uv sync`. If `_models/acestep/acestep/third_parts/nano-vllm/pyproject.toml` doesn't exist, `uv sync` fails with "package not found." Verify with `find _models/acestep/acestep/third_parts/nano-vllm -name pyproject.toml` before building.
3. **Bind mount narrowing breaking another path.** The upstream code's only references to paths joined with `_get_project_root()` are `examples/` (loaded at module import → satisfied by the COPYed source) and `checkpoints/` (resolved at runtime → satisfied by the narrowed bind mount). If a real generation triggers `FileNotFoundError` for some other subdirectory, re-add it via the COPY.
4. **`/opt/acestep/logs` write permissions.** `/opt/acestep` is owned by `songmaker` so the subprocess runner's `log_dir.mkdir(parents=True, exist_ok=True)` should succeed. Symptom of failure: subprocess starts but `acestep-sft.stderr.log` is empty.
5. **Music-worker hidden torch import.** Surprise discovery (#4 above) confirmed today's import chain is torch-free, but a future PR could add a top-level torch import to `jobs.py` or any module on the path and break music-worker silently. The smoke test (step 10) catches this if it ever happens. A defensive guard would be a CI test that creates a torch-free venv and imports `songmaker_cli.music_worker` — out of scope for Phase 8.
6. **`docker compose build` running without the bases existing.** If a contributor runs `docker compose up --build` without first running `scripts/build_images.sh`, the compose build fails with `manifest unknown` for `FROM songmaker/acestep-base:latest`. The CLAUDE.md update is the documentation fix; a more robust fix would be a compose build hook, which compose doesn't natively support.
7. **Build orchestration in CI.** Phase 8 explicitly does not add image building to CI (CI runs unit tests against source, not built images). If Phase 9+ adds image-build CI, it must call `scripts/build_images.sh` first.
8. **Layer cache invalidation cascade.** Editing `docker/base/gpu-torch-base.Dockerfile` invalidates `acestep-base` and `acestep-worker`. Editing `docker/base/acestep-base.Dockerfile` invalidates only `acestep-base` and `acestep-worker`. Editing the wrapper extras in root `pyproject.toml` invalidates only the leaf `acestep-worker.Dockerfile`. Any iteration loop should touch the lowest layer that needs to change.
9. **`Dockerfile.worker` deletion happens in the same commit.** The single C1 commit must include the file deletion alongside the new dockerfiles and the compose migration. If split, an intermediate commit has compose pointing at deleted dockerfiles or vice versa.
10. **`ARQ_JOB_TIMEOUT` rollback ordering.** Same constraint as Option B — must land in the same commit as the venv fix per parent plan decision #6.

## Rollback plan

If the new image hierarchy has a regression that survives the smoke test gate, the recovery path is:

1. `git revert <commit-sha>` — single commit, clean revert (Dockerfile.worker resurrected, compose restored, `__main__.py` defaults reverted, `.env` workaround restored)
2. `scripts/build_images.sh` — but the script itself was reverted, so revert leaves the working copy without bases. **Fallback:** `docker compose build` directly uses `Dockerfile.worker` once again, no bases needed.
3. Restore `ARQ_JOB_TIMEOUT=1800` in `.env` if not already restored by the revert

The host bind mount `_models/acestep/checkpoints/` is unchanged structurally — the model weights stay put across revert. No data migration. No `down -v` required.

## What is NOT in Phase 8 (deferred)

- **C2 — torch unification across the codebase.** Explicitly rejected — C1 keeps scoring on its current torch stack.
- **Image registry pushes (GHCR, semver tagging).** Local-only base image builds for the first cut. Defer to a later phase.
- **CI image building.** CI continues to run pytest against source.
- **`scoring-base` named image.** Single consumer today, no reuse story. Extract when there's a second consumer.
- **Multi-host worker deployment.** Parent plan known tech debt.
- **Pinning the upstream ACE-Step version (host clone may be stale).** Future phase candidate.
- **Replacing `subprocess_runner.find_uv()` with a hardcoded path now that `uv` is reliably at `/usr/local/bin/uv` in the bases.** Out of scope for Phase 8.

## Branching + commits

**Single backend commit.** This is one logical change: the image hierarchy refactor + venv fix + `Dockerfile.worker` split + workaround rollback. Splitting it would leave intermediate commits in a half-broken state.

Suggested commit message:

```
feat(phase8): image hierarchy refactor — gpu-torch-base + acestep-base, split Dockerfile.worker

- New base images: songmaker/gpu-torch-base (torch 2.10+cu128 venv at
  /opt/acestep/.venv) and songmaker/acestep-base (upstream ACE-Step source
  + delta deps install). Reusable for any future cu128 GPU worker.
- acestep-worker.Dockerfile rewritten as a thin leaf FROM acestep-base.
  The inner ACE-Step venv is now baked at /opt/acestep/.venv at image
  build time — no more 5+ minute uv sync on every fresh container start.
- Dockerfile.worker split into docker/music-worker.Dockerfile (server
  extras only, no torch — image goes from ~5 GB to ~500 MB) and
  docker/scoring-worker.Dockerfile (server + scoring + whisper).
  Dockerfile.worker deleted. Closes Phase 7 D1.
- docker-compose.yml: bind mount narrowed from ./_models/acestep
  to ./_models/acestep/checkpoints. ACESTEP_CHECKPOINT_DIR moves to
  /opt/acestep, ACESTEP_LOG_DIR to /opt/acestep/logs.
- .env: drop ARQ_JOB_TIMEOUT=1800 workaround — model load is now <90s,
  well within the documented 300s default.
- New scripts/build_images.sh orchestrates base→leaf builds.
- No pyproject.toml or uv.lock changes — torch versions stay separate
  per workload (acestep cu128, scoring CPU PyPI). C1, not C2.

Closes Phase 8 of plans/acestep-worker-pool.md.
```

Push the sub-plan rewrite as a separate prior commit:
```
docs(phase8): switch sub-plan from Option B to C1 (image hierarchy refactor)
```

## Quick context for next session (handoff)

- Branch `feat/acestep-worker-pool`, head `41c3591` is the previous Option B sub-plan draft. This rewrite supersedes that draft entirely.
- The sub-plan locks **C1**: full image hierarchy (gpu-torch-base + acestep-base + per-service leaf dockerfiles), but **no** torch version unification. `pyproject.toml` and `uv.lock` are untouched.
- Key invariants when implementing:
  - The `acestep-base` build must COPY the upstream source tree, not install it as a wheel — `_get_project_root()` requires in-tree layout.
  - The wrapper venv (`/app/.venv`) and the inner ACE-Step venv (`/opt/acestep/.venv`) are independent. Don't merge them.
  - `subprocess_runner.py` source is unchanged — only the runtime paths change via env vars and defaults.
  - `Dockerfile.worker` deletion + compose migration + new dockerfiles must be the same commit.
- Build orchestration: `scripts/build_images.sh` builds bases first, then leaves. CLAUDE.md is updated to mention this.
- The smoke test gate is "sft loads in <90 s on a fresh container, music-worker generation works, scoring runs post-generation." Don't ship without hitting all three.
- Approximate effort: 6-10 hours, dominated by the cold base image builds (20-40 min each) and the smoke test loop. If a base image build fails, fix the Dockerfile and rebuild — don't try to patch the running container.

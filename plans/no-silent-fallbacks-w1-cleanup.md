# W1 Cleanup — Final Pass Before Commit

**Status:** Proposed
**Date:** 2026-04-09
**For:** Whichever agent is executing Workstream 1 of [no-silent-fallbacks-v2.md](no-silent-fallbacks-v2.md)
**Why this exists:** Mid-W1 review caught five duplicate constants, one Optional-as-fallback anti-pattern in `Settings`, and ~9 prefix inconsistencies in `constants.py`. This document collects all of them in one place so the cleanup can ship as part of the same W1 commit instead of as a follow-up.

## TL;DR

Three passes, in order. Correctness first, then polish. Commit W1 only after all four verification greps return empty.

1. **Pass 1** — Delete 5 leftover duplicate constants from `constants.py`
2. **Pass 2** — Fix `Settings.audio_dir` / `data_dir` (Optional → required with named default)
3. **Pass 3** — Rename 9 inconsistently-prefixed constants

Then run the four verification greps and delete two CLAUDE.md technical-debt entries.

## Why this matters

The user is reviewing W1 in real time and noticed the agent left half-measures behind. Specifically:

- `claude_chat_model()` and `claude_scoring_model()` were created as **functions in `constants.py`** that wrap `os.environ.get(...)` reads. That's the wrong intermediate step — they should not exist at all, the values should be `Settings` fields and call sites should read `get_settings().claude_chat_model` directly. (The agent has likely already fixed this by the time you read it; if not, do that first as part of Pass 1.)
- `Settings.audio_dir: str | None = None` and `Settings.data_dir: str | None = None` reproduce the silent-fallback anti-pattern at a different layer: the call site has to OR them against `AUDIO_ROOT` / `DATA_ROOT` constants in `constants.py`. The default belongs **in** `Settings`, not as None-with-fallback-elsewhere.
- A handful of constants in `constants.py` now duplicate `Settings` fields (DATA_ROOT, AUDIO_ROOT, DEFAULT_SOFT_DELETE_RETENTION_DAYS, ACESTEP_DEFAULT_VRAM_GB) or belong to deleted code paths (REDIS_URL_MISMATCH_WARNING). They need to go.
- The renames are a small consistency cleanup the user wants done in the same W1 pass. They're mechanical, ~30 minutes total, and shipping them with W1 means the codebase doesn't need a second pass through the same files.

## The general rule (do not violate this in W1 or later)

> **Env reads belong in `settings.py`. Compile-time identifiers belong in `constants.py`. Functions that wrap env reads belong nowhere.**
>
> If you find yourself writing:
> ```python
> # constants.py
> def claude_chat_model() -> str:
>     return os.environ.get("CLAUDE_CHAT_MODEL", "claude-opus-4-6")
> ```
> Stop. That's a half-measure. The right shape is a Pydantic field on `Settings` with the same default, accessed via `get_settings().claude_chat_model` at the call site.
>
> The litmus test for any constant: "Could a deployment legitimately want to override this without changing code?" → Yes → `Settings`. → No → `constants.py`. The third question that catches the anti-pattern: "Did the value come from `os.environ.get(...)` historically?" → Yes → `Settings`, regardless of what the answer to the first question feels like.

What stays in `constants.py` after W1:
- DB row key strings (`SETTING_CLAUDE_CHAT_MODEL = "claude_chat_model"`)
- Enum classes (`JobStatus`, `JobType`, `ResourceType`, `AuditAction`)
- Frozensets derived from enums (`JOB_ACTIVE_STATUSES`)
- Protocol/queue/Redis key names (`ARQ_MUSIC_QUEUE_NAME`, `RECOVERY_LOCK_MUSIC_KEY`)
- Fixed lookup tables (`ALLOWED_CLAUDE_MODELS`)
- Algorithm constants that were never env-tunable (`SILENCE_TOP_DB`, `DYNAMICS_PITCH_WEIGHT`)
- Prometheus metric name strings (`PROM_HTTP_REQUESTS_TOTAL`)

What `constants.py` must NOT contain after W1:
- Any `os.environ.*` reference
- Any function definition
- Any value whose default is conditional on env state
- Any constant whose value duplicates a `Settings` field

---

## Pass 1 — Delete leftover duplicates from `constants.py`

Delete these five entries from `src/songmaker_cli/constants.py`:

```python
DATA_ROOT = "data"                                       # duplicate of Settings.data_dir
AUDIO_ROOT = "data/audio"                                # duplicate of Settings.audio_dir
DEFAULT_SOFT_DELETE_RETENTION_DAYS: Final[int] = 30      # duplicate of Settings.soft_delete_retention_days
ACESTEP_DEFAULT_VRAM_GB = "24"                           # duplicate of WorkerSettings.vram_budget_gb
REDIS_URL_MISMATCH_WARNING = (...)                       # warning code is being deleted by W1
```

After deletion, grep to confirm no remaining imports:

```bash
grep -rn "DATA_ROOT\|AUDIO_ROOT\|DEFAULT_SOFT_DELETE_RETENTION_DAYS\|ACESTEP_DEFAULT_VRAM_GB\|REDIS_URL_MISMATCH_WARNING" src/ tests/ | grep -v __pycache__
# Expected: empty
```

**VRAM value disagreement:** `constants.py` has `ACESTEP_DEFAULT_VRAM_GB = "24"` (string), `WorkerSettings.vram_budget_gb = 22.0` (float). The values disagree. The float in `WorkerSettings` is correct (22.0 is what production has been using). Delete the constants version, keep the WorkerSettings field.

## Pass 2 — Fix the silent-fallback in `Settings.audio_dir` / `data_dir`

`src/songmaker_cli/settings.py` lines 116-117 currently read:

```python
audio_dir: str | None = None
data_dir: str | None = None
```

This is the silent-fallback anti-pattern in disguise. The Optional + None means call sites have to OR them against the (now-deleted) `AUDIO_ROOT` / `DATA_ROOT` constants. The default belongs in `Settings` as a named value, not as None-with-fallback-elsewhere.

Change to:

```python
audio_dir: str = "data/audio"
data_dir: str = "data"
```

Then `WorkerBase.audio_dir()` becomes simply:

```python
def audio_dir(self) -> Path:
    return Path(self._settings.audio_dir)
```

No `or` chain. No fallback to a deleted constant.

## Pass 3 — Prefix renames for consistency

`constants.py` is mostly already prefix-organized (`REDIS_*`, `PROM_*`, `ARQ_*`, `SETTING_*`, `SILENCE_*`, `DYNAMICS_*`, `WHISPER_*`, `JOB_*`, etc.). A few outliers and one collision need cleanup. Mechanical rename pass:

| From | To | Why |
|---|---|---|
| `SHARED_RATE_LIMIT` | `SHARING_RATE_LIMIT` | The `SHARED_` prefix collides with `SHARED_TMP_DIRNAME` (unrelated). Disambiguate. |
| `SHARED_RATE_WINDOW_SECONDS` | `SHARING_RATE_WINDOW_SECONDS` | Same collision. |
| `SHARED_TMP_DIRNAME` | `WORKER_SHARED_TMP_DIRNAME` | Resolves the collision and clarifies intent (cross-container worker IPC dir). |
| `SCORER_PIPELINE_TIMEOUT_SECONDS` | `SCORING_PIPELINE_TIMEOUT_SECONDS` | All other scoring constants use `SCORING_*` (`SCORING_SAMPLE_RATE`, `SCORING_NUM_SECTIONS`). The lone `SCORER_` is inconsistent. |
| `AVAILABLE_MODEL_MODES` | `MODEL_AVAILABLE_MODES` | Three model constants currently have three different prefix patterns. Unify under `MODEL_*`. |
| `DEFAULT_MODEL_MODE` | `MODEL_DEFAULT_MODE` | Same. |
| `ALLOWED_CLAUDE_MODELS` | `MODEL_ALLOWED_CLAUDE` | Same. |
| `MAX_USER_AGENT_LENGTH` | `HTTP_MAX_USER_AGENT_LENGTH` | HTTP request constraint. |
| `GLOBAL_DEFAULTS_PRESET_NAME` | `PRESET_GLOBAL_DEFAULTS_NAME` | Preset-domain constant. |

**Leave `APP_NAME` and `DEFAULT_ARTIST` alone** — they're so global the prefix is implicit.

For each rename, update all imports across `src/` and `tests/`. The renames are mechanical and can be done with grep + sed (or your editor's rename refactor):

```bash
# Example for one rename — repeat per row in the table:
grep -rln "\bSHARED_RATE_LIMIT\b" src/ tests/ | xargs sed -i 's/\bSHARED_RATE_LIMIT\b/SHARING_RATE_LIMIT/g'
```

**Important:** use word boundaries (`\b`). `SHARED_RATE_LIMIT` is a substring of `SHARED_RATE_WINDOW_SECONDS` — without `\b` you'd corrupt the second name. Or do them in the right order (longest first).

After all renames, verify no stale references:

```bash
grep -rn "\b\(SHARED_RATE_LIMIT\|SHARED_RATE_WINDOW_SECONDS\|SHARED_TMP_DIRNAME\|SCORER_PIPELINE_TIMEOUT_SECONDS\|AVAILABLE_MODEL_MODES\|DEFAULT_MODEL_MODE\|ALLOWED_CLAUDE_MODELS\|MAX_USER_AGENT_LENGTH\|GLOBAL_DEFAULTS_PRESET_NAME\)\b" src/ tests/ | grep -v __pycache__
# Expected: empty
```

**Watch for string-literal occurrences:** if any of the renamed constants is hardcoded as a string somewhere (e.g. inside a JSON config, a frontend file, or a migration's `op.execute(...)` SQL), the grep above won't catch it. Run a broader grep too:

```bash
grep -rn "shared_rate_limit\|max_user_agent_length\|global_defaults_preset_name" src/ tests/ frontend/ docs/ scripts/ | grep -v __pycache__
# Review any matches manually before renaming
```

Most likely there are zero string occurrences for these particular names, but check.

## Verification — run all four greps before declaring W1 done

```bash
# 1. No env reads outside settings.py (with the audiobox CUDA mutation as the only allowlisted exception)
grep -rn "os\.environ\|os\.getenv" src/ | grep -v __pycache__ | grep -v "settings\.py" | grep -v "audiobox_aesthetics.py:60"
# Expected: empty

# 2. constants.py contains zero functions and zero env references
grep -E "os\.(environ|getenv)|^def " src/songmaker_cli/constants.py
# Expected: empty

# 3. The 5 deleted constants have no remaining references
grep -rn "DATA_ROOT\|AUDIO_ROOT\|DEFAULT_SOFT_DELETE_RETENTION_DAYS\|ACESTEP_DEFAULT_VRAM_GB\|REDIS_URL_MISMATCH_WARNING" src/ tests/ | grep -v __pycache__
# Expected: empty

# 4. The 9 renamed constants have no stale references
grep -rn "\b\(SHARED_RATE_LIMIT\|SHARED_RATE_WINDOW_SECONDS\|SHARED_TMP_DIRNAME\|SCORER_PIPELINE_TIMEOUT_SECONDS\|AVAILABLE_MODEL_MODES\|DEFAULT_MODEL_MODE\|ALLOWED_CLAUDE_MODELS\|MAX_USER_AGENT_LENGTH\|GLOBAL_DEFAULTS_PRESET_NAME\)\b" src/ tests/ | grep -v __pycache__
# Expected: empty
```

All four greps must return empty. If any returns content, that's residue — fix it before committing.

## Delete the CLAUDE.md technical-debt entries

After the cleanup, the following entries in `CLAUDE.md` "Known Technical Debt" must be **deleted** (not rewritten):

- `**WorkerSettings.redis_settings is resolved at import time** from REDIS_URL...`
- `**CLAUDE_CHAT_MODEL and CLAUDE_SCORING_MODEL are resolved at import time** in constants.py via os.environ.get()...`

If they still describe `constants.py` as the source of these values after W1, the cleanup didn't go far enough — go back and fix it.

## Order of operations

1. Pass 1 (deletions) — uncovers any remaining call-site issues that depended on the deleted constants
2. Pass 2 (Settings.audio_dir fix) — required by Pass 1 since `AUDIO_ROOT` / `DATA_ROOT` are gone
3. Run the test suite — should be green
4. Pass 3 (renames) — purely mechanical, no behavior change
5. Run the test suite again — should still be green
6. Run all four verification greps
7. Delete the two CLAUDE.md tech-debt entries
8. Commit W1 in one go

## Acceptance criteria

W1 is done when:

- All four verification greps return empty
- `pytest tests/ -q --no-cov` passes
- `ruff check src/ tests/` passes
- `constants.py` contains zero `os.environ` references and zero function definitions
- `Settings.audio_dir` and `Settings.data_dir` are `str` (not `Optional[str]`) with named defaults
- The two CLAUDE.md "Known Technical Debt" entries about import-time resolution are deleted
- The W1 commit message references this cleanup plan in addition to the v2 plan

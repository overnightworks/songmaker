# ACE-Step naming alignment + magic-string centralization

> **Status: READY** — Audit-driven cleanup. Four phases, each independently mergeable. Phases 1-2 are safe prep; Phase 3 is the cross-cutting rename (DB + wire format + frontend); Phase 4 locks Phase 3 against vendored drift.

## Why

A codebase audit found that [src/acestep_engine/client.py:173-236](../src/acestep_engine/client.py#L173-L236) hand-translates ~60 lines of field names into the ACE-Step `/release_task` payload, even though the vendored [GenerateMusicRequest](../_models/acestep/acestep/api/http/release_task_models.py) sets `allow_population_by_field_name = True` and accepts most songmaker names verbatim. The real renames ACE-Step requires are a handful: `key → key_scale`, `think_mode → thinking` (with bool coercion), `duration → audio_duration`, plus two `*_path` suffixes. Everything else is busywork that masks a `model_dump()` call and forces every layer (dataclass, Pydantic, JSON columns, Svelte components) to carry a bespoke name different from the upstream model.

The same audit surfaced ~90 raw string literals for job status, job type, audit action, and scorer identity scattered across 14 files, plus a parallel scorer namespace (`VALID_SCORER_NAMES` frozenset in [api_models/songs.py:40](../src/songmaker_cli/api_models/songs.py#L40) vs `SCORE_KEY_*` constants in [scoring/models.py:7-24](../src/songmaker_cli/scoring/models.py#L7-L24) vs fields on `SongScores`, mapped together in `SongScores.to_dict()`). Centralizing these *before* Phase 3 touches the same files means the big rename doesn't collide with typo-fixes on the way through.

## Canonical names (audit-locked)

Every internal identifier matches the vendored `GenerateMusicRequest` field name:

| Songmaker today | Canonical (this refactor) | Notes |
|---|---|---|
| `prompt` | **`prompt`** | No change. Vendored field is `prompt: str` ([release_task_models.py:19](../_models/acestep/acestep/api/http/release_task_models.py#L19)); `caption` is only an input alias in the parser. |
| `duration` | `audio_duration` | Vendored: `audio_duration: Optional[float]`. |
| `key` | `key_scale` | Vendored: `key_scale: str`. |
| `think_mode: str` (`"deep"`/`"off"`) | `thinking: bool` | Lossy: `"deep" → True`, anything else → `False`. |
| `src_audio` | `src_audio_path` | Vendored accepts both; canonical is `_path`. |
| `reference_audio` | `reference_audio_path` | Same. |
| `inference_steps` | `inference_steps` | Already correct. |
| `vocal_language` | `vocal_language` | Already correct. Delete `_FIELD_MAPPING = {"language": "vocal_language"}` at [config.py:94](../src/songmaker_cli/config.py#L94). |

All `lm_*` fields already pass through unchanged.

---

## Phase 1 — StrEnum centralization (Change B)

**Goal:** one source of truth for job status, job type, resource type, and audit action. Zero behavior change on the wire.

### Edits

1. **[src/songmaker_cli/constants.py](../src/songmaker_cli/constants.py)** — append:

   ```python
   from enum import StrEnum

   class JobStatus(StrEnum):
       QUEUED = "queued"
       RUNNING = "running"
       COMPLETED = "completed"
       FAILED = "failed"
       PARTIAL = "partial"

   class JobType(StrEnum):
       GENERATE = "generate"
       SCORE = "score"
       CHAT = "chat"

   class ResourceType(StrEnum):
       SONG = "song"
       ALBUM = "album"
       GENERATION = "generation"
       PLAYLIST = "playlist"

   class AuditAction(StrEnum):
       GENERATE = "generate"
       SCORE = "score"
       REPAINT = "repaint"
       COVER = "cover"
       DELETE = "delete"
       # add any others surfaced during the grep sweep

   JOB_ACTIVE_STATUSES = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})
   JOB_TERMINAL_STATUSES = frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.PARTIAL})
   ```

2. **Grep sweep**:
   ```
   rg -n '"(queued|running|completed|failed|partial)"' src/songmaker_cli tests/
   rg -n '"(generate|score|chat)"' src/songmaker_cli/jobs* src/songmaker_cli/*_worker.py \
      src/songmaker_cli/generation_api.py src/songmaker_cli/db/queries/jobs.py \
      src/songmaker_cli/admin_api.py src/songmaker_cli/api_helpers.py
   rg -n '"(song|album|generation|playlist)"' src/songmaker_cli/audit*.py src/songmaker_cli/db/queries/sharing.py
   ```

3. **Edit order** (one PR, three commits):
   1. Add enums to `constants.py`. Run `pytest tests/test_constants.py -q`.
   2. Replace job-status literals — start at [db/queries/jobs.py:21,51,61,82,84](../src/songmaker_cli/db/queries/jobs.py#L21), then call sites. Run `pytest tests/test_jobs.py tests/test_db.py tests/test_api.py -q`.
   3. Replace job-type, resource-type, and audit-action literals. Same test subset.

4. **Bug to fix in this phase**: [db/models.py:137](../src/songmaker_cli/db/models.py#L137) — `Generation.status` defaults to `"completed"`. Investigate whether any code path relies on this. If every constructor passes `status=` explicitly, change the default to `JobStatus.RUNNING` (or drop the default and make the column non-nullable). If anything reads the default, fix the caller.

### Tests
- New `tests/test_constants.py`: assert each enum member equals its string value, assert `JOB_ACTIVE_STATUSES` membership, assert SQLAlchemy column comparison still works (`Job.status == JobStatus.QUEUED`).
- Run full suite once at phase end.

### Risks
- **`StrEnum` JSON serialization**: pydantic v2 serializes `StrEnum` as the value (`"queued"`), not `"JobStatus.QUEUED"`. Add a regression test for the `/jobs/{id}` response shape.
- **DB rows on disk are unchanged** — `StrEnum("queued") == "queued"` is `True`.
- **Frontend untouched**: wire format identical.

### Rollback
Mechanical revert. No data migration.

---

## Phase 2 — Scorer registry unification (Change C)

**Goal:** one declarative `SCORERS` table that drives validation, `SongScores.to_dict()` output keys, and a new `/scoring/schema` endpoint that the frontend consumes instead of hardcoding score keys.

### Current duplication
- [api_models/songs.py:40-43](../src/songmaker_cli/api_models/songs.py#L40-L43) — `VALID_SCORER_NAMES` frozenset of seven names.
- [scoring/pipeline.py](../src/songmaker_cli/scoring/pipeline.py) — `_VALID_SCORER_NAMES = frozenset(f.name for f in fields(SongScores))`. Same seven names, different derivation.
- [scoring/models.py:7-24](../src/songmaker_cli/scoring/models.py#L7-L24) — 18 `SCORE_KEY_*` constants used by [SongScores.to_dict()](../src/songmaker_cli/scoring/models.py#L145-L185).
- Frontend hardcodes the output key list in `frontend/src/lib/utils/scores.ts`.

### Design

Single declarative table in `scoring/pipeline.py` (or new `scoring/registry.py`):

```python
@dataclass(frozen=True)
class ScorerSpec:
    name: str                       # canonical scorer name, matches SongScores field
    output_keys: tuple[str, ...]    # keys emitted in to_dict()
    needs_audio: bool = True
    after_gpu: bool = False

SCORERS: dict[str, ScorerSpec] = {
    "text_accuracy":     ScorerSpec("text_accuracy", ("text_accuracy", "detected_language"), needs_audio=False),
    "lyrical_coherence": ScorerSpec("lyrical_coherence", ("lyrical_coherence", "lyrical_summary"), needs_audio=False, after_gpu=True),
    "emotional_dynamics":ScorerSpec("emotional_dynamics", ("dynamics", "dynamics_pitch_cv", "dynamics_rms_contrast", "dynamics_onset_cv")),
    "audiobox":          ScorerSpec("audiobox", ("audiobox_enjoyment", "audiobox_understanding", "audiobox_complexity", "audiobox_quality")),
    "bpm_accuracy":      ScorerSpec("bpm_accuracy", ("bpm_detected", "bpm_deviation")),
    "silence":           ScorerSpec("silence", ("silence_gaps", "silence_longest")),
    "spectral_quality":  ScorerSpec("spectral_quality", ("spectral_artifacts",)),
}
```

### Edits
1. Create `SCORERS` table. Wrap the existing `register` decorator to validate `name in SCORERS` (richer error).
2. Rewrite `SongScores.to_dict()` to iterate `SCORERS` rather than the conditional ladder. Each scorer dataclass gets a tiny `dump()` method or per-spec adapter. Delete the 18 `SCORE_KEY_*` constants — strings live inside `output_keys`.
3. Replace `VALID_SCORER_NAMES` in `api_models/songs.py` with `SCORERS.keys()`.
4. Add `GET /scoring/schema` endpoint returning `{"scorers": [{"name": ..., "output_keys": [...], "needs_audio": ...}, ...]}`.
5. Re-run `python scripts/generate_types.py`.
6. Frontend: replace hardcoded key list in `frontend/src/lib/utils/scores.ts` with the schema fetch (initial commit can keep frontend constants but source them from the schema endpoint — full frontend cleanup is optional).

### Tests
- `tests/test_scoring_pipeline.py` — new test iterates `SCORERS`, builds a fake score dataclass for each, asserts `to_dict()` keys ⊆ `output_keys`.
- `tests/test_api.py` — `/scoring/schema` test.
- **Equivalence test**: hold the old `to_dict()` body in a private helper for one commit, assert byte-equal output against the new implementation for a sample `SongScores`, then delete the old version.

### Risks
- **Existing `scores.value` JSON on disk uses the existing output keys** — plan keeps those exact strings inside `output_keys`. No data migration.
- `to_dict()` rewrite is the riskiest edit; the equivalence test is the safety net.

### Rollback
Pure code revert.

---

## Phase 3 — ACE-Step canonical rename (Change A)

**Goal:** adopt vendored canonical names everywhere. Delete `_FIELD_MAPPING` / `_apply_params()`. Collapse `client.py:173-236` to a single `model_dump`. Run an Alembic migration for the two `Version` columns and an Alembic data migration for all `generation_params` JSON columns.

### Step 3.1 — Engine side
- [src/acestep_engine/models.py](../src/acestep_engine/models.py) — `AceStepConfig`: rename `duration → audio_duration`, `key → key_scale`, `src_audio → src_audio_path`, `reference_audio → reference_audio_path`, `think_mode: str = "deep" → thinking: bool = True`. Keep `prompt`.
- [src/acestep_engine/client.py:165-236](../src/acestep_engine/client.py#L165-L236) — replace the explicit `payload = {...}` dict with:
  ```python
  from dataclasses import asdict
  payload = {k: v for k, v in asdict(config).items() if v not in (None, "", -1)}
  payload["audio_format"] = "wav"
  payload["use_random_seed"] = config.seed < 0
  ```
  **Verify** in `_models/acestep/acestep/api/http/release_task_route.py` whether the server tolerates irrelevant fields per `task_type`. If it does, the simple comprehension is sufficient. If not, keep a tiny `task_type → field whitelist` filter.
- Run `pytest tests/test_client.py tests/test_acestep_state.py -q`.

### Step 3.2 — DB schema migration (two `Version` columns)
- [db/models.py:109-110](../src/songmaker_cli/db/models.py#L109): `Version.duration → Version.audio_duration`, `Version.key → Version.key_scale`. `Version.prompt` and `Version.bpm` stay (already canonical).
- New Alembic revision `<hash>_rename_version_columns_and_params.py`:
  ```python
  def upgrade() -> None:
      op.alter_column("versions", "duration", new_column_name="audio_duration")
      op.alter_column("versions", "key", new_column_name="key_scale")
      _migrate_generation_params(op.get_bind(), forward=True)

  def downgrade() -> None:
      _migrate_generation_params(op.get_bind(), forward=False)
      op.alter_column("versions", "audio_duration", new_column_name="duration")
      op.alter_column("versions", "key_scale", new_column_name="key")
  ```

### Step 3.3 — JSON data migration

**Decision: Alembic data migration, NOT a read-time shim.** Rationale:
- The rename set is tiny (5 keys) and static.
- A read-time shim taxes every `model_validate()` call forever and forces mirror logic on writes.
- Forward-only migrations match prior art in `src/songmaker_cli/db/migrations/versions/`.
- Postgres JSONB supports this natively in ~10 lines of SQL.

```python
RENAMES = {
    "duration": "audio_duration",
    "key": "key_scale",
    "src_audio": "src_audio_path",
    "reference_audio": "reference_audio_path",
}
TARGETS = (
    ("generations", "generation_params"),
    ("versions", "generation_params"),
    ("generation_presets", "params"),
)

def _migrate_generation_params(conn, forward: bool) -> None:
    rename_pairs = list(RENAMES.items()) if forward else [(v, k) for k, v in RENAMES.items()]
    for table, col in TARGETS:
        for old, new in rename_pairs:
            conn.execute(text(f"""
                UPDATE {table} SET {col} =
                  ({col} - '{old}') || jsonb_build_object('{new}', {col}->'{old}')
                WHERE {col} ? '{old}'
            """))
        # think_mode requires value coercion
        if forward:
            conn.execute(text(f"""
                UPDATE {table} SET {col} =
                  ({col} - 'think_mode') ||
                  jsonb_build_object('thinking', ({col}->>'think_mode') = 'deep')
                WHERE {col} ? 'think_mode'
            """))
        else:
            conn.execute(text(f"""
                UPDATE {table} SET {col} =
                  ({col} - 'thinking') ||
                  jsonb_build_object('think_mode', CASE WHEN ({col}->>'thinking')::bool THEN 'deep' ELSE 'off' END)
                WHERE {col} ? 'thinking'
            """))
```

**Take a DB backup before applying** (`scripts/backup.sh`).

### Step 3.4 — Pydantic API models
- [src/songmaker_cli/api_models/songs.py:46-122](../src/songmaker_cli/api_models/songs.py#L46-L122):
  - `GenerationParams`: `think_mode: str | None → thinking: bool | None`. Drop `_VALID_THINK_MODES` + the `_validate_think_mode` validator. Rename `reference_audio → reference_audio_path`.
  - `StoredGenerationParams`: `duration → audio_duration`, `key → key_scale`.
  - `SongCreateRequest` / `SongUpdateRequest` / `VersionResponse` / `SongSummaryResponse`: same renames where they reference these fields.

### Step 3.5 — Config + Song.language column
- **`Song.language` DB column → `Song.vocal_language`**. Investigation found that `parser.py:SongMeta` does NOT parse Markdown frontmatter — it's a passive Pydantic model built in-memory at [jobs.py:121](../src/songmaker_cli/jobs.py#L121) from DB rows. The `language` key only exists because [jobs.py:116](../src/songmaker_cli/jobs.py#L116) packs `Song.language` into a dict that `_FIELD_MAPPING` then translates. Renaming the DB column eliminates the asymmetry entirely. **No frontmatter shim is needed** (no frontmatter parsing exists). Add `op.alter_column("songs", "language", new_column_name="vocal_language")` to the same Alembic revision as Step 3.2.
- [src/songmaker_cli/config.py](../src/songmaker_cli/config.py): delete `_FIELD_MAPPING` (line 94) and `_apply_params` (line 97). Replace the loop at lines 203-204 with `fields.update(layer)`. Update `_SHARED_LM_DEFAULTS`: `"think_mode": "deep" → "thinking": True`. Update `_sanitize_params`: `duration → audio_duration`, drop `think_mode` branch.
- [jobs.py:116](../src/songmaker_cli/jobs.py#L116): emit `"vocal_language": song.vocal_language` instead of `"language": song.language`.
- Grep callers: `rg '\.language\b|\blanguage=' src/songmaker_cli tests/` → rename to `vocal_language`. Frontend `Song` type and any `song.language` references in Svelte components also need renaming (regenerated via `scripts/generate_types.py`).

### Step 3.6 — Endpoints + jobs
Grep and rename: `rg '\b(prompt|duration|key|reference_audio|src_audio|think_mode)\b' src/songmaker_cli/generation_api.py src/songmaker_cli/jobs* src/songmaker_cli/chat_api.py` — audit hit by hit. The `prompt` matches will be loud (mostly correct uses); filter manually.

### Step 3.7 — Frontend (no labels layer)
1. `python scripts/generate_types.py` — regenerate `frontend/src/lib/api/types.ts`.
2. Sweep with `rg`:
   ```
   rg 'think_mode|reference_audio\b|src_audio\b' frontend/src
   rg '\bduration\b' frontend/src/lib/components frontend/src/lib/stores
   ```
3. Files known to touch: `GenerationSettings.svelte`, `ParamControls.svelte`, `SongEditor.svelte`, `SongDetailView.svelte`, `SongNode.svelte`, `GenerationsList.svelte`, `GenerationView.svelte`, `WaveformRangePicker.svelte`, `lib/stores/editor.ts` + test, `lib/utils/chat-context.ts` + test, share routes.
4. The `think_mode: "deep" | "off"` `<select>` becomes a `<input type="checkbox" bind:checked={params.thinking}>`.

### Step 3.8 — Tests
- `tests/test_client.py`: rewrite payload-shape assertions.
- `tests/test_config.py`: any test passing `language=` / `think_mode=` / `duration=` / `key=`.
- `tests/test_parser.py`: frontmatter fixtures + back-compat shim coverage.
- `tests/test_api.py`: `SongCreateRequest`, `SongUpdateRequest`, `GenerateRequest` fixtures.
- `tests/test_db.py`, `tests/conftest.py`: any raw `Version`/`Generation` constructors.

### Commit order in the PR
1. Alembic migration (schema + data) — file added, not yet applied
2. `db/models.py` column rename
3. `AceStepConfig` rename + `client.py` collapse
4. `config.py` + `parser.py` (delete `_FIELD_MAPPING`)
5. `api_models/songs.py` Pydantic rename
6. `generation_api.py` + `jobs/` call sites
7. Backend tests
8. `generate_types.py` regen
9. Frontend rename sweep + tests
10. `docs/acestep.md` + `docs/architecture.md` updates

Run `pytest tests/test_config.py tests/test_client.py tests/test_parser.py -q` between commits 5 and 6. **Full suite once** after commit 9.

### Risks
- **API break for `SongCreateRequest`**: external CLI users posting `{"duration": 180}` will get a 422. Single-tenant deployment, accepted break — document in PR body.
- **`think_mode` value coercion is lossy**: anything other than `"deep"` becomes `False`. Grep `rg 'think_mode.*=.*[\"\']' src/ tests/` to verify only `"deep"` and `"off"` are in use.
- **Frontend + backend must deploy in lockstep** (same docker compose up).
- **Pre-existing user `.md` files** with `duration:` frontmatter — covered by parser shim.

### Rollback
Alembic `downgrade()` reverses both schema and data migration. Code revert is a single PR revert. Frontend redeploys in lockstep.

---

## Phase 4 — Contract test against vendored ACE-Step model (Change D)

**Goal:** machine-checked guarantee that any `AceStepConfig` round-trips through `GenerateMusicRequest`. Locks Phase 3 and catches future upstream drift on rebase.

### File
`tests/test_acestep_contract.py`:

```python
from dataclasses import asdict
import pytest
from acestep.api.http.release_task_models import GenerateMusicRequest
from acestep_engine.models import AceStepConfig


def _base(**overrides) -> AceStepConfig:
    defaults = dict(
        prompt="rock ballad with piano",
        lyrics="[verse]\nHello\n[chorus]\nOh oh oh",
        bpm=120,
        audio_duration=60,
        key_scale="C major",
        vocal_language="en",
        inference_steps=8,
        thinking=True,
    )
    defaults.update(overrides)
    return AceStepConfig(**defaults)


@pytest.mark.parametrize("task_type,extras", [
    ("text2music", {}),
    ("repaint", {"src_audio_path": "/tmp/src.wav", "repainting_start": 10.0,
                 "repainting_end": 20.0, "repaint_mode": "balanced", "repaint_strength": 0.5}),
    ("cover",   {"src_audio_path": "/tmp/src.wav", "audio_cover_strength": 0.8,
                 "cover_noise_strength": 0.1}),
])
def test_acestep_config_matches_vendored_model(task_type, extras):
    cfg = _base(task_type=task_type, **extras)
    payload = {k: v for k, v in asdict(cfg).items() if v not in (None, "", -1)}
    payload["use_random_seed"] = cfg.seed < 0
    payload["audio_format"] = "wav"
    model = GenerateMusicRequest(**payload)
    assert model.prompt == cfg.prompt
    assert model.audio_duration == cfg.audio_duration
    assert model.key_scale == cfg.key_scale
    assert model.thinking is cfg.thinking


def test_acestep_config_no_unknown_fields():
    cfg_fields = {f.name for f in AceStepConfig.__dataclass_fields__.values()}
    model_fields = set(GenerateMusicRequest.model_fields.keys())
    songmaker_only = {"seed"}  # client wraps use_random_seed from seed<0
    extra = cfg_fields - model_fields - songmaker_only
    assert not extra, f"AceStepConfig fields missing from vendored model: {extra}"
```

### Risks
- Vendored upgrade may rename fields → test fails on rebase. **That's the point.**
- Pydantic v1/v2 import: vendored uses v1-style `Field`. Verify the import works in songmaker's pydantic-v2 environment; gate behind `pytest.importorskip` if not.

### Rollback
Delete the file. Pure additive.

---

## Self-review checklist (per phase)

- [ ] Re-read every changed file top to bottom
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/ -n auto -q --cov=songmaker_cli --cov=audio_engine --cov=acestep_engine --cov-report=term-missing` once at phase end
- [ ] Coverage must not regress
- [ ] Phase 1 grep: `rg '"(queued|running|completed|failed|partial|generate|score|chat)"' src/songmaker_cli/`
- [ ] Phase 3 grep: `rg '\bthink_mode\b|\bsrc_audio\b(?!_path)|\breference_audio\b(?!_path)|_FIELD_MAPPING|_apply_params' src/ tests/ frontend/src/`
- [ ] `docs/architecture.md` + `docs/acestep.md` updated for any field name reference
- [ ] `python scripts/generate_types.py` run on clean checkout, diff committed
- [ ] **Phase 3 only**: tested against a restored production DB snapshot in staging before deploy

## Speed notes

- Batch edits — Phase 1 is ~90 string replacements across 14 files; one rg-driven pass.
- Parallel tool calls when reading multiple files for a sweep.
- Test suite **once per phase**, not per commit.
- **Phases 1 and 2 can land in parallel PRs** — they don't touch the same lines. Phase 3 waits on both. Phase 4 waits on Phase 3.
- **Phase 3 is one PR**, not ten — splitting would leave `main` with the Pydantic model and DB column disagreeing.

## Out of scope

- Modifying the vendored `_models/acestep/` source (read-only).
- A `/generation/schema` endpoint for `AceStepConfig` (frontend hardcoding tolerable; `AceStepConfig` rarely changes).
- The `jobs.py` god-module split — see [jobs-module-split.md](jobs-module-split.md).
- Frontend pretty labels / i18n — explicitly rejected by the user.

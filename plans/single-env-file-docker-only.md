# Single env file + Docker-only deployment

**Status:** Proposed
**Date:** 2026-04-09
**Driver:** During the W1 re-review on 2026-04-09, the user noticed that `.env` and `.server.env` overlap on 6 keys (SESSION_SECRET, ALLOWED_HOSTS, CORS_ORIGIN, TRUSTED_PROXIES, ADMIN_USERNAME, ADMIN_PASSWORD) and asked whether the duplication is justified. Investigation showed it isn't — the only reason `.server.env` exists is to support a `uv run songmaker server` local-dev workflow that the user has not used in months. The host Postgres install backing that workflow has a 4K (essentially empty) data directory. This plan eliminates the local-dev path entirely and consolidates to a single `.env` file.
**Sequencing:** Execute **after** the agent's in-flight W1 cleanup commit lands (the one fixing `clear_stale_user_jobs` docstring + `WorkerSettings(BaseSettings)` split + `extra="forbid"`). This plan touches `settings.py` and `conftest.py`, both of which are in the W1 cleanup. Doing this concurrently would create merge conflicts.
**Companion:** [no-silent-fallbacks-v2.md](no-silent-fallbacks-v2.md), [no-silent-fallbacks-w1-cleanup.md](no-silent-fallbacks-w1-cleanup.md)

## Goal

After this lands:

1. **Single env file** — `.env` is the only env file. `.server.env` is deleted.
2. **Single deployment path** — `docker compose up -d --build --wait` is the only way to run the live app. `uv run songmaker server` no longer works (intentionally).
3. **No host Postgres dependency** — the host's `postgresql@16-main` service can be stopped, disabled, and uninstalled without breaking anything in the project.
4. **Tests still run natively** — `pytest tests/` against SQLite stays the same. The IDE still uses the local `.venv` for type checking and autocomplete.
5. **`extra="forbid"` is preserved** — the Settings class explicitly declares the Docker-substitution-only fields (POSTGRES_USER, GRAFANA_PASSWORD, etc.) as ignored optionals so a typo on a real app field still raises at startup.

## Non-goals

- Containerizing tests. `pytest` continues to run natively against SQLite. There is no need to spin up a Docker postgres for tests.
- Containerizing the IDE / type checker. Local `.venv` stays. Code edits happen in the IDE as before.
- Removing SQLite test support. `init_test_db()` and the SQLite-skip migration guards stay.
- Touching the acestep-worker container or its config (other than removing `.server.env` references if any).

## Why this is cleaner

The current state has **two paths for "run the songmaker server":**

1. `docker compose up` → reads from `.env` via Docker Compose substitution → containers get vars via `environment:` blocks → pydantic Settings reads from container env. **This is what you actually use.**
2. `uv run songmaker server` → reads from `.server.env` via pydantic-settings env_file → process gets vars directly → connects to host Postgres on `localhost:5432`. **This is what you have not used in months.**

Path 2 exists, has dedicated config (`.server.env`), and requires a separate host Postgres install. Path 2 also creates a 6-key duplication in the env files (the keys that need to be the same in both contexts) which is silent-fallback bait — change one, forget the other, get a deployment that boots with stale secrets.

Removing path 2 collapses everything to path 1. One config file, one deployment, one place to set a secret.

## Step 1 — Host Postgres removal (manual, you do this)

These require sudo and are best done by hand with eyes on the output. Estimated time: 2 minutes.

```bash
# 1. Confirm the data directory is essentially empty (sanity check before destructive ops)
sudo ls -la /var/lib/postgresql/16/main
sudo du -sh /var/lib/postgresql/16/main
# Expected: ~4K, empty subdirs only. If you see >100M, STOP and back up first.

# 2. Stop the service
sudo systemctl stop postgresql@16-main
sudo systemctl stop postgresql.service

# 3. Verify port 5432 is free on the host
ss -ltn | grep ":5432"
# Expected: empty output

# 4. Disable on boot
sudo systemctl disable postgresql@16-main
sudo systemctl disable postgresql.service

# 5. (Optional, recommended) uninstall the package entirely
sudo apt-get purge postgresql-16 postgresql-client-16 postgresql-common
sudo apt-get autoremove

# 6. (Optional) remove the data directory
sudo rm -rf /var/lib/postgresql/
```

If you skip steps 5 and 6, the package stays installed but inert — you can `systemctl enable && start` to bring it back. Steps 5 and 6 are irreversible (well, you can `apt-get install postgresql-16` again, but the data is gone).

## Step 2 — Project cleanup (the agent does this in a follow-up commit)

### 2.1 Settings: switch env_file source to `.env`

In `src/songmaker_cli/settings.py`, change `_find_env_file()` to look for `.env` instead of `.server.env`:

```python
def _find_env_file() -> Path | None:
    """Walk up from CWD to find .env at the project root.

    Honors ``SONGMAKER_SKIP_ENV_FILE=1`` to bypass loading entirely
    (used by the test suite so .env values do not leak into
    monkeypatched env tests).
    """
    import os as _os
    if _os.environ.get("SONGMAKER_SKIP_ENV_FILE") == "1":
        return None
    cwd = Path.cwd().resolve()
    for parent in (cwd, *cwd.parents):
        candidate = parent / ".env"
        if candidate.exists():
            return candidate
        if (parent / "pyproject.toml").exists():
            return None
    return None
```

Same change in `src/acestep_engine/settings.py` (the hardcoded `env_file=".server.env"` should become `env_file=".env"`).

### 2.2 Settings: declare Docker-substitution fields as ignored optionals

Add the following fields to `Settings` (`src/songmaker_cli/settings.py`) after the existing field block:

```python
    # ── Docker Compose substitution fields ────────────────────────────
    # These are present in .env so docker-compose can substitute them into
    # container environment blocks (e.g. POSTGRES_USER → the postgres
    # container, HF_TOKEN → scripts/download_models.sh). The app code does
    # not read them. Declared here so extra="forbid" still recognizes them
    # and a typo on a real app field still raises ValidationError.
    postgres_user: str | None = None
    postgres_password: SecretStr | None = None
    postgres_db: str | None = None
    grafana_user: str | None = None
    grafana_password: SecretStr | None = None
    hf_token: SecretStr | None = None
```

`hf_token` is moved here from `WorkerSettings` if duplicated. Actually keep it on `WorkerSettings` too if the worker code uses it directly — both classes can declare the same field, they're independent.

### 2.3 Settings: keep `extra="forbid"` (already required by W1 re-review)

The existing `extra="ignore"` from the W1 commit must already be flipped to `extra="forbid"` as part of the W1 cleanup commit (per `plans/no-silent-fallbacks-w1-cleanup.md` Finding 3 / re-review). This plan assumes that fix is in place. If for some reason `extra="ignore"` is still in the working tree when this plan runs, flip it now.

### 2.4 Delete `.server.env` and any example files

```bash
git rm .server.env  # if tracked
rm -f .server.env   # always, in case it's only in working tree
git rm .server.env.example 2>/dev/null || true
```

The `.gitignore` already lists both `.env` and `.server.env`. The `.server.env` line in `.gitignore` can be removed for cleanliness:

```bash
sed -i '/^\.server\.env$/d' .gitignore
```

### 2.5 Update `tests/conftest.py`

Currently sets defaults via `os.environ.setdefault` for required fields and bypasses `.server.env` via `SONGMAKER_SKIP_ENV_FILE=1`. After the change, `SONGMAKER_SKIP_ENV_FILE=1` now bypasses `.env` instead. The fixture logic does not change — same defaults, same env var name, just bypasses a different file.

Verify by running the full test suite and confirming nothing leaks values from a real `.env` file.

### 2.6 Update `src/songmaker_cli/config.py`

Remove `load_env_file()` if it still exists — pydantic-settings handles env file loading directly now. Grep for `load_env_file` and `find_project_root` callers to confirm they're dead.

```bash
grep -rn "load_env_file\|find_project_root" src/ tests/
# Any references should either be removed or migrated to use Settings()
```

### 2.7 Update CLAUDE.md and docs

Replace every reference to `.server.env` with `.env`:

```bash
grep -rln "\.server\.env" CLAUDE.md docs/ scripts/
# For each match, edit to use .env instead
```

Specifically:
- `CLAUDE.md` "Setup & Run" section
- `docs/security.md` if it documents secret storage
- `scripts/BACKUP.md` (already references `.server.env` as "copy manually")
- Any `.server.env.example` should become `.env.example`

### 2.8 Update `scripts/download_models.sh`

The script already reads from `.env` (`ENV_FILE="$PROJECT_ROOT/.env"`). No change needed.

### 2.9 Verify `docker-compose.yml` doesn't reference `.server.env`

```bash
grep -n "server.env\|env_file" docker-compose.yml
```

If any service has `env_file: .server.env`, change to `env_file: .env` (or remove if `environment:` block already covers it, which it does for the songmaker services per the existing config).

## Step 3 — Verification

After Steps 1 and 2:

```bash
# 1. Linter clean
.venv/bin/ruff check src/ tests/

# 2. Full test suite green
.venv/bin/python -m pytest tests/ -q --no-cov

# 3. No .server.env references anywhere
grep -rn "\.server\.env" src/ tests/ docs/ scripts/ CLAUDE.md docker-compose.yml | grep -v __pycache__
# Expected: empty

# 4. Settings.model_config has extra="forbid"
grep -n 'extra=' src/songmaker_cli/settings.py src/acestep_engine/settings.py
# Expected: all "forbid"

# 5. Pydantic Settings can construct against the merged .env
.venv/bin/python -c "
from songmaker_cli.settings import Settings, get_settings
s = get_settings()
print('OK:', s.database_url[:30], s.redis_url[:20])
"

# 6. Docker stack starts healthy
timeout 300 docker compose up -d --build --wait
docker compose ps  # all services healthy

# 7. Smoke test: hit /health
curl -f http://localhost:8080/health
```

If any of these fails, do NOT proceed — fix and re-run.

## Risks

1. **`.env` file might be missing fields the merged Settings expects.** If `.env` doesn't have DATABASE_URL or REDIS_URL today (because they're constructed from POSTGRES_USER + POSTGRES_PASSWORD by docker-compose), the migration will fail. Fix: add `DATABASE_URL=postgresql://...` and `REDIS_URL=redis://...` lines to `.env` explicitly. They're now read directly by Settings instead of being constructed.

2. **`extra="forbid"` may surface long-standing typos in `.env`** that were previously silent. If Settings construction fails with `extra fields not permitted: SOME_OLD_VAR`, remove the unused var from `.env` (or add it as an Optional ignored field if it's still legitimately needed by Docker/scripts).

3. **The `_reset_settings_cache` autouse fixture in conftest.py is still required.** Tests that monkeypatch env vars depend on it. Don't delete.

4. **acestep-worker container env handling.** The acestep-worker reads its env from docker-compose `environment:` block, NOT from the env_file. Verify the worker still starts after the change.

5. **You will permanently lose the `uv run songmaker server` workflow.** This is intentional per the plan goal. If you change your mind later, restoring it is ~30 minutes of work (re-add `.server.env`, restore the env_file path, install host postgres). But you almost certainly won't want to.

## Acceptance criteria

- `.server.env` does not exist anywhere in the repo or working tree
- `Settings._find_env_file()` looks for `.env`, not `.server.env`
- `Settings` has the 6 new ignored Docker-substitution fields
- `extra="forbid"` is set in all three Settings classes
- Full test suite green (≥1325 passed)
- `docker compose up -d --build --wait` produces all-healthy stack
- `grep -rn "\.server\.env"` returns empty across the entire repo
- CLAUDE.md "Setup & Run" section reflects the Docker-only flow
- The host Postgres service is stopped and disabled (Step 1 done by user)

## Out of scope

- Renaming `.env` to anything else. The Docker Compose default is `.env`, so keeping that name avoids extra config.
- Adding `--watch` mode to docker-compose for hot reload during dev. Separate quality-of-life improvement, not required by this plan.
- Setting up `debugpy` for in-container debugging. If you ever want it, add later.
- Removing the `_reference/` directory. User is handling that manually.
- Removing the leftover `/tmp/songmaker_alembic_test.db`. Trivial cleanup, user can `rm` it.

## Estimated effort

- Step 1 (host cleanup): ~2 minutes (manual, sudo)
- Step 2 (project cleanup, agent): ~30 minutes including verification
- Step 3 (verification): ~5 minutes

Total: well under an hour. Single commit on the no-silent-fallbacks branch, immediately after the W1 cleanup commit.

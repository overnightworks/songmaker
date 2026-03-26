# Alembic-Only Schema Management

## Problem

`db/engine.py:34` calls `Base.metadata.create_all(engine)` on every startup. Alembic migrations also exist. Fresh installs get tables from `create_all()` with no Alembic history, so `alembic upgrade head` either fails or double-creates. Existing installs work because Alembic handles incremental changes.

## Approach

Drop `create_all()`. Use `alembic upgrade head` as the sole schema management path.

### Implementation

**Step 1: Remove `create_all()` from `init_db()`**

```python
# db/engine.py — remove this line:
Base.metadata.create_all(engine)
```

**Step 2: Run migrations at startup**

```python
# db/engine.py or server.py startup
from alembic.config import Config
from alembic import command

def run_migrations(db_path: Path) -> None:
    alembic_cfg = Config()
    alembic_cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(alembic_cfg, "head")
```

Call this in `init_db()` after engine creation but before returning the session factory.

**Step 3: Handle fresh installs**

For a brand-new database (no tables, no alembic_version table), `alembic upgrade head` runs all migrations from the initial one forward. This works out of the box if the first migration creates all tables.

Check: does the earliest migration create the full schema? If not, create a "baseline" migration:

```bash
alembic revision --autogenerate -m "baseline schema"
```

This migration becomes the starting point for fresh installs.

**Step 4: Stamp existing installs**

Existing databases created by `create_all()` have no `alembic_version` table. Running `alembic upgrade head` would try to create tables that already exist → crash.

Fix: add a one-time stamp check in the migration runner:

```python
def run_migrations(db_path: Path) -> None:
    # If tables exist but no alembic_version, stamp to current head
    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)
    has_tables = "albums" in inspector.get_table_names()
    has_alembic = "alembic_version" in inspector.get_table_names()

    if has_tables and not has_alembic:
        command.stamp(alembic_cfg, "head")
        return

    command.upgrade(alembic_cfg, "head")
```

### Files to Change

- `db/engine.py` — remove `create_all()`, add `run_migrations()`
- `alembic/env.py` — verify it uses the same engine/URL pattern
- Possibly: new baseline migration if the earliest migration doesn't cover full schema

### Test Changes

- Test fixtures currently use `create_all()` via `init_db()`. Two options:
  1. Let tests also use Alembic (slower but more realistic)
  2. Keep `create_all()` in a test-only helper (faster, acceptable divergence)

Recommendation: option 2. Tests need speed. The Alembic path is tested by the stamp/upgrade logic itself.

```python
# tests/conftest.py
def init_test_db(path):
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)  # fast, no migrations
    return sessionmaker(bind=engine)
```

### Risks

- If any migration has a bug, fresh installs break. Mitigated by CI running `alembic upgrade head` on an empty DB.
- Alembic adds ~200ms to startup. Acceptable.
- The stamp-existing-installs logic runs once, then never again. But if it gets the head revision wrong, existing data could be corrupted by re-running migrations. Use `command.stamp()` not `command.upgrade()` for this path.

### Validation

Add a CI step:

```bash
rm -f /tmp/test.db
alembic upgrade head  # must succeed on empty DB
alembic downgrade base  # must succeed (if downgrade is supported)
alembic upgrade head  # round-trip
```

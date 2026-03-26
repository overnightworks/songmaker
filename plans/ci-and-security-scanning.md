# CI Pipeline & Security Scanning

> **Status: Phase 1 DONE** — CI + security workflows in `.github/workflows/`.

## Goal

Automated CI pipeline that runs on every push/PR + security scanning to catch vulnerabilities before they ship.

---

## Phase 1: GitHub Actions CI

### Workflow: `.github/workflows/ci.yml`

Runs on every push and PR to `main` and `feat/*` branches.

- [x] **Python checks**: `ruff check src/ tests/` + `pytest tests/ -q --tb=short`
- [x] **Frontend checks**: `pnpm check` + `pnpm lint` + `pnpm test`
- [x] **Coverage gate**: fail if coverage drops below 90% on core modules
- [x] Matrix: Python 3.12, Node 22

### Workflow: `.github/workflows/security.yml`

Runs on every push + weekly schedule.

- [x] **Bandit**: `bandit -r src/ -c pyproject.toml` (Python security linter)
- [x] **pip-audit**: check for known vulnerabilities in Python dependencies
- [x] **npm audit**: check for known vulnerabilities in frontend dependencies
- [ ] Notifications: email/Slack on security findings (deferred — GitHub default email works)

---

## Phase 2: Pre-commit Hooks (Local)

Fast local feedback before code reaches GitHub.

```bash
pip install pre-commit
pre-commit install
```

### `.pre-commit-config.yaml`

- [ ] **ruff** — lint + format (replaces isort, black, flake8)
- [ ] **bandit** — security scan (`-r src/ -ll` — low severity and above)
- [ ] **prettier** — frontend formatting
- [ ] **svelte-check** — TypeScript + Svelte validation

### Bandit Configuration

Add to `pyproject.toml`:

```toml
[tool.bandit]
exclude_dirs = ["tests", ".venv"]
skips = ["B101"]  # assert used in tests
```

---

## Phase 3: Dependency Security

- [ ] **Dependabot** or **Renovate** for automated dependency updates
- [ ] Pin exact versions in `uv.lock` and `pnpm-lock.yaml` (already done)
- [ ] Weekly `pip-audit` + `npm audit` in CI
- [ ] Review and update quarterly

---

## What We Already Have

| Check | Where | Status |
|-------|-------|--------|
| ruff (lint) | Local | Running |
| pytest (505 tests) | Local | Running |
| vitest (131 tests) | Local | Running |
| svelte-check | Local | Running |
| eslint + prettier | Local | Running |
| vulture (dead code) | Local | Configured |

---

## Priority

1. GitHub Actions CI (immediate — catch regressions on push)
2. Bandit in CI (security baseline)
3. Pre-commit hooks (developer convenience)
4. Dependency scanning (ongoing maintenance)

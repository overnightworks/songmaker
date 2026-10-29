#!/usr/bin/env bash
# Run songmaker's static CI gates locally, cheapest first, stopping at the first red one.
# Usage: bash scripts/static_checks.sh   (from anywhere; runs at the repository root)
# Needs .venv (uv sync --frozen --extra server --extra dev --extra mcp --extra agent-service --extra image)
# and frontend/node_modules (pnpm install --frozen-lockfile in frontend/), as CI does.
# Sonar and tests are not run here: Sonar needs CI, tests stay targeted.
# Each command and flag is copied from .github/workflows/ci.yml; keep them in step.
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

[[ -x .venv/bin/ruff ]] || { echo "static_checks: .venv is missing or incomplete; run: uv sync --frozen --extra server --extra dev --extra mcp --extra agent-service --extra image" >&2; exit 2; }
[[ -d frontend/node_modules ]] || { echo "static_checks: frontend/node_modules is missing; run: pnpm install --frozen-lockfile (in frontend/)" >&2; exit 2; }

export PATH="$PWD/.venv/bin:$PATH"

gate() {
    local name=$1
    shift
    echo "== $name"
    if ! "$@"; then
        echo "static_checks: RED: $name" >&2
        exit 1
    fi
}

in_frontend() {
    (cd frontend && "$@")
}

# why: a pin read at run time cannot drift from the one CI runs.
quality_pin=$(sed -n 's|.*overnightworks/quality/\.github/workflows/gate\.yml@\([0-9a-f]\{40\}\).*|\1|p' .github/workflows/ci.yml | head -n 1)
[[ -n $quality_pin ]] || { echo "static_checks: no quality gate pin found in .github/workflows/ci.yml" >&2; exit 2; }
quality_engines_dir="${XDG_CACHE_HOME:-$HOME/.cache}/songmaker-static-checks/quality-engines-$quality_pin"

quality() {
    uvx --from "git+https://github.com/overnightworks/quality@$quality_pin" quality "$@"
}

hygiene() {
    quality engines install "$quality_engines_dir" && quality hygiene --engines "$quality_engines_dir" .
}

gate "Root layout" python scripts/check_root_layout.py
gate "CI and compose pin the same Postgres image" python scripts/check_pinned_images_match.py
gate "Ruff lint" ruff check src/ tests/
gate "Test helper duplication ratchet" scripts/test_helper_ratchet.sh
gate "No silent-fallback smell check" python scripts/check_no_silent_fallbacks.py src/
gate "No unreferenced backend symbols" python scripts/check_dead_symbols.py
gate "TypeScript types in sync" python scripts/generate_types.py --check
gate "No test-only-alive exports" in_frontend bash ../scripts/check_test_only_exports.sh
gate "No new style literals" in_frontend python3 ../scripts/check_style_literals.py
gate "Frontend lint (eslint, prettier)" in_frontend pnpm lint
gate "Svelte check" in_frontend pnpm check
gate "Quality hygiene (pin ${quality_pin:0:12})" hygiene

echo "static_checks: all gates passed"

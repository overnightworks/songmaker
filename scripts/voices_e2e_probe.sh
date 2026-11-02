#!/usr/bin/env bash
# Runs the Voices browser proof (frontend/e2e/voices.spec.ts) against its own
# isolated stack, then removes the stack. The stack is the CI one plus the
# test-only fake training worker; every value below is test-only.
#
# Run it only under the probe lock, as one capped command:
#   flock -o -w 3600 /tmp/probe-stack.lock setpriv --pdeathsig TERM timeout -k 120 1700 scripts/voices_e2e_probe.sh
# CAP 1700 + K 120 = 1820, within the lock contract's 1830. K covers the
# teardown (`down -v --remove-orphans`), measured at about 2 s, with room for a slower disk.
#
# The exit code is the proof's own; a failed build or start exits non-zero too.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PROBE_PORT=18080

secret_file="$(mktemp)"
echo e2e-ci-client-secret > "$secret_file"

export COMPOSE_PROJECT_NAME=songmaker-i689-probe
export WEB_PORT="$PROBE_PORT"
export POSTGRES_PASSWORD=e2e-ci-postgres-password
export SESSION_SECRET=e2e-ci-session-secret-do-not-reuse-anywhere-else
export SONGMAKER_INTERNAL_TOKEN=e2e-ci-internal-token
export E2E_ADMIN_USERNAME=e2e-ci-admin
export OIDC_ISSUER=https://keycloak.invalid/realms/e2e
export KEYCLOAK_CLIENT_SECRET_FILE="$secret_file"
export GRAFANA_PASSWORD=e2e-ci-grafana-password
export PUBLIC_BASE_URL="http://localhost:$PROBE_PORT"
export E2E_BASE_URL="http://localhost:$PROBE_PORT"
export E2E_VOICES_STACK=1

cd "$PROJECT_ROOT"
compose=(docker compose -f docker-compose.yml -f docker/docker-compose.ci.yml
    -f docker/docker-compose.e2e-voices.yml)

teardown() {
    trap - EXIT TERM
    "${compose[@]}" down -v --remove-orphans
    rm -f "$secret_file"
}
trap teardown EXIT
trap 'teardown; exit 143' TERM

"${compose[@]}" up -d --build --wait \
    postgres redis migrate songmaker-web songmaker-music-worker \
    songmaker-voices-e2e-worker

cd frontend
pnpm exec playwright test e2e/voices.spec.ts

#!/usr/bin/env bash
# Runs the Voices browser proof (frontend/e2e/voices.spec.ts) against its own
# isolated stack, then removes the stack. The stack is the CI one plus the
# test-only fake training worker; every value below is test-only.
#
# Run it only under the probe lock, as one capped command:
#   flock -o -w 3600 /tmp/probe-stack.lock setpriv --pdeathsig TERM timeout -k 120 1700 scripts/voices_e2e_probe.sh
# CAP 1700 + K 120 = 1820, within the lock contract's 1830. K covers the
# teardown (`--profile gpu down -v --remove-orphans --rmi local`), measured at
# about 2 s without the image removal; 120 s leaves room for removing the
# probe's images.
#
# The exit code is the proof's own; a failed build or start exits non-zero too.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PROBE_PORT=18080

secrets_dir="$(mktemp -d)"
echo e2e-ci-postgres-password > "$secrets_dir/postgres-password"
echo e2e-ci-session-secret-do-not-reuse-anywhere-else > "$secrets_dir/session-secret"
echo e2e-ci-internal-token > "$secrets_dir/internal-token"
echo e2e-ci-monitoring-token > "$secrets_dir/monitoring-token"
secret_file="$(mktemp)"
echo e2e-ci-client-secret > "$secret_file"
gateway_key_file="$(mktemp)"
echo e2e-ci-gateway-key > "$gateway_key_file"

export COMPOSE_PROJECT_NAME=songmaker-i689-probe
export WEB_PORT="$PROBE_PORT"
export SONGMAKER_SECRETS_DIR="$secrets_dir"
export E2E_ADMIN_USERNAME=e2e-ci-admin
export OIDC_ISSUER=https://keycloak.invalid/realms/e2e
export KEYCLOAK_CLIENT_SECRET_FILE="$secret_file"
export GATEWAY_KEY_FILE="$gateway_key_file"
export PUBLIC_BASE_URL="http://localhost:$PROBE_PORT"
export E2E_BASE_URL="http://localhost:$PROBE_PORT"
export E2E_VOICES_STACK=1

cd "$PROJECT_ROOT"
compose=(docker compose --project-directory . -f docker/docker-compose.test.yml
    -f docker/docker-compose.e2e-voices.yml)

teardown() {
    trap - EXIT TERM
    # The overlay puts the GPU workers in the gpu profile; without the profile,
    # down leaves them running. --rmi local removes the images the run built.
    "${compose[@]}" --profile gpu down -v --remove-orphans --rmi local
    rm -rf "$secrets_dir"
    rm -f "$secret_file" "$gateway_key_file"
}
trap teardown EXIT
trap 'teardown; exit 143' TERM

# Two steps: the stack has no restart policy, so the apps start only once the
# stores are healthy, and the fake worker only once web is.
"${compose[@]}" up -d --wait postgres redis
"${compose[@]}" up -d --build --wait songmaker-web songmaker-music-worker
"${compose[@]}" up -d --build --wait songmaker-voices-e2e-worker

pnpm --dir frontend exec playwright test e2e/voices.spec.ts

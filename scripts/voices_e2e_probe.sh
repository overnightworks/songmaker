#!/usr/bin/env bash
# Runs the Voices browser proof (frontend/e2e/voices.spec.ts) against its own
# isolated stack, then removes the stack. The stack is the CI one plus the
# test-only fake training worker; every value below is test-only.
#
# Run it directly, not through probe-run: the script builds the images, starts
# the stack and waits until it is healthy on its own time, then runs only the
# drive (the Playwright proof) under `probe-run -k 30 1700`. CAP 1700 + K 30 =
# 1730, within probe-run's 1830; K is the time the drive gets to stop after TERM.
# The teardown (`--profile gpu down -v --remove-orphans --rmi local`) runs in
# this script's trap after the drive, outside the cap; it was measured at about
# 2 s without the image removal.
#
# Each run takes its own Compose project name and a free loopback port, so
# two runs at once do not share a stack.
#
# The exit code is the proof's own; a failed build or start exits non-zero too.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PROBE_PORT="$("$SCRIPT_DIR/free_loopback_port.sh")"

secrets_dir="$(mktemp -d)"
echo e2e-ci-postgres-password > "$secrets_dir/postgres-password"
echo e2e-ci-session-secret-do-not-reuse-anywhere-else > "$secrets_dir/session-secret"
echo e2e-ci-internal-token > "$secrets_dir/internal-token"
echo e2e-ci-monitoring-token > "$secrets_dir/monitoring-token"
secret_file="$(mktemp)"
echo e2e-ci-client-secret > "$secret_file"
gateway_key_file="$(mktemp)"
echo e2e-ci-gateway-key > "$gateway_key_file"

export COMPOSE_PROJECT_NAME="songmaker-voices-probe-$$"
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
drive_pid=""
# Ending the drive first lets the EXIT trap tear the stack down at once.
stop_drive() {
    [[ -z "$drive_pid" ]] || kill -TERM "$drive_pid" 2>/dev/null || true
    exit 143
}
trap teardown EXIT
trap stop_drive TERM

# Two steps: the stack has no restart policy, so the apps start only once the
# stores are healthy, and the fake worker only once web is.
"${compose[@]}" up -d --wait postgres redis
"${compose[@]}" up -d --build --wait songmaker-web songmaker-music-worker
"${compose[@]}" up -d --build --wait songmaker-voices-e2e-worker

probe-run -k 30 1700 pnpm --dir frontend exec playwright test e2e/voices.spec.ts &
drive_pid=$!
wait "$drive_pid"

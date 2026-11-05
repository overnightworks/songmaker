#!/usr/bin/env bash
# Runs pytest against a disposable PostgreSQL, then removes it.
# Usage: scripts/test_postgresql.sh <test files and pytest arguments>
#   PYTEST_XDIST_AUTO_NUM_WORKERS=4 scripts/test_postgresql.sh tests/songmaker_cli/test_lock_guard_postgres.py -q
#
# The container runs Compose's PostgreSQL image pin on a free loopback port, on tmpfs,
# without durability and without any deployment configuration or volume; every value
# below is test-only. Tests in each xdist worker get their own databases from
# tests/support/postgresql.py. The run takes no shared probe-stack lock (operator ruling
# in #2280); it checks the load and caps pytest instead:
#   setpriv --pdeathsig TERM timeout -k 30 1200
# CAP 1200 s holds a targeted run; K 30 s lets pytest drop its databases after TERM.
# The trapped teardown (`docker rm -f`, measured at about 0.2 s) runs in this shell,
# outside the cap, because timeout kills its child outright on a second interrupt. The
# container stops itself after CAP + K + 30 s in case this shell is killed outright.

set -euo pipefail

CAP_SECONDS=1200
KILL_AFTER_SECONDS=30
CONTAINER_LIFETIME_SECONDS=$((CAP_SECONDS + KILL_AFTER_SECONDS + 30))

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

cores=$(nproc)
load=$(cut -d ' ' -f 1 /proc/loadavg)
if awk -v load="$load" -v cores="$cores" 'BEGIN { exit !(load > 1.5 * cores) }'; then
    echo "test_postgresql: one-minute load $load is above 1.5 x $cores cores; wait and retry" >&2
    exit 75
fi

python=.venv/bin/python
[[ -x $python ]] || { echo "test_postgresql: .venv is missing; run uv sync as the README says" >&2; exit 2; }
docker info > /dev/null 2>&1 || { echo "test_postgresql: Docker is not reachable" >&2; exit 2; }

image=$("$python" -c '
import yaml
print(yaml.safe_load(open("docker-compose.yml"))["services"]["postgres"]["image"])
')
container="songmaker-test-postgresql-$(od -An -N6 -tx1 /dev/urandom | tr -d ' \n')"
password=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')

teardown() {
    trap - EXIT
    trap '' INT TERM
    docker rm -f "$container" > /dev/null 2>&1 || true
}
trap teardown EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

docker run --detach --rm --name "$container" \
    --publish 127.0.0.1::5432 \
    --tmpfs /var/lib/postgresql/data \
    --env POSTGRES_USER=songmaker_test \
    --env POSTGRES_PASSWORD="$password" \
    --env POSTGRES_DB=songmaker_test \
    --entrypoint timeout \
    "$image" \
    "$CONTAINER_LIFETIME_SECONDS" docker-entrypoint.sh postgres \
    -c fsync=off -c synchronous_commit=off -c full_page_writes=off > /dev/null

ready=
for _ in $(seq 60); do
    if docker exec "$container" pg_isready --quiet --host 127.0.0.1 --username songmaker_test; then
        ready=1
        break
    fi
    sleep 0.5
done
[[ -n $ready ]] || { echo "test_postgresql: PostgreSQL in $container did not become ready" >&2; exit 2; }

port=$(docker port "$container" 5432/tcp | head -n 1)
port=${port##*:}

TEST_DATABASE_URL="postgresql://songmaker_test:$password@127.0.0.1:$port/songmaker_test" \
    setpriv --pdeathsig TERM timeout -k "$KILL_AFTER_SECONDS" "$CAP_SECONDS" \
    "$python" -m pytest -n auto "$@"

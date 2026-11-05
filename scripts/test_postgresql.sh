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
# CAP 1200 s holds a targeted run; K 30 s bounds pytest's exit after TERM.
# pytest runs as a background job, so this shell's INT, TERM and HUP traps run at once:
# they send TERM to timeout, which passes it to its whole process group (pytest and its
# xdist workers), wait for it and remove the container. A terminal's Ctrl-C reaches only
# this shell, never timeout's own process group. A background job starts with SIGINT
# ignored, which every process pytest starts would inherit; `env --default-signal=INT`
# restores it. Every Docker call is capped as well: DOCKER_CALL_SECONDS each,
# DOCKER_START_SECONDS for the start, which may pull the pinned image, and READY_SECONDS
# for readiness. The removal, measured at about 0.2 s, runs in this shell after pytest
# has ended; the container also stops itself after its lifetime in case this shell is
# killed outright.

set -euo pipefail

CAP_SECONDS=1200
KILL_AFTER_SECONDS=30
DOCKER_CALL_SECONDS=30
DOCKER_START_SECONDS=300
READY_SECONDS=30
CONTAINER_LIFETIME_SECONDS=$((READY_SECONDS + CAP_SECONDS + KILL_AFTER_SECONDS + DOCKER_CALL_SECONDS))

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

cores=$(nproc)
load=$(cut -d ' ' -f 1 /proc/loadavg)
if awk -v load="$load" -v cores="$cores" 'BEGIN { exit !(load > 1.5 * cores) }'; then
    echo "test_postgresql: one-minute load $load is above 1.5 x $cores cores; wait and retry" >&2
    exit 75
fi

capped_docker() {
    local seconds=$1
    shift
    timeout --foreground -k 5 "$seconds" docker "$@"
}

python=.venv/bin/python
[[ -x $python ]] || { echo "test_postgresql: .venv is missing; run uv sync as the README says" >&2; exit 2; }
capped_docker "$DOCKER_CALL_SECONDS" info > /dev/null 2>&1 \
    || { echo "test_postgresql: Docker is not reachable" >&2; exit 2; }

image=$("$python" -c '
import yaml
print(yaml.safe_load(open("docker-compose.yml"))["services"]["postgres"]["image"])
')
container="songmaker-test-postgresql-$(od -An -N6 -tx1 /dev/urandom | tr -d ' \n')"
password=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
pytest_pid=

stop_pytest() {
    if [[ -n $pytest_pid ]]; then
        kill -TERM "$pytest_pid" 2> /dev/null || true
        wait "$pytest_pid" 2> /dev/null || true
        pytest_pid=
    fi
}

# `docker rm -f` succeeds for a container that is already gone, as after its own --rm;
# a container that still exists after a failed removal fails the run.
teardown() {
    local status=$?
    trap - EXIT
    trap '' INT TERM HUP
    stop_pytest
    local removal
    if ! removal=$(capped_docker "$DOCKER_CALL_SECONDS" rm -f "$container" 2>&1) \
        && capped_docker "$DOCKER_CALL_SECONDS" container inspect "$container" > /dev/null 2>&1; then
        echo "test_postgresql: could not remove container $container: $removal" >&2
        exit 1
    fi
    exit "$status"
}
interrupted() {
    trap '' INT TERM HUP
    stop_pytest
    exit "$1"
}
trap teardown EXIT
trap 'interrupted 129' HUP
trap 'interrupted 130' INT
trap 'interrupted 143' TERM

capped_docker "$DOCKER_START_SECONDS" run --detach --rm --name "$container" \
    --publish 127.0.0.1::5432 \
    --tmpfs /var/lib/postgresql/data \
    --env POSTGRES_USER=songmaker_test \
    --env POSTGRES_PASSWORD="$password" \
    --env POSTGRES_DB=songmaker_test \
    --entrypoint timeout \
    "$image" \
    "$CONTAINER_LIFETIME_SECONDS" docker-entrypoint.sh postgres \
    -c fsync=off -c synchronous_commit=off -c full_page_writes=off > /dev/null

ready_by=$((SECONDS + READY_SECONDS))
until capped_docker 5 exec "$container" pg_isready --quiet --host 127.0.0.1 --username songmaker_test; do
    if ((SECONDS >= ready_by)); then
        echo "test_postgresql: PostgreSQL in $container did not become ready" >&2
        exit 2
    fi
    sleep 0.5
done

port=$(capped_docker "$DOCKER_CALL_SECONDS" port "$container" 5432/tcp | head -n 1)
port=${port##*:}

TEST_DATABASE_URL="postgresql://songmaker_test:$password@127.0.0.1:$port/songmaker_test" \
    env --default-signal=INT setpriv --pdeathsig TERM timeout -k "$KILL_AFTER_SECONDS" "$CAP_SECONDS" \
    "$python" -m pytest -n auto "$@" &
pytest_pid=$!
status=0
wait "$pytest_pid" || status=$?
pytest_pid=
exit "$status"

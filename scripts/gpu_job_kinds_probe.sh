#!/usr/bin/env bash
# Proves on the real GPU that all five job kinds still work: generation,
# reference, repaint, cover and LoRA training. It starts its own compose
# project (one acestep worker on the GPU, the web process, the music worker,
# Postgres and Redis), drives each kind through the API as a throwaway admin,
# and judges each by its outcome: a completed job, a take row whose mp3 and
# wav are served with its raw.wav beside them, a LoRA adapter adopted (status
# ready, its storage path holding the adapter's files), and nothing left in the
# worker's local output root.
#
# Usage, only as one capped command under the probe lock:
#   flock -o -w 3600 /tmp/probe-stack.lock setpriv --pdeathsig TERM timeout -k 120 1700 \
#       scripts/gpu_job_kinds_probe.sh <deploy checkout>/vendor/acestep/checkpoints
# CAP 1700 + K 120 = 1820, within the lock contract's 1830. K covers the
# teardown (`--profile gpu down -v --remove-orphans --rmi local`), measured at
# about 2 s on the voices stack without the image removal; 120 s leaves room
# for a worker that still holds the GPU and for removing the probe's images.
#
# The operator stops the live `acestep-worker-0` first and restarts it after;
# the script refuses to start while one runs (one GPU, one worker name).
# The checkpoint directory is mounted read-only, so the probe cannot change the
# deploy's models. The script never touches the live project, port 8080 or an
# `.env`: every compose call reads an empty environment file instead of the
# checkout's `.env`, and every secret below is a throwaway.
#
# The exit code is the proof's: 0 only when all five kinds held and the
# teardown left nothing behind.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PROBE_PORT=18081
PROJECT=songmaker-gpu-probe
WORKER_SERVICE=songmaker-acestep-worker-0
# Takes of 8 s and a LoRA of 5 epochs keep the whole proof well inside the cap.
TAKE_SECONDS=8
LORA_EPOCHS=5
JOB_TIMEOUT_SECONDS=420
LORA_TIMEOUT_SECONDS=900

usage() {
    echo "usage: $0 <checkpoints directory of the deploy checkout>" >&2
    exit 2
}

[[ $# -eq 1 ]] || usage
checkpoints="$1"
[[ -d "$checkpoints" ]] || { echo "not a directory: $checkpoints" >&2; usage; }
checkpoints="$(cd "$checkpoints" && pwd)"

refuse_while_another_worker_runs() {
    local running
    running="$(docker ps --filter "label=com.docker.compose.service=$WORKER_SERVICE" \
        --format '{{.Names}} {{.Label "com.docker.compose.project"}}')"
    while read -r name project; do
        [[ -z "$name" || "$project" == "$PROJECT" ]] && continue
        echo "refusing to start: $name (compose project $project) runs $WORKER_SERVICE;" \
            "the operator stops the live worker first" >&2
        exit 3
    done <<<"$running"
}
refuse_while_another_worker_runs

work_dir="$(mktemp -d)"
secrets_dir="$work_dir/secrets"
mkdir "$secrets_dir"
echo gpu-probe-postgres-password > "$secrets_dir/postgres-password"
echo gpu-probe-session-secret-do-not-reuse-anywhere-else > "$secrets_dir/session-secret"
echo gpu-probe-internal-token > "$secrets_dir/internal-token"
echo gpu-probe-monitoring-token > "$secrets_dir/monitoring-token"
echo gpu-probe-client-secret > "$work_dir/client-secret"
echo gpu-probe-gateway-key > "$work_dir/gateway-key"
# Compose reads the checkout's `.env` unless it is handed another file.
: > "$work_dir/empty.env"
unset COMPOSE_ENV_FILES

# Compose merges a volume by its container path: only the checkpoints entry changes.
cat > "$work_dir/checkpoints-readonly.yml" <<'EOF'
services:
  songmaker-acestep-worker-0:
    volumes:
      - ${GPU_PROBE_CHECKPOINTS}:/opt/acestep/checkpoints:ro
EOF

export COMPOSE_PROJECT_NAME="$PROJECT"
export WEB_PORT="$PROBE_PORT"
export GPU_PROBE_CHECKPOINTS="$checkpoints"
export SONGMAKER_SECRETS_DIR="$secrets_dir"
export KEYCLOAK_CLIENT_SECRET_FILE="$work_dir/client-secret"
export GATEWAY_KEY_FILE="$work_dir/gateway-key"
export OIDC_ISSUER=https://keycloak.invalid/realms/gpu-probe
export GRAFANA_PASSWORD=gpu-probe-grafana-password
export PUBLIC_BASE_URL="http://localhost:$PROBE_PORT"
export LORA_TRAINING_EPOCHS="$LORA_EPOCHS"
export LORA_TRAINING_SAVE_EVERY_N_EPOCHS="$LORA_EPOCHS"

cd "$PROJECT_ROOT"
compose=(docker compose --env-file "$work_dir/empty.env"
    -f docker-compose.yml -f docker/docker-compose.ci.yml
    -f "$work_dir/checkpoints-readonly.yml")
base="http://127.0.0.1:$PROBE_PORT"
cookie=""

teardown() {
    local status=$?
    trap - EXIT TERM
    # The CI override puts the GPU and music services in the gpu profile; without
    # the profile, down leaves them running. The images it built go too: the
    # worker's alone is about 9 GB.
    "${compose[@]}" --profile gpu down -v --remove-orphans --rmi local || status=1
    rm -rf "$work_dir"
    local left
    left="$(docker ps -a -q --filter "label=com.docker.compose.project=$PROJECT")$(
        docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT")"
    if [[ -n "$left" ]]; then
        echo "FAIL teardown: containers or volumes of $PROJECT remain" >&2
        status=1
    else
        echo "PROOF teardown: nothing of $PROJECT remains"
    fi
    exit "$status"
}
trap teardown EXIT
trap 'exit 143' TERM

api() { # api METHOD PATH [curl args...]; the Origin passes the app's same-origin CSRF check
    local method="$1" path="$2"
    shift 2
    curl -fsS -X "$method" -b "$cookie" -H "Origin: $base" "$base$path" "$@"
}

api_json() { # api_json METHOD PATH JSON
    api "$1" "$2" -H 'Content-Type: application/json' -d "$3"
}

fail() {
    echo "FAIL $*" >&2
    exit 1
}

wait_for_job() { # wait_for_job JOB_ID LABEL
    local deadline=$((SECONDS + JOB_TIMEOUT_SECONDS)) status
    while ((SECONDS < deadline)); do
        status="$(api GET "/api/jobs/$1" | jq -r .status)"
        case "$status" in
            completed) return 0 ;;
            failed | partial | cancelled) fail "$2: job $1 ended $status: $(api GET "/api/jobs/$1" | jq -c '{error,error_type}')" ;;
        esac
        sleep 5
    done
    fail "$2: job $1 still $status after ${JOB_TIMEOUT_SECONDS}s"
}

newest_take() { # newest_take SONG_ID -> JSON of the song's newest generation
    api GET "/api/songs/$1" | jq -c '.generations | sort_by(.created_at) | last'
}

audio_file_exists() { # audio_file_exists RELATIVE_PATH: a non-empty file in the audio tree
    "${compose[@]}" exec -T songmaker-web sh -c 'test -s "$1"' _ "/app/data/audio/$1"
}

prove_take() { # prove_take LABEL TAKE_JSON: an mp3 and a wav served, the raw.wav beside them
    local label="$1" take="$2" kind path size wav
    for kind in mp3_path wav_path; do
        path="$(jq -r ".$kind // empty" <<<"$take")"
        [[ -n "$path" ]] || fail "$label: take has no $kind"
        size="$(api GET "/audio/$path" | wc -c)"
        ((size > 1000)) || fail "$label: /audio/$path served only $size bytes"
    done
    wav="$(jq -r .wav_path <<<"$take")"
    audio_file_exists "${wav%.wav}.raw.wav" || fail "$label: no raw.wav beside $wav"
    echo "PROOF $label: take $(jq -r .id <<<"$take") with its mp3 and wav served and its raw.wav kept"
}

generate_kind() { # generate_kind LABEL PATH JSON SONG_ID
    local job
    job="$(api_json POST "$2" "$3" | jq -r .id)"
    wait_for_job "$job" "$1"
    prove_take "$1" "$(newest_take "$4")"
}

"${compose[@]}" --profile gpu up -d --build --wait \
    postgres redis migrate songmaker-web songmaker-music-worker "$WORKER_SERVICE"

echo "--- checkpoints read-only ---"
if "${compose[@]}" exec -T "$WORKER_SERVICE" sh -c 'touch /opt/acestep/checkpoints/.gpu-probe-write' 2>/dev/null; then
    fail "the worker could write into the checkpoint mount"
fi
echo "PROOF checkpoints: the worker cannot write into /opt/acestep/checkpoints"

# The stack has no admin bootstrap: the seeding helper opens a database session
# for a throwaway admin, signed as the app signs it.
seeded="$("${compose[@]}" exec -T \
    -e 'SEED_SESSIONS_REQUEST={"seed":[{"username":"gpu-probe-admin","role":"admin"}]}' \
    songmaker-web /app/.venv/bin/python - < frontend/e2e/support/seed_sessions.py | tail -n 1)"
cookie="$(jq -r '.[0] | "\(.session_cookie_name)=\(.session_cookie_value)"' <<<"$seeded")"
# A fresh stack activates only songmaker's default model; the probe takes what it offers.
model="$(api GET /api/settings/models | jq -r 'first.id // empty')"
[[ -n "$model" ]] || fail "the stack offers no active model"

album="$(api_json POST /api/albums '{"title":"gpu-probe album","artist":"gpu-probe"}' | jq -r .id)"
song_body="$(jq -nc --arg album "$album" --argjson seconds "$TAKE_SECONDS" '{
    title: "gpu-probe song", album_id: $album, audio_duration: $seconds,
    lyrics: "[verse]\nla la la la\nla la la la", prompt: "calm piano, slow"}')"
song="$(api_json POST /api/songs "$song_body" | jq -r .id)"
generate_body="$(jq -nc --arg model "$model" '{count: 1, model: $model}')"

# 1. Generation
generate_kind generation "/api/songs/$song/generate" "$generate_body" "$song"
source_take="$(newest_take "$song")"
source_id="$(jq -r .id <<<"$source_take")"

# 2. Reference: the first take, uploaded as the song's reference recording
api GET "/audio/$(jq -r .wav_path <<<"$source_take")" -o "$work_dir/reference.wav"
reference="$(api POST /api/references -F "file=@$work_dir/reference.wav;filename=reference.wav" | jq -r .id)"
api_json PUT "/api/songs/$song" "$(jq -nc --arg id "$reference" '{reference_recording_id: $id}')" > /dev/null
generate_kind reference "/api/songs/$song/generate" "$generate_body" "$song"
[[ "$(newest_take "$song" | jq -r '.reference.id // empty')" == "$reference" ]] \
    || fail "reference: the new take does not link the uploaded reference"
echo "PROOF reference: the new take links reference $reference"

# 3. Repaint the middle of the first take
repaint_body="$(jq -nc --arg src "$source_id" --arg model "$model" '{
    src_generation_id: $src, repainting_start: 0.3, repainting_end: 0.6, count: 1, model: $model}')"
generate_kind repaint "/api/generations/$source_id/repaint" "$repaint_body" "$song"

# 4. Cover of the first take
cover_body="$(jq -nc --arg src "$source_id" --arg model "$model" '{
    src_generation_id: $src, count: 1, model: $model}')"
generate_kind cover "/api/generations/$source_id/cover" "$cover_body" "$song"

# 5. LoRA training on three of the takes, then the adopted adapter
voice="$(api_json POST /api/loras '{"name":"gpu-probe voice"}' | jq -r .id)"
for take_id in $(api GET "/api/songs/$song" | jq -r '.generations | sort_by(.created_at) | .[:3][].id'); do
    api_json POST "/api/loras/$voice/samples/from-generation" \
        "$(jq -nc --arg id "$take_id" '{generation_id: $id}')" > /dev/null
done
api POST "/api/loras/$voice/train" > /dev/null
lora_deadline=$((SECONDS + LORA_TIMEOUT_SECONDS))
while ((SECONDS < lora_deadline)); do
    lora="$(api GET "/api/loras/$voice")"
    status="$(jq -r .status <<<"$lora")"
    [[ "$status" == ready ]] && break
    [[ "$status" == failed ]] && fail "lora: training failed: $(jq -c '{error}' <<<"$lora")"
    sleep 10
done
[[ "$(jq -r .status <<<"$lora")" == ready ]] || fail "lora: still $status after ${LORA_TIMEOUT_SECONDS}s"
# A trained adapter is adopted as its storage path (jobs/lora_training.py, _mark_lora_training_complete).
storage="$(jq -r '.storage_path // empty' <<<"$lora")"
[[ -n "$storage" ]] || fail "lora: ready without a storage path"
"${compose[@]}" exec -T songmaker-web sh -c 'test -n "$(ls -A "$1")"' _ "/app/data/audio/$storage" \
    || fail "lora: no adapter files under $storage"
echo "PROOF lora: voice $voice ready with its adapter adopted ($storage)"

echo "--- nothing on the shared volume from the worker ---"
if "${compose[@]}" exec -T songmaker-web sh -c 'ls /app/data/audio/worker_output/*.wav' > /dev/null 2>&1; then
    fail "generation: the worker left a take on the shared audio volume"
fi
echo "PROOF output: no take under the shared audio volume's worker_output"
# An unset root, a missing one or a failed listing fails here instead of reading as empty.
"${compose[@]}" exec -T "$WORKER_SERVICE" sh -c \
    'set -eu; test -d "$AUDIO_OUTPUT_DIR"; listing=$(ls -A "$AUDIO_OUTPUT_DIR"); test -z "$listing"' \
    || fail "generation: the worker's local output root is not readable as empty"
echo "PROOF output: the worker's local output root is empty"
echo "PROOF all five job kinds held"

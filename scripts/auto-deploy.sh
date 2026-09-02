#!/bin/bash
# Pull-based auto-deploy for Songmaker (issue #298).
#
# A GitOps timer, not a webhook or a self-hosted CI runner: this script polls
# origin/main every couple of minutes (see songmaker-autodeploy.timer) and
# fast-forwards + redeploys the local checkout when main has moved. Before it
# pulls, it verifies through GitHub that every check run for the fetched
# commit has completed successfully; the script itself does not re-run tests.
#
# Safety rules below come from real incidents, not hypotheticals:
#   - A redeploy on 2026-08-30 18:31 mid-generation killed every in-flight
#     stream. `docker compose build` (image build only, no container
#     recreate) is now separated from `docker compose up -d --wait`
#     (container recreate). The active-jobs check runs once before the pull
#     and again right before the recreate step, so the only window a job can
#     start and still get killed is the few seconds between that second
#     check and the recreate — not the 8-15 minutes a cold-cache build can
#     take. A build-only tick that finds jobs active on the recheck defers
#     to the next tick, which finds the image already built and is back at
#     the recheck within seconds.
#   - "Up to date" is judged against what actually got recreated, not just
#     what got pulled. A `deployed.sha` file in the state directory is
#     written ONLY by `record_success`, right after `compose up -d --wait`
#     succeeds. Up-to-date means `HEAD == origin/$DEPLOY_BRANCH` AND
#     `deployed.sha == HEAD` — not `HEAD == origin/$DEPLOY_BRANCH` alone.
#     Without this, a tick that pulled and built but deferred the recreate
#     (jobs still active, or a build/up failure) already sits on the new
#     HEAD; every following tick then saw "local == remote" and treated the
#     stale running containers as "nothing to deploy" forever, silently
#     resetting the setback counter along the way. The first tick that ever
#     finds no `deployed.sha` (fresh install) adopts the current HEAD as
#     already-deployed instead of deploying — the operator chose that to
#     keep `install-autodeploy.sh`'s `enable --now` harmless; the
#     consequence is that a checkout installed while behind main stays on
#     the stale stack until the operator deploys it once by hand (see
#     docs/architecture.md).
#   - Migrations occasionally abort loudly on lock_timeout (see the
#     c9d4a2f18e37 unique-slug-index migration). That is not fatal — the
#     next tick retries the same pull+deploy. A tick that could not deploy
#     despite main having moved (a hard refusal, or a pull/build/up
#     failure) increments a consecutive-FAILURE counter; only the tick
#     that crosses N in a row escalates to a prio=err journal line worth
#     paging on — and, since issue #333, is also the only tick that exits
#     non-zero (fail_tick below), so `OnFailure=songmaker-alert@%n.service`
#     on the systemd unit emails the operator at that exact same moment
#     instead of on every transient blip. A streak that simply continues
#     escalates again once every ALERT_REPEAT_SECONDS of wall-clock time,
#     so an outage nobody reacts to stays visible without mailing every
#     two minutes (see escalation_due). A tick that merely defers because
#     jobs are active
#     increments a separate consecutive-BUSY counter with a much higher
#     threshold and a quieter prio=warning line, never fails the unit — a
#     normal generation queue or an hours-long lora_training job
#     legitimately keeps jobs active for a long time, and that is not the
#     same emergency as a deploy that keeps failing outright (see
#     record_failure / fail_tick / record_busy_deferral below). Both
#     counters reset only after a deploy and its Docker cleanup both succeed,
#     or on a genuine "nothing to deploy" tick.
#   - This host's `.env` and checkout are also the operator's manual
#     workspace. A dirty tree, a diverged local main, or HEAD sitting on a
#     branch other than the deploy branch are left completely untouched —
#     the script only ever fast-forwards a clean checkout of the deploy
#     branch. The up-to-date shortcut (including the deployed.sha check)
#     runs BEFORE this branch guard: an operator sitting on an experiment
#     branch with nothing actually pending to deploy must not get a loud
#     err line every ~2 minutes for no reason (see step ordering below).
#
# Per CLAUDE.md: NEVER wrap `docker compose up --build --wait` in `timeout`.
# A cold-cache rebuild can take 8-15 minutes; the systemd unit has no
# TimeoutStartSec override for the same reason. That rule is about the
# image BUILD, not about the DB round-trip the active-jobs check makes —
# that one gets its own short `timeout` (see below) so a wedged DB
# connection can't hang a tick indefinitely. `compose build` and
# `compose up` both stream straight to this process's stdout/stderr (which
# systemd journals under the unit) rather than being captured into a
# variable — a failed build can print far more than a single logger
# invocation can safely carry as one argument, so only a short log_err line
# with the exit code goes through `logger`. `log()` itself additionally
# truncates any payload to ~2000 chars as a second line of defense for
# every other captured-output log line in this script (git status, pull,
# fetch, the DB check).
#
# All journal lines are tagged "songmaker-autodeploy" (`journalctl -t
# songmaker-autodeploy`). The steady-state "nothing to do" tick (the common
# case, every ~2 minutes) logs at debug priority — an unfiltered `journalctl
# -t songmaker-autodeploy` still shows it (journald keeps everything by
# default), but any priority-restricted view (e.g. `journalctl -t
# songmaker-autodeploy -p info`, or a dashboard/alerting rule that only
# watches info-and-above) stays quiet, and only real events (deferred,
# refused, deployed, failed) surface there. If a tick dies before it ever
# reaches `logger` (e.g. the shell itself fails to start), the tag-filtered
# view is empty by construction — `journalctl -u
# songmaker-autodeploy.service -n 20` (unit-filtered, not tag-filtered)
# still shows it.
#
# REPO_ROOT is derived from where this script itself lives (same pattern as
# install-autostart.sh's SCRIPT_DIR/PROJECT_ROOT derivation), never hardcoded
# here — running it from a worktree operates on that worktree. The installer
# (scripts/install-autodeploy.sh) separately substitutes the matching
# WorkingDirectory/User/ExecStart into the systemd unit, exactly like
# install-autostart.sh does for songmaker.service.
#
# LOCK_FILE and all state files (the two counters, the two escalation
# timestamps, DEPLOYED_SHA_FILE) live at a fixed path inside the git ADMIN
# directory, resolved via `git rev-parse --absolute-git-dir` (GIT_ADMIN_DIR) —
# not assumed to be $REPO_ROOT/.git. In a normal checkout that IS
# $REPO_ROOT/.git; in a linked worktree (`git worktree add`), $REPO_ROOT/.git
# is a FILE ("gitdir: /path/to/main/.git/worktrees/<name>"), and the real
# admin dir lives at that other path — redirecting straight at
# $REPO_ROOT/.git/songmaker-autodeploy.lock would fail before the first log
# line and kill the shell every tick. There is deliberately no separate
# systemd StateDirectory: that would be a second location, so a manual shell
# run outside systemd and the unit's own tick would silently diverge onto
# two different "deployed.sha"/failure histories instead of sharing one. The
# resolved admin dir is the one thing every caller (systemd unit, manual
# invocation, a second worktree pointed at a different checkout) already
# agrees on for a given checkout, and it survives reboots exactly like the
# rest of the repo. The SONGMAKER_AUTODEPLOY_* env vars remain the explicit
# override for tests and unusual setups.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

LOG_TAG="songmaker-autodeploy"
LOG_PAYLOAD_MAX_CHARS=2000
DEPLOY_BRANCH="${SONGMAKER_AUTODEPLOY_BRANCH:-main}"
PRUNE_RETENTION_HOURS=48
PRUNE_TIMEOUT_SECONDS="${SONGMAKER_AUTODEPLOY_PRUNE_TIMEOUT_SECONDS:-600}"
PREVIOUS_IMAGE_TAG="previous"
PROMETHEUS_RULE_FILE="monitoring/alert.rules.yml"
PROMETHEUS_URL="http://127.0.0.1:9090"
PROMETHEUS_RELOAD_URL="${PROMETHEUS_URL}/-/reload"
PROMETHEUS_RULES_URL="${PROMETHEUS_URL}/api/v1/rules"
PROMETHEUS_HTTP_TIMEOUT_SECONDS=30

log() {
    local level="$1"
    shift
    local message="$*"
    local original_length=${#message}
    if ((original_length > LOG_PAYLOAD_MAX_CHARS)); then
        message="${message:0:$LOG_PAYLOAD_MAX_CHARS}... (truncated from $original_length chars)"
    fi
    logger -t "$LOG_TAG" -p "user.$level" -- "$message"
}
log_debug() { log debug "$*"; }
log_info() { log info "$*"; }
log_warning() { log warning "$*"; }
log_err() { log err "$*"; }

# Every Git command in this tick goes through this narrow runner. The deploy
# checkout is a privileged execution boundary: repository hooks and an
# fsmonitor configured in its admin directory must not run from the timer.
# Keep the environment equally narrow, following requirement_binder.py's
# trusted-Git pattern, rather than inheriting arbitrary Git configuration from
# the service or its caller.
GIT_BINARY="/usr/bin/git"
GIT_PATH="/usr/bin:/bin"
safe_git() {
    env -i \
        PATH="$GIT_PATH" \
        LANG="C.UTF-8" \
        LC_ALL="C.UTF-8" \
        GIT_CONFIG_NOSYSTEM="1" \
        GIT_CONFIG_GLOBAL="/dev/null" \
        GIT_NO_LAZY_FETCH="1" \
        GIT_NO_REPLACE_OBJECTS="1" \
        GIT_TERMINAL_PROMPT="0" \
        GIT_OPTIONAL_LOCKS="0" \
        "$GIT_BINARY" \
        -c core.hooksPath=/dev/null \
        -c core.fsmonitor=false \
        -C "$REPO_ROOT" "$@"
}

# Resolve the real git ADMIN directory instead of assuming $REPO_ROOT/.git
# is one (see the LOCK_FILE/state-file comment above) — must run after log()
# is defined, since a failure here has to log_err before it exits.
if ! GIT_ADMIN_DIR="$(safe_git rev-parse --absolute-git-dir 2>&1)"; then
    log_err "cannot resolve the git admin directory for $REPO_ROOT: $GIT_ADMIN_DIR"
    exit 1
fi
STATE_DIR_FALLBACK="$GIT_ADMIN_DIR"
LOCK_FILE="${SONGMAKER_AUTODEPLOY_LOCK_FILE:-$STATE_DIR_FALLBACK/songmaker-autodeploy.lock}"
FAILURE_COUNT_FILE="${SONGMAKER_AUTODEPLOY_FAILURE_COUNT_FILE:-$STATE_DIR_FALLBACK/songmaker-autodeploy.failcount}"
BUSY_COUNT_FILE="${SONGMAKER_AUTODEPLOY_BUSY_COUNT_FILE:-$STATE_DIR_FALLBACK/songmaker-autodeploy.busycount}"
DEPLOYED_SHA_FILE="${SONGMAKER_AUTODEPLOY_DEPLOYED_SHA_FILE:-$STATE_DIR_FALLBACK/songmaker-autodeploy.deployed-sha}"
FAILURE_ESCALATED_AT_FILE="${SONGMAKER_AUTODEPLOY_FAILURE_ESCALATED_AT_FILE:-$STATE_DIR_FALLBACK/songmaker-autodeploy.failure-escalated-at}"
BUSY_ESCALATED_AT_FILE="${SONGMAKER_AUTODEPLOY_BUSY_ESCALATED_AT_FILE:-$STATE_DIR_FALLBACK/songmaker-autodeploy.busy-escalated-at}"
GUARD_REASON_FILE="${SONGMAKER_AUTODEPLOY_GUARD_REASON_FILE:-$STATE_DIR_FALLBACK/songmaker-autodeploy.guard-reason}"
FAILURE_ALERT_THRESHOLD="${SONGMAKER_AUTODEPLOY_FAILURE_ALERT_THRESHOLD:-3}"
BUSY_ALERT_THRESHOLD="${SONGMAKER_AUTODEPLOY_BUSY_ALERT_THRESHOLD:-30}"
# Wall-clock time between one escalation of an unbroken streak and the
# next — 1h, deliberately the same cadence Alertmanager's repeat_interval
# gives the other half of this one alert channel
# (monitoring/alertmanager.yml.template). See escalation_due.
ALERT_REPEAT_SECONDS="${SONGMAKER_AUTODEPLOY_ALERT_REPEAT_SECONDS:-3600}"
# A zero or garbage value here would make every escalation arithmetic
# silently fail, i.e. turn the alarm off — the one failure mode this whole
# issue exists to prevent.
if ! [[ "$ALERT_REPEAT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
    log_err "SONGMAKER_AUTODEPLOY_ALERT_REPEAT_SECONDS must be a positive integer, got '$ALERT_REPEAT_SECONDS'"
    exit 1
fi
DB_CHECK_TIMEOUT_SECONDS="${SONGMAKER_AUTODEPLOY_DB_CHECK_TIMEOUT_SECONDS:-30}"
CHECK_RUN_LOOKUP_TIMEOUT_SECONDS="${SONGMAKER_AUTODEPLOY_CHECK_RUN_LOOKUP_TIMEOUT_SECONDS:-60}"
if ! [[ "$PRUNE_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
    log_err "SONGMAKER_AUTODEPLOY_PRUNE_TIMEOUT_SECONDS must be a positive integer, got '$PRUNE_TIMEOUT_SECONDS'"
    exit 1
fi
# GitHub normally creates the first check run shortly after a push. Do not
# treat that ordinary propagation delay as a failed deploy, but do surface a
# workflow that never starts instead of waiting forever on the same SHA.
CHECK_RUN_APPEARANCE_GRACE_SECONDS="${SONGMAKER_AUTODEPLOY_CHECK_RUN_APPEARANCE_GRACE_SECONDS:-1800}"
if ! [[ "$CHECK_RUN_LOOKUP_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
    log_err "SONGMAKER_AUTODEPLOY_CHECK_RUN_LOOKUP_TIMEOUT_SECONDS must be a positive integer, got '$CHECK_RUN_LOOKUP_TIMEOUT_SECONDS'"
    exit 1
fi
if ! [[ "$CHECK_RUN_APPEARANCE_GRACE_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
    log_err "SONGMAKER_AUTODEPLOY_CHECK_RUN_APPEARANCE_GRACE_SECONDS must be a positive integer, got '$CHECK_RUN_APPEARANCE_GRACE_SECONDS'"
    exit 1
fi
# Bounds the container-readiness wait of step 10 only; the image build in
# step 9 stays deliberately unbounded, because a cold-cache build takes
# 8-15 minutes by design. Without a bound, one service that can never
# become healthy (issue #333's own alertmanager, if .env lacks the SMTP
# values) makes `compose up --wait` wait forever — and since the tick holds
# the flock the whole time, every later tick skips and nothing is ever
# alerted. The default is generous enough for a cold ACE-Step model load
# (ACESTEP_STARTUP_TIMEOUT_SECONDS, 900s) to still converge: this guards
# against "never", not against "slow".
COMPOSE_UP_WAIT_TIMEOUT_SECONDS="${SONGMAKER_AUTODEPLOY_COMPOSE_UP_WAIT_TIMEOUT_SECONDS:-1200}"
POSTGRES_USER="${POSTGRES_USER:-songmaker}"
POSTGRES_DB="${POSTGRES_DB:-songmaker}"

compose() {
    (cd "$REPO_ROOT" && docker compose "$@")
}

preserve_running_images() {
    command -v jq >/dev/null || {
        log_err "jq is required for the pre-recreate rollback tagging but is not installed"
        return 1
    }

    local compose_config
    local compose_stderr_file
    local compose_error
    local compose_exit_code
    local project_name
    local build_services
    local service
    local containers
    local container
    local service_image
    local current_image

    if ! compose_stderr_file="$(mktemp "$GIT_ADMIN_DIR/songmaker-autodeploy.compose-stderr.XXXXXX" 2>/dev/null)"; then
        log_err "cannot create temporary file for Compose config stderr before recreate"
        return 1
    fi

    if compose_config="$(compose config --format json --no-interpolate 2>"$compose_stderr_file")"; then
        rm -f "$compose_stderr_file"
    else
        compose_exit_code=$?
        compose_error="$(<"$compose_stderr_file")"
        rm -f "$compose_stderr_file"
        log_err "cannot read Compose config before recreate (exit $compose_exit_code): $compose_error"
        return 1
    fi

    if ! project_name="$(jq -er '.name | if type == "string" then . else error("missing Compose project name") end' <<<"$compose_config")"; then
        log_err "cannot read the Compose project name before recreate"
        return 1
    fi
    if ! [[ "$project_name" =~ ^[A-Za-z0-9._-]+$ ]]; then
        log_err "Compose project name '$project_name' contains unsupported characters"
        return 1
    fi

    if ! build_services="$(jq -r 'if (.services | type) == "object" then [.services | to_entries[] | select((.value | type) == "object" and (.value.build != null)) | .key][]? else error("missing Compose services") end' <<<"$compose_config")"; then
        log_err "cannot identify build services from Compose config before recreate"
        return 1
    fi
    [[ -n "$build_services" ]] || return 0

    while IFS= read -r service; do
        if ! [[ "$service" =~ ^[A-Za-z0-9._-]+$ ]]; then
            log_err "Compose build service '$service' contains unsupported characters"
            return 1
        fi

        if ! compose_stderr_file="$(mktemp "$GIT_ADMIN_DIR/songmaker-autodeploy.compose-stderr.XXXXXX" 2>/dev/null)"; then
            log_err "cannot create temporary file for Compose ps stderr before recreate"
            return 1
        fi

        if containers="$(compose ps -q --status running "$service" 2>"$compose_stderr_file")"; then
            rm -f "$compose_stderr_file"
        else
            compose_exit_code=$?
            compose_error="$(<"$compose_stderr_file")"
            rm -f "$compose_stderr_file"
            log_err "cannot find the running container for $service before recreate (exit $compose_exit_code): $compose_error"
            return 1
        fi
        [[ -n "$containers" ]] || continue

        service_image=""
        while IFS= read -r container; do
            if ! [[ "$container" =~ ^[A-Za-z0-9._-]+$ ]]; then
                log_err "Compose container ID '$container' for $service contains unsupported characters"
                return 1
            fi
            if ! current_image="$(docker inspect --format '{{.Image}}' "$container" 2>&1)"; then
                log_err "cannot inspect the running image for $service before recreate: $current_image"
                return 1
            fi
            if [[ -n "$service_image" && "$service_image" != "$current_image" ]]; then
                log_err "running containers for $service use different images; refusing to replace its single previous image tag"
                return 1
            fi
            service_image="$current_image"
        done <<<"$containers"

        if ! docker tag "$service_image" "${project_name}-${service}:${PREVIOUS_IMAGE_TAG}"; then
            log_err "cannot preserve the running image for $service before recreate"
            return 1
        fi
    done <<<"$build_services"
}

prune_docker_resources() {
    local prune_filter="until=${PRUNE_RETENTION_HOURS}h"
    local prune_failed=false
    local prune_exit_code

    if timeout "$PRUNE_TIMEOUT_SECONDS" docker image prune --force --filter "$prune_filter"; then
        :
    else
        prune_exit_code=$?
        log_err "docker image prune --force --filter $prune_filter failed after deploy (exit $prune_exit_code); deploy remains successful"
        prune_failed=true
    fi

    if timeout "$PRUNE_TIMEOUT_SECONDS" docker builder prune --all --force --filter "$prune_filter"; then
        :
    else
        prune_exit_code=$?
        log_err "docker builder prune --all --force --filter $prune_filter failed after deploy (exit $prune_exit_code); deploy remains successful"
        prune_failed=true
    fi

    if [[ "$prune_failed" == false ]]; then
        log_info "pruned unreferenced Docker images and build cache older than ${PRUNE_RETENTION_HOURS}h"
    fi

    return 0
}

reload_prometheus_rules() {
    local previous_deployed_sha="$1"
    local deployed_sha="$2"
    local changed_files
    local configured_rule_count
    local loaded_rule_count
    local rules_response

    if ! changed_files="$(safe_git diff --name-only "$previous_deployed_sha" "$deployed_sha" -- "$PROMETHEUS_RULE_FILE" 2>&1)"; then
        log_err "cannot determine whether $PROMETHEUS_RULE_FILE changed after deploy: $changed_files; deploy remains successful"
        return 0
    fi
    [[ "$changed_files" == "$PROMETHEUS_RULE_FILE" ]] || return 0

    if ! curl --fail --silent --show-error --max-time "$PROMETHEUS_HTTP_TIMEOUT_SECONDS" -X POST "$PROMETHEUS_RELOAD_URL"; then
        log_err "Prometheus rule reload failed after deploy; deploy remains successful"
        return 0
    fi
    if ! rules_response="$(curl --fail --silent --show-error --max-time "$PROMETHEUS_HTTP_TIMEOUT_SECONDS" "$PROMETHEUS_RULES_URL")"; then
        log_err "cannot read Prometheus rules after reload; deploy remains successful"
        return 0
    fi
    if ! loaded_rule_count="$(jq -er '[.data.groups[]?.rules[]? | select(.type == "alerting")] | length' <<<"$rules_response")"; then
        log_err "cannot count loaded Prometheus alert rules after reload; deploy remains successful"
        return 0
    fi
    if ! configured_rule_count="$(grep -c 'alert:' "$REPO_ROOT/$PROMETHEUS_RULE_FILE" || true)" || ! [[ "$configured_rule_count" =~ ^[0-9]+$ ]]; then
        log_err "cannot count configured Prometheus alert rules after reload; deploy remains successful"
        return 0
    fi
    if [[ "$loaded_rule_count" != "$configured_rule_count" ]]; then
        log_err "Prometheus alert rule count mismatch after reload: configured $configured_rule_count, loaded $loaded_rule_count; deploy remains successful"
    fi
}

# --- Active-jobs guard, called once before the pull and once again right
# before the container recreate (see the header). Bounded by a short
# `timeout` — a wedged DB connection must not hang a tick, unlike the image
# build below, which is allowed to run as long as it needs.
active_job_count() {
    local output
    if ! output="$(cd "$REPO_ROOT" && timeout "$DB_CHECK_TIMEOUT_SECONDS" docker compose exec -T postgres psql \
        -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
        "SELECT count(*) FROM jobs WHERE status IN ('queued', 'running')" 2>&1)"; then
        printf '%s' "$output"
        return 1
    fi
    local count
    count="$(printf '%s' "$output" | tr -d '[:space:]')"
    if ! [[ "$count" =~ ^[0-9]+$ ]]; then
        printf '%s' "$output"
        return 1
    fi
    printf '%s' "$count"
}

# Shared reader for every whole-number state file this script keeps: the
# two consecutive-tick counters and the two escalation timestamps. A
# missing file reads 0, which is what both kinds want — no streak yet, and
# no escalation yet. Guards `cat` itself against set -e (an unreadable
# file, e.g. a permissions problem, must be treated like a corrupt one — 0
# plus a loud line — rather than killing the tick before it can even
# record anything).
read_number() {
    local file="$1"
    if [[ ! -f "$file" ]]; then
        printf '0'
        return
    fi
    local value
    if ! value="$(cat "$file" 2>&1)"; then
        log_err "cannot read state file $file ($value) — treating as corrupt, using 0"
        printf '0' >"$file"
        printf '0'
        return
    fi
    if ! [[ "$value" =~ ^[0-9]+$ ]]; then
        log_err "state file $file has corrupt content ('$value') — resetting to 0"
        printf '0' >"$file"
        printf '0'
        return
    fi
    printf '%s' "$value"
}

reset_counters() {
    printf '0' >"$FAILURE_COUNT_FILE"
    printf '0' >"$BUSY_COUNT_FILE"
    # The escalation timestamps belong to the streak that is now over. A
    # new streak has to be able to escalate on the tick that crosses its
    # threshold, even if that is minutes after the previous streak's last
    # escalation — otherwise a recovery followed by a fresh outage would
    # stay silent for the rest of the repeat window.
    rm -f "$FAILURE_ESCALATED_AT_FILE" "$BUSY_ESCALATED_AT_FILE"
    # The counters hitting 0 means the guard streak is over too — an
    # up-to-date shortcut or a first-run adoption both reset the counters
    # without ever reaching the branch check that would otherwise clear
    # this file (see step 4 below), so it has to be cleared here as well or
    # a stale reason from a previous episode could suppress the err line on
    # a genuinely new one.
    rm -f "$GUARD_REASON_FILE"
}

# Writes $DEPLOYED_SHA_FILE and reads it straight back before declaring
# success — the reader elsewhere in this script rejects anything that isn't
# a clean 40-char hex SHA (see step 3), so a write that silently didn't take
# (full disk, permissions, a stale bind mount) would otherwise look like
# nothing was ever deployed and every following tick would redeploy the
# same commit forever with no ALERT. A mismatch counts as a failed tick, not
# a successful one.
record_success() {
    local deployed_sha="$1"
    printf '%s' "$deployed_sha" >"$DEPLOYED_SHA_FILE"
    local written_sha
    if ! written_sha="$(cat "$DEPLOYED_SHA_FILE" 2>&1)" || [[ "$written_sha" != "$deployed_sha" ]]; then
        log_err "deployed-sha file $DEPLOYED_SHA_FILE reads back as '$written_sha' after writing '$deployed_sha' — treating this deploy as failed, not successful"
        # This path pages immediately either way (the caller exits 1), so
        # only record_failure's counting matters here, not its answer to
        # "did this tick escalate".
        record_failure "deployed-sha readback mismatch" || true
        return 1
    fi
    reset_counters
    log_info "deploy succeeded, now running $deployed_sha"
}

# What the clock reads. Its own function because the tests replace it —
# a repetition promised in hours cannot be proven by a test that waits
# hours.
now_seconds() {
    date +%s
}

# The escalation rule both counters below share: escalate on the tick that
# CROSSES the threshold, then at most once per ALERT_REPEAT_SECONDS for as
# long as the streak lasts, recording in $timestamp_file when it did.
# Escalating on every tick past the threshold would mail the operator
# every two minutes through `OnFailure=` (issue #333) and bury the
# journal; escalating only on the crossing tick would let a permanent
# outage go quiet after a single missed message, which is the worse of the
# two failures. Every tick is still counted and still logged at debug, so
# the record of what happened is complete either way.
#
# The repetition is measured in TIME, not in ticks. A systemd timer starts
# no second run while the previous one is still going, so a tick is not a
# fixed two minutes: one that waits out COMPOSE_UP_WAIT_TIMEOUT_SECONDS
# occupies twenty. Counting ticks turned "again in an hour" into "again in
# ten hours" on exactly the slow, broken ticks this alarm exists for.
# The THRESHOLD stays a tick count on
# purpose: "three attempts in a row failed" is what separates a transient
# blip (a migration lock_timeout the next tick retries) from an outage,
# and elapsed time cannot tell those two apart.
#
# Called at most once per tick per counter — it writes the timestamp it
# reads.
escalation_due() {
    local count="$1"
    local threshold="$2"
    local timestamp_file="$3"
    ((count >= threshold)) || return 1
    local now last_escalation
    now="$(now_seconds)"
    last_escalation="$(read_number "$timestamp_file")"
    ((now - last_escalation >= ALERT_REPEAT_SECONDS)) || return 1
    printf '%s' "$now" >"$timestamp_file"
}

# A tick that could not deploy at all despite $DEPLOY_BRANCH having moved —
# a hard refusal (wrong branch, dirty tree, diverged), a fail-closed DB
# check, or a pull/build/up failure. This is the "something is actually
# broken" signal: N of these in a row (default 3) pages.
#
# Returns success on exactly the ticks that escalated, so fail_tick below
# fails the systemd unit — and therefore sends the email — on those and
# only those, without asking escalation_due a second question it would
# answer differently (it records the time it escalated).
record_failure() {
    local reason="$1"
    local count
    count="$(read_number "$FAILURE_COUNT_FILE")"
    count=$((count + 1))
    printf '%s' "$count" >"$FAILURE_COUNT_FILE"
    log_debug "failure count now $count (this tick: $reason)"
    escalation_due "$count" "$FAILURE_ALERT_THRESHOLD" "$FAILURE_ESCALATED_AT_FILE" || return 1
    log_err "ALERT: $count ticks in a row deferred/failed, reason: $reason — auto-deploy is stuck, needs human attention"
}

# Every guard/infra refusal below calls this instead of a bare `exit 1` —
# it records the tick via record_failure() exactly as before, and fails the
# systemd unit (exit 1) on exactly the ticks that also log the "ALERT: N
# ticks in a row" line above: the tick that crosses
# FAILURE_ALERT_THRESHOLD, and then the first tick at least
# ALERT_REPEAT_SECONDS later while the streak holds. Every other tick in a
# streak exits 0 despite having deferred.
#
# This is what makes `OnFailure=songmaker-alert@%n.service` (issue #333)
# safe to attach to this unit: without it, the branch guard alone would
# fire that unit-failure — and the alert email — on essentially every
# 2-minute tick for as long as the operator works on a branch other than
# $DEPLOY_BRANCH in this checkout (see step 4's own comment), which is a
# routine, not an emergency, state.
fail_tick() {
    local reason="$1"
    if record_failure "$reason"; then
        exit 1
    fi
    exit 0
}

# A tick deferred only because jobs are active (before or after the build).
# This is expected behavior under a busy queue or a long-running
# lora_training job, not a fault — it gets its own, much higher threshold
# (default 30 ticks) and a quieter prio=warning line instead of err.
record_busy_deferral() {
    local active_job_count="$1"
    local count
    count="$(read_number "$BUSY_COUNT_FILE")"
    count=$((count + 1))
    printf '%s' "$count" >"$BUSY_COUNT_FILE"
    log_debug "busy-deferral count now $count ($active_job_count jobs active)"
    if escalation_due "$count" "$BUSY_ALERT_THRESHOLD" "$BUSY_ESCALATED_AT_FILE"; then
        log_warning "deploy deferred on $count ticks in a row, $active_job_count jobs still active"
    fi
}

# Dedup for the branch guard's err line only (step 4 below). An operator who
# stays on a work branch has step 3's up-to-date shortcut fail on
# essentially every tick — their HEAD is essentially never ==
# origin/$DEPLOY_BRANCH while they are away from it — so without this, the
# branch guard would log the identical prio=err line every ~2 minutes for
# hours. Only a CHANGED reason (a different branch, or detached vs named)
# re-earns an err line; the same reason repeating logs at debug instead.
# record_failure still counts every tick regardless of which level this
# logs at, so the ALERT threshold is unaffected.
log_guard_reason() {
    local reason="$1"
    local previous_reason=""
    if [[ -f "$GUARD_REASON_FILE" ]]; then
        previous_reason="$(cat "$GUARD_REASON_FILE" 2>/dev/null || true)"
    fi
    if [[ "$reason" == "$previous_reason" ]]; then
        log_debug "$reason (unchanged since last tick, not repeating at err)"
    else
        log_err "$reason"
        printf '%s' "$reason" >"$GUARD_REASON_FILE"
    fi
}

# Prints exactly one of green, waiting, or failed. An API/CLI failure is a
# named error return because it is not evidence that the fetched commit is
# safe to deploy. The API's explicit zero-run envelope waits only until the
# commit is old enough that a workflow which never started needs attention.
# A missing/malformed envelope is never mistaken for zero runs.
remote_check_status() {
    local commit_sha="$1"
    local commit_timestamp="$2"
    local check_runs gh_error gh_stderr_file lookup_exit
    if ! command -v gh >/dev/null 2>&1; then
        printf '%s' "GitHub CLI (gh) is unavailable on PATH"
        return 1
    fi
    if ! gh_stderr_file="$(mktemp "$GIT_ADMIN_DIR/songmaker-autodeploy.gh-stderr.XXXXXX" 2>/dev/null)"; then
        printf '%s' 'cannot create temporary file for check-run lookup stderr'
        return 1
    fi
    if check_runs="$(timeout "$CHECK_RUN_LOOKUP_TIMEOUT_SECONDS" gh api --paginate \
        "repos/FlexOr2/songmaker/commits/$commit_sha/check-runs?per_page=100" \
        --jq 'if (type == "object" and (.total_count | type == "number") and (.check_runs | type == "array")) then "envelope\t\(.total_count)", (.check_runs[] | "check\t\(.status // "")\t\(.conclusion // "")") else error("GitHub returned malformed check-runs response") end' 2>"$gh_stderr_file")"; then
        rm -f "$gh_stderr_file"
    else
        lookup_exit=$?
        gh_error="$(<"$gh_stderr_file")"
        rm -f "$gh_stderr_file"
        if ((lookup_exit == 124)); then
            printf '%s' 'check-run lookup timed out'
        else
            printf '%s' "$gh_error"
        fi
        return 1
    fi

    local record status conclusion
    local expected_check_count=""
    local observed_check_count=0
    local has_envelope=false
    local has_running_check=false
    local has_failed_check=false
    while IFS=$'\t' read -r record status conclusion; do
        case "$record" in
            envelope)
                if [[ ! "$status" =~ ^[0-9]+$ || -n "$conclusion" ]]; then
                    printf 'GitHub returned a malformed check-runs envelope'
                    return 1
                fi
                if [[ -n "$expected_check_count" && "$expected_check_count" != "$status" ]]; then
                    printf 'GitHub returned inconsistent paginated check-run counts'
                    return 1
                fi
                expected_check_count="$status"
                has_envelope=true
                ;;
            check)
                ((observed_check_count += 1))
                if [[ -z "$status" ]]; then
                    printf 'GitHub returned an incomplete check-run status'
                    return 1
                fi
                case "$status" in
                    queued|in_progress|pending|requested|waiting)
                        has_running_check=true
                        ;;
                    completed)
                        if [[ -z "$conclusion" ]]; then
                            printf 'GitHub returned an incomplete check-run status'
                            return 1
                        fi
                        if [[ "$conclusion" != "success" ]]; then
                            has_failed_check=true
                        fi
                        ;;
                    *)
                        printf 'GitHub returned an unknown check-run status'
                        return 1
                        ;;
                esac
                ;;
            *)
                printf 'GitHub returned a malformed check-runs response'
                return 1
                ;;
        esac
    done <<<"$check_runs"

    if [[ "$has_envelope" != true || "$observed_check_count" != "$expected_check_count" ]]; then
        printf 'GitHub returned an incomplete check-runs response'
        return 1
    fi
    if ((observed_check_count == 0)); then
        local now
        if ! now="$(now_seconds)" || ! [[ "$now" =~ ^[0-9]+$ ]]; then
            printf 'cannot determine current time for check-run grace period'
            return 1
        fi
        if ((now - commit_timestamp >= CHECK_RUN_APPEARANCE_GRACE_SECONDS)); then
            printf 'failed (GitHub has not reported a check run within %ss of its commit)' "$CHECK_RUN_APPEARANCE_GRACE_SECONDS"
        else
            printf 'waiting (GitHub has not reported a check run yet)'
        fi
        return
    fi

    # A run that GitHub still considers active means this SHA is not green
    # yet, even if another completed run has already failed. Waiting avoids
    # escalating while CI is still producing its final verdict.
    if [[ "$has_running_check" == true ]]; then
        printf 'waiting (one or more GitHub check runs are still running)'
    elif [[ "$has_failed_check" == true ]]; then
        printf 'failed (one or more GitHub check runs did not succeed)'
    else
        printf 'green'
    fi
}

# --- 1. Refuse to overlap with another run in flight (a slow cold-cache
# build can outlive one 2-minute tick). Busy is the expected steady state
# under a running build, not an error — logged at debug so an unfiltered
# journal still shows it, but no info/err noise.
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    log_debug "another run is already in flight, skipping this tick"
    exit 0
fi

# --- 2. Cheap reads: local HEAD, then fetch, then remote HEAD. Neither
# depends on which branch is currently checked out (rev-parse HEAD works
# detached too), so these run before the branch guard. A persistently
# broken `git fetch` (e.g. a dead SSH key on the host) is the single most
# likely way this whole mechanism goes silently stale, so all three record a
# failure tick like every other refusal below, instead of only logging and
# exiting — without this a stuck fetch would never reach the consecutive-
# failure ALERT.
if ! LOCAL_HEAD="$(safe_git rev-parse HEAD 2>&1)"; then
    log_err "cannot determine local HEAD in $REPO_ROOT: $LOCAL_HEAD"
    fail_tick "cannot determine local HEAD"
fi

if ! FETCH_OUTPUT="$(safe_git fetch origin "$DEPLOY_BRANCH" --quiet 2>&1)"; then
    log_err "git fetch origin $DEPLOY_BRANCH failed in $REPO_ROOT: $FETCH_OUTPUT"
    fail_tick "git fetch failed"
fi

if ! REMOTE_HEAD="$(safe_git rev-parse "origin/$DEPLOY_BRANCH" 2>&1)"; then
    log_err "cannot resolve origin/$DEPLOY_BRANCH in $REPO_ROOT: $REMOTE_HEAD"
    fail_tick "cannot resolve origin/$DEPLOY_BRANCH"
fi

# --- 3. Up-to-date shortcut — the common case, and must stay silent. Judged
# against what is actually RUNNING ($DEPLOYED_SHA_FILE, written only by
# record_success), not just what is checked out: a tick that pulled/built
# but deferred the recreate already sits on the new HEAD, so "local ==
# remote" alone would call that "nothing to deploy" forever. Runs before the
# branch guard: an operator sitting on an unrelated branch with nothing
# pending to deploy must not get a loud line every ~2 minutes.
if [[ ! -f "$DEPLOYED_SHA_FILE" ]]; then
    printf '%s' "$LOCAL_HEAD" >"$DEPLOYED_SHA_FILE"
    reset_counters
    log_info "adopted running state $LOCAL_HEAD (no prior $DEPLOYED_SHA_FILE — first run after install; if the live stack is not actually running this commit, deploy manually once)"
    exit 0
fi

if ! DEPLOYED_SHA="$(cat "$DEPLOYED_SHA_FILE" 2>&1)"; then
    log_err "cannot read $DEPLOYED_SHA_FILE ($DEPLOYED_SHA) — treating deploy state as unknown, will re-verify by deploying"
    DEPLOYED_SHA=""
elif ! [[ "$DEPLOYED_SHA" =~ ^[0-9a-f]{40}$ ]]; then
    log_err "deployed-sha file $DEPLOYED_SHA_FILE has unexpected content ('$DEPLOYED_SHA') — treating deploy state as unknown, will re-verify by deploying"
    DEPLOYED_SHA=""
fi

if [[ "$LOCAL_HEAD" == "$REMOTE_HEAD" && "$DEPLOYED_SHA" == "$LOCAL_HEAD" ]]; then
    reset_counters
    log_debug "already at origin/$DEPLOY_BRANCH ($LOCAL_HEAD) and deployed — nothing to deploy"
    exit 0
fi

# --- 4. On the deploy branch? Reached only once step 3 has established that
# something is actually pending — but on a work branch that is essentially
# every tick: HEAD there is essentially never == origin/$DEPLOY_BRANCH, so
# this guard fires continuously for as long as the operator stays away from
# it, not as some rare edge case. A detached HEAD or a non-deploy branch
# therefore only re-logs at prio=err when the reason actually changes
# (log_guard_reason); record_failure still counts every tick regardless, so
# the ALERT threshold is unaffected by the log-level damping.
if ! CURRENT_BRANCH="$(safe_git symbolic-ref --quiet --short HEAD 2>&1)"; then
    log_guard_reason "HEAD at $REPO_ROOT is not on a branch (detached?) — refusing to deploy, not touching the tree: $CURRENT_BRANCH"
    fail_tick "HEAD not on a branch"
fi

if [[ "$CURRENT_BRANCH" != "$DEPLOY_BRANCH" ]]; then
    log_guard_reason "HEAD at $REPO_ROOT is on branch '$CURRENT_BRANCH', not the deploy branch '$DEPLOY_BRANCH' — refusing to deploy, not touching the tree"
    fail_tick "HEAD on branch $CURRENT_BRANCH instead of $DEPLOY_BRANCH"
fi

# Branch guard passed — clear any stale reason so a future recurrence (after
# a branch change or a successful deploy in between) logs at err again
# instead of being suppressed by a reason left over from before.
rm -f "$GUARD_REASON_FILE"

# --- 5. Safe to touch? A dirty working tree or a diverged (non-fast-
# forwardable) local main stops here — the host's checkout is also the
# operator's manual workspace.
if ! STATUS_OUTPUT="$(safe_git status --porcelain 2>&1)"; then
    log_err "cannot determine working tree status in $REPO_ROOT: $STATUS_OUTPUT"
    fail_tick "git status failed"
fi

if [[ -n "$STATUS_OUTPUT" ]]; then
    log_err "working tree at $REPO_ROOT is dirty — refusing to deploy, not touching it (the operator may be working here)"
    fail_tick "working tree dirty"
fi

if ! safe_git merge-base --is-ancestor "$LOCAL_HEAD" "$REMOTE_HEAD"; then
    log_err "local HEAD ($LOCAL_HEAD) has diverged from origin/$DEPLOY_BRANCH ($REMOTE_HEAD) — not fast-forwardable, refusing to deploy, not touching the tree"
    fail_tick "local HEAD diverged from origin/$DEPLOY_BRANCH"
fi

# --- 6. Job guard, ahead of the first step that touches the checkout. An
# unreachable DB fails closed: unknown job state is treated as "do not
# deploy", not as "assume idle".
if ! ACTIVE_JOB_COUNT="$(active_job_count)"; then
    log_err "cannot reach the database to check for active jobs — refusing to deploy (fail closed): $ACTIVE_JOB_COUNT"
    fail_tick "database unreachable before pull"
fi

if [[ "$ACTIVE_JOB_COUNT" -gt 0 ]]; then
    log_info "deploy deferred, $ACTIVE_JOB_COUNT jobs active"
    record_busy_deferral "$ACTIVE_JOB_COUNT"
    exit 0
fi

# --- 7. Alert-channel guard.
# The stack's alertmanager refuses to start without the five .env values
# (issue #333), so a checkout that reaches this commit without them cannot
# be deployed at all — `compose up --wait` would only discover that after
# the whole build, minutes later, from an "unhealthy container" message
# that names no cause. Refusing here instead names the missing keys on the
# very first tick. The same helper scripts/alert.sh uses owns the list, so
# there is one answer to "what configures the alert channel".
if ! ALERT_CONFIG_ERROR="$( (
    # shellcheck source=scripts/alert-config.sh
    source "$SCRIPT_DIR/alert-config.sh"
    load_alert_config "$REPO_ROOT/.env"
) 2>&1 )"; then
    log_err "alert channel not configured — refusing to deploy a stack whose alertmanager cannot start: $ALERT_CONFIG_ERROR"
    fail_tick "alert channel not configured"
fi

# --- 8. Agent-CLI mount preflight, the last check before anything is
# changed. When the verifier from issue #350 is present, make its named
# failure a regular deploy refusal before a pull or an expensive image build.
# Until that change lands, absence is explicit rather than a silent fallback:
# this tick names the missing preflight and continues with the guards already
# available in this checkout.
MOUNT_PREFLIGHT_SCRIPT="$SCRIPT_DIR/check_agent_cli_mounts.sh"
if [[ ! -e "$MOUNT_PREFLIGHT_SCRIPT" && ! -L "$MOUNT_PREFLIGHT_SCRIPT" ]]; then
    log_info "mount preflight not installed, skipping"
elif ! MOUNT_PREFLIGHT_ERROR="$(bash "$MOUNT_PREFLIGHT_SCRIPT" 2>&1)"; then
    log_err "agent CLI mount preflight failed — refusing to deploy: $MOUNT_PREFLIGHT_ERROR"
    fail_tick "agent CLI mount preflight failed"
fi

# --- 9. Only pull a commit whose checks are green. A check run that is
# still queued/in progress is an ordinary wait, not a deploy failure: the
# next timer tick will query the same fetched SHA again. A completed non-green
# run, an aged SHA with no runs, or inability to query GitHub at all, is a
# named fail-closed refusal.
if ! REMOTE_COMMIT_TIMESTAMP="$(safe_git show -s --format=%ct "$REMOTE_HEAD" 2>&1)"; then
    log_err "cannot determine commit time for verified origin/$DEPLOY_BRANCH commit $REMOTE_HEAD: $REMOTE_COMMIT_TIMESTAMP"
    fail_tick "cannot determine verified commit time"
fi
if ! [[ "$REMOTE_COMMIT_TIMESTAMP" =~ ^[0-9]+$ ]]; then
    log_err "verified origin/$DEPLOY_BRANCH commit $REMOTE_HEAD has an invalid commit time '$REMOTE_COMMIT_TIMESTAMP'"
    fail_tick "invalid verified commit time"
fi

if ! REMOTE_CHECK_STATUS="$(remote_check_status "$REMOTE_HEAD" "$REMOTE_COMMIT_TIMESTAMP")"; then
    log_err "cannot determine GitHub check status for origin/$DEPLOY_BRANCH ($REMOTE_HEAD) — refusing to deploy: $REMOTE_CHECK_STATUS"
    if [[ "$REMOTE_CHECK_STATUS" == "check-run lookup timed out" ]]; then
        fail_tick "check-run lookup timed out"
    fi
    fail_tick "GitHub check status undetermined"
fi

case "$REMOTE_CHECK_STATUS" in
    green)
        ;;
    waiting\ *)
        log_info "GitHub checks for origin/$DEPLOY_BRANCH ($REMOTE_HEAD) are not green yet: $REMOTE_CHECK_STATUS"
        exit 0
        ;;
    failed\ *)
        log_err "GitHub checks for origin/$DEPLOY_BRANCH ($REMOTE_HEAD) are not green — refusing to deploy: $REMOTE_CHECK_STATUS"
        if [[ "$REMOTE_CHECK_STATUS" == "failed (GitHub has not reported a check run within "* ]]; then
            fail_tick "no GitHub check runs reported within ${CHECK_RUN_APPEARANCE_GRACE_SECONDS}s of commit"
        fi
        fail_tick "GitHub checks are not green"
        ;;
    *)
        log_err "cannot determine GitHub check status for origin/$DEPLOY_BRANCH ($REMOTE_HEAD) — refusing to deploy: unexpected result '$REMOTE_CHECK_STATUS'"
        fail_tick "GitHub check status undetermined"
        ;;
esac

# --- 10. Fast-forward exactly the fetched-and-verified commit, then build.
# Do not use `git pull` here: it would fetch a second time and could move the
# checkout past $REMOTE_HEAD after its checks were accepted. No timeout around
# the build (CLAUDE.md) — a
# cold-cache rebuild legitimately takes 8-15 minutes. Building does not
# recreate any running container, so it cannot kill an in-flight job by
# itself — the recheck in step 11 is what guards the actual recreate. Both
# the fast-forward and `compose build` stream straight to this process's own
# stdout/stderr rather than being captured — a failed build's full output
# can easily exceed what a single logger argument can carry (see header) —
# only a short log_err line with the exit code goes through `logger`.
if ! MERGE_OUTPUT="$(safe_git merge --ff-only "$REMOTE_HEAD" 2>&1)"; then
    log_err "git merge --ff-only to verified origin/$DEPLOY_BRANCH ($REMOTE_HEAD) failed in $REPO_ROOT: $MERGE_OUTPUT"
    fail_tick "git fast-forward failed"
fi

if ! CHECKED_OUT_HEAD="$(safe_git rev-parse HEAD 2>&1)"; then
    log_err "cannot determine HEAD in $REPO_ROOT after fast-forward: $CHECKED_OUT_HEAD"
    fail_tick "cannot determine HEAD after fast-forward"
fi

if [[ "$CHECKED_OUT_HEAD" != "$REMOTE_HEAD" ]]; then
    log_err "HEAD in $REPO_ROOT is $CHECKED_OUT_HEAD after fast-forward, not the verified origin/$DEPLOY_BRANCH commit $REMOTE_HEAD — refusing to build"
    fail_tick "checked out commit differs from verified commit"
fi

if compose build; then
    :
else
    BUILD_EXIT_CODE=$?
    log_err "docker compose build failed in $REPO_ROOT (exit $BUILD_EXIT_CODE)"
    fail_tick "compose build failed"
fi

# --- 11. Recheck immediately before the recreate — the only step that can
# kill an in-flight job. This shrinks the unsafe window from the build's
# 8-15 minutes down to the seconds between this check and `compose up`. A
# deferral here finds the image already built on the next tick, so the
# recheck lands within seconds rather than after another full build.
if ! ACTIVE_JOB_COUNT="$(active_job_count)"; then
    log_err "cannot reach the database to recheck for active jobs after build — refusing to recreate containers (fail closed): $ACTIVE_JOB_COUNT"
    fail_tick "database unreachable after build"
fi

if [[ "$ACTIVE_JOB_COUNT" -gt 0 ]]; then
    log_info "deploy deferred after build, $ACTIVE_JOB_COUNT jobs active"
    record_busy_deferral "$ACTIVE_JOB_COUNT"
    exit 0
fi

# Resolved once, right before the recreate — not after `compose up`
# succeeds — so a broken `rev-parse` here fails the tick outright instead of
# leaving a just-recreated stack with no way to record what it is running.
if ! DEPLOYED_HEAD="$(safe_git rev-parse HEAD 2>&1)"; then
    log_err "cannot determine HEAD in $REPO_ROOT right before recreate: $DEPLOYED_HEAD"
    fail_tick "cannot determine HEAD before recreate"
fi

if ! preserve_running_images; then
    fail_tick "cannot preserve running images before recreate"
fi

if compose up -d --wait --wait-timeout "$COMPOSE_UP_WAIT_TIMEOUT_SECONDS"; then
    if record_success "$DEPLOYED_HEAD"; then
        reload_prometheus_rules "$DEPLOYED_SHA" "$DEPLOYED_HEAD"
        prune_docker_resources
        exit 0
    fi
    # record_success's own failure path (deployed-sha readback mismatch)
    # already called record_failure — but a deploy that succeeded and then
    # immediately corrupted its own bookkeeping is a different, rarer, and
    # more urgent kind of broken than a routine guard refusal, so this one
    # pages immediately (exit 1) rather than waiting for fail_tick's
    # threshold.
    exit 1
else
    UP_EXIT_CODE=$?
    log_err "docker compose up -d --wait failed or timed out after ${COMPOSE_UP_WAIT_TIMEOUT_SECONDS}s in $REPO_ROOT (exit $UP_EXIT_CODE)"
    fail_tick "compose up failed"
fi

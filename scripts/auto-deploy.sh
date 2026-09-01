#!/bin/bash
# Pull-based auto-deploy for Songmaker (issue #298).
#
# A GitOps timer, not a webhook or a self-hosted CI runner: this script polls
# origin/main every couple of minutes (see songmaker-autodeploy.timer) and
# fast-forwards + redeploys the local checkout when main has moved. CI is
# green on every merge to main by process, so "origin/main moved" already
# means "this is deployable" — the script itself does not re-run tests.
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
#     failure) increments a consecutive-FAILURE counter; only N in a row
#     escalates to a prio=err journal line worth paging on. A tick that
#     merely defers because jobs are active increments a separate
#     consecutive-BUSY counter with a much higher threshold and a quieter
#     prio=warning line — a normal generation queue or an hours-long
#     lora_training job legitimately keeps jobs active for a long time, and
#     that is not the same emergency as a deploy that keeps failing outright
#     (see record_failure / record_busy_deferral below). Both counters reset
#     only on an actual deploy or a genuine "nothing to deploy" tick.
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
# LOCK_FILE and all three state files (FAILURE_COUNT_FILE, BUSY_COUNT_FILE,
# DEPLOYED_SHA_FILE) live at a fixed path inside the git ADMIN directory,
# resolved via `git rev-parse --absolute-git-dir` (GIT_ADMIN_DIR below) —
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

# Resolve the real git ADMIN directory instead of assuming $REPO_ROOT/.git
# is one (see the LOCK_FILE/state-file comment above) — must run after log()
# is defined, since a failure here has to log_err before it exits.
if ! GIT_ADMIN_DIR="$(git -C "$REPO_ROOT" rev-parse --absolute-git-dir 2>&1)"; then
    log_err "cannot resolve the git admin directory for $REPO_ROOT: $GIT_ADMIN_DIR"
    exit 1
fi
STATE_DIR_FALLBACK="$GIT_ADMIN_DIR"
LOCK_FILE="${SONGMAKER_AUTODEPLOY_LOCK_FILE:-$STATE_DIR_FALLBACK/songmaker-autodeploy.lock}"
FAILURE_COUNT_FILE="${SONGMAKER_AUTODEPLOY_FAILURE_COUNT_FILE:-$STATE_DIR_FALLBACK/songmaker-autodeploy.failcount}"
BUSY_COUNT_FILE="${SONGMAKER_AUTODEPLOY_BUSY_COUNT_FILE:-$STATE_DIR_FALLBACK/songmaker-autodeploy.busycount}"
DEPLOYED_SHA_FILE="${SONGMAKER_AUTODEPLOY_DEPLOYED_SHA_FILE:-$STATE_DIR_FALLBACK/songmaker-autodeploy.deployed-sha}"
GUARD_REASON_FILE="${SONGMAKER_AUTODEPLOY_GUARD_REASON_FILE:-$STATE_DIR_FALLBACK/songmaker-autodeploy.guard-reason}"
FAILURE_ALERT_THRESHOLD="${SONGMAKER_AUTODEPLOY_FAILURE_ALERT_THRESHOLD:-3}"
BUSY_ALERT_THRESHOLD="${SONGMAKER_AUTODEPLOY_BUSY_ALERT_THRESHOLD:-30}"
DB_CHECK_TIMEOUT_SECONDS="${SONGMAKER_AUTODEPLOY_DB_CHECK_TIMEOUT_SECONDS:-30}"
POSTGRES_USER="${POSTGRES_USER:-songmaker}"
POSTGRES_DB="${POSTGRES_DB:-songmaker}"

compose() {
    (cd "$REPO_ROOT" && docker compose "$@")
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

# Shared reader for both consecutive-tick counters. Guards `cat` itself
# against set -e (an unreadable file, e.g. a permissions problem, must be
# treated like a corrupt one — 0 plus a loud line — rather than killing the
# tick before it can even record anything).
read_counter() {
    local file="$1"
    if [[ ! -f "$file" ]]; then
        printf '0'
        return
    fi
    local count
    if ! count="$(cat "$file" 2>&1)"; then
        log_err "cannot read counter file $file ($count) — treating as corrupt, using 0"
        printf '0' >"$file"
        printf '0'
        return
    fi
    if ! [[ "$count" =~ ^[0-9]+$ ]]; then
        log_err "counter file $file has corrupt content ('$count') — resetting to 0"
        printf '0' >"$file"
        printf '0'
        return
    fi
    printf '%s' "$count"
}

reset_counters() {
    printf '0' >"$FAILURE_COUNT_FILE"
    printf '0' >"$BUSY_COUNT_FILE"
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
        record_failure "deployed-sha readback mismatch"
        return 1
    fi
    reset_counters
    log_info "deploy succeeded, now running $deployed_sha"
}

# A tick that could not deploy at all despite $DEPLOY_BRANCH having moved —
# a hard refusal (wrong branch, dirty tree, diverged), a fail-closed DB
# check, or a pull/build/up failure. This is the "something is actually
# broken" signal: N of these in a row (default 3, ~6 minutes) pages.
record_failure() {
    local reason="$1"
    local count
    count="$(read_counter "$FAILURE_COUNT_FILE")"
    count=$((count + 1))
    printf '%s' "$count" >"$FAILURE_COUNT_FILE"
    log_debug "failure count now $count (this tick: $reason)"
    if [[ "$count" -ge "$FAILURE_ALERT_THRESHOLD" ]]; then
        log_err "ALERT: $count ticks in a row deferred/failed, reason: $reason — auto-deploy is stuck, needs human attention"
    fi
}

# A tick deferred only because jobs are active (before or after the build).
# This is expected behavior under a busy queue or a long-running
# lora_training job, not a fault — it gets its own, much higher threshold
# (default 30 ticks, ~1h) and a quieter prio=warning line instead of err.
record_busy_deferral() {
    local active_job_count="$1"
    local count
    count="$(read_counter "$BUSY_COUNT_FILE")"
    count=$((count + 1))
    printf '%s' "$count" >"$BUSY_COUNT_FILE"
    log_debug "busy-deferral count now $count ($active_job_count jobs active)"
    if [[ "$count" -ge "$BUSY_ALERT_THRESHOLD" ]]; then
        log_warning "deploy pending for ~1h, $active_job_count jobs still active"
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
if ! LOCAL_HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD 2>&1)"; then
    log_err "cannot determine local HEAD in $REPO_ROOT: $LOCAL_HEAD"
    record_failure "cannot determine local HEAD"
    exit 1
fi

if ! FETCH_OUTPUT="$(git -C "$REPO_ROOT" fetch origin "$DEPLOY_BRANCH" --quiet 2>&1)"; then
    log_err "git fetch origin $DEPLOY_BRANCH failed in $REPO_ROOT: $FETCH_OUTPUT"
    record_failure "git fetch failed"
    exit 1
fi

if ! REMOTE_HEAD="$(git -C "$REPO_ROOT" rev-parse "origin/$DEPLOY_BRANCH" 2>&1)"; then
    log_err "cannot resolve origin/$DEPLOY_BRANCH in $REPO_ROOT: $REMOTE_HEAD"
    record_failure "cannot resolve origin/$DEPLOY_BRANCH"
    exit 1
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
if ! CURRENT_BRANCH="$(git -C "$REPO_ROOT" symbolic-ref --quiet --short HEAD 2>&1)"; then
    log_guard_reason "HEAD at $REPO_ROOT is not on a branch (detached?) — refusing to deploy, not touching the tree: $CURRENT_BRANCH"
    record_failure "HEAD not on a branch"
    exit 1
fi

if [[ "$CURRENT_BRANCH" != "$DEPLOY_BRANCH" ]]; then
    log_guard_reason "HEAD at $REPO_ROOT is on branch '$CURRENT_BRANCH', not the deploy branch '$DEPLOY_BRANCH' — refusing to deploy, not touching the tree"
    record_failure "HEAD on branch $CURRENT_BRANCH instead of $DEPLOY_BRANCH"
    exit 1
fi

# Branch guard passed — clear any stale reason so a future recurrence (after
# a branch change or a successful deploy in between) logs at err again
# instead of being suppressed by a reason left over from before.
rm -f "$GUARD_REASON_FILE"

# --- 5. Safe to touch? A dirty working tree or a diverged (non-fast-
# forwardable) local main stops here — the host's checkout is also the
# operator's manual workspace.
if ! STATUS_OUTPUT="$(git -C "$REPO_ROOT" status --porcelain 2>&1)"; then
    log_err "cannot determine working tree status in $REPO_ROOT: $STATUS_OUTPUT"
    record_failure "git status failed"
    exit 1
fi

if [[ -n "$STATUS_OUTPUT" ]]; then
    log_err "working tree at $REPO_ROOT is dirty — refusing to deploy, not touching it (the operator may be working here)"
    record_failure "working tree dirty"
    exit 1
fi

if ! git -C "$REPO_ROOT" merge-base --is-ancestor "$LOCAL_HEAD" "$REMOTE_HEAD"; then
    log_err "local HEAD ($LOCAL_HEAD) has diverged from origin/$DEPLOY_BRANCH ($REMOTE_HEAD) — not fast-forwardable, refusing to deploy, not touching the tree"
    record_failure "local HEAD diverged from origin/$DEPLOY_BRANCH"
    exit 1
fi

# --- 6. Job guard, ahead of the first step that touches the checkout. An
# unreachable DB fails closed: unknown job state is treated as "do not
# deploy", not as "assume idle".
if ! ACTIVE_JOB_COUNT="$(active_job_count)"; then
    log_err "cannot reach the database to check for active jobs — refusing to deploy (fail closed): $ACTIVE_JOB_COUNT"
    record_failure "database unreachable before pull"
    exit 1
fi

if [[ "$ACTIVE_JOB_COUNT" -gt 0 ]]; then
    log_info "deploy deferred, $ACTIVE_JOB_COUNT jobs active"
    record_busy_deferral "$ACTIVE_JOB_COUNT"
    exit 0
fi

# --- 7. Pull, then build. No timeout around the build (CLAUDE.md) — a
# cold-cache rebuild legitimately takes 8-15 minutes. Building does not
# recreate any running container, so it cannot kill an in-flight job by
# itself — the recheck in step 8 is what guards the actual recreate. Both
# `git pull` and `compose build` stream straight to this process's own
# stdout/stderr rather than being captured — a failed build's full output
# can easily exceed what a single logger argument can carry (see header) —
# only a short log_err line with the exit code goes through `logger`.
if ! PULL_OUTPUT="$(git -C "$REPO_ROOT" pull --ff-only origin "$DEPLOY_BRANCH" 2>&1)"; then
    log_err "git pull --ff-only failed in $REPO_ROOT despite passing the fast-forward check: $PULL_OUTPUT"
    record_failure "git pull failed"
    exit 1
fi

if compose build; then
    :
else
    BUILD_EXIT_CODE=$?
    log_err "docker compose build failed in $REPO_ROOT (exit $BUILD_EXIT_CODE)"
    record_failure "compose build failed"
    exit 1
fi

# --- 8. Recheck immediately before the recreate — the only step that can
# kill an in-flight job. This shrinks the unsafe window from the build's
# 8-15 minutes down to the seconds between this check and `compose up`. A
# deferral here finds the image already built on the next tick, so the
# recheck lands within seconds rather than after another full build.
if ! ACTIVE_JOB_COUNT="$(active_job_count)"; then
    log_err "cannot reach the database to recheck for active jobs after build — refusing to recreate containers (fail closed): $ACTIVE_JOB_COUNT"
    record_failure "database unreachable after build"
    exit 1
fi

if [[ "$ACTIVE_JOB_COUNT" -gt 0 ]]; then
    log_info "deploy deferred after build, $ACTIVE_JOB_COUNT jobs active"
    record_busy_deferral "$ACTIVE_JOB_COUNT"
    exit 0
fi

# Resolved once, right before the recreate — not after `compose up`
# succeeds — so a broken `rev-parse` here fails the tick outright instead of
# leaving a just-recreated stack with no way to record what it is running.
if ! DEPLOYED_HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD 2>&1)"; then
    log_err "cannot determine HEAD in $REPO_ROOT right before recreate: $DEPLOYED_HEAD"
    record_failure "cannot determine HEAD before recreate"
    exit 1
fi

if compose up -d --wait; then
    if record_success "$DEPLOYED_HEAD"; then
        TICK_EXIT_CODE=0
    else
        TICK_EXIT_CODE=1
    fi
else
    TICK_EXIT_CODE=$?
    log_err "docker compose up -d --wait failed in $REPO_ROOT (exit $TICK_EXIT_CODE)"
    record_failure "compose up failed"
fi

exit "$TICK_EXIT_CODE"

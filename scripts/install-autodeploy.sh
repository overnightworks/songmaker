#!/bin/bash
# Installs the Songmaker pull-based auto-deploy systemd units (issue #298).
#
# scripts/songmaker-autodeploy.service runs scripts/auto-deploy.sh once;
# scripts/songmaker-autodeploy.timer fires it every ~2 minutes. The script
# itself does the actual git-fetch/compare, guard checks, `docker compose
# build`, and `docker compose up -d --wait` — see its header for the full
# design rationale and the incidents that shaped the guards.
#
# The OPERATOR runs this script, not an agent. It only touches
# /etc/systemd/system/ and the systemd unit cache.
#
# WorkingDirectory/ExecStart/User are derived from where this script lives
# and who runs it, exactly like scripts/install-autostart.sh (issue #256):
# running it from a worktree installs units pointing at that worktree, not
# silently at the main checkout; User is SUDO_USER under sudo (otherwise the
# current user), refusing outright if that resolves to root, so the units
# run as the stack owner (whose .env, docker group membership, and Claude
# CLI credentials the deploy needs) rather than as whoever invoked sudo.
#
# Unlike install-autostart.sh, this installer enables AND starts the timer
# immediately (`systemctl enable --now`). That is safe here in a way it is
# not for songmaker.service: starting songmaker.service directly runs
# `docker compose up -d` unconditionally against the live stack, which can
# recreate containers and kill an in-flight generation — the operator has to
# choose that moment deliberately. Starting songmaker-autodeploy.timer only
# arms a ~2-minute schedule; the first tick it triggers goes through
# auto-deploy.sh's own guards in order — up-to-date short-circuit (including
# the deployed.sha check), deploy-branch check, dirty-tree/diverge check,
# active-jobs check before AND after the build — before it would ever touch
# the stack. Its very first-ever tick (no deployed.sha yet) ADOPTS the
# current HEAD as already-deployed instead of deploying: if this checkout
# was behind main at install time, the stack stays on that stale commit
# until the operator deploys it once by hand (see docs/architecture.md).
# There is no unguarded moment to protect the operator from, so there is no
# reason to make them run a second command.
#
# Idempotent: rerunning it re-copies both unit files and re-applies
# enable/start, all no-ops if already applied. If a unit file's content
# changed since the last install, `daemon-reload` picks up the new file
# immediately; the timer re-evaluates its schedule as usual, but an
# in-progress auto-deploy.sh run (already forked off by the previous unit
# generation) is not affected until its next invocation.
#
# Usage:
#   ./scripts/install-autodeploy.sh
#
# Prerequisites: Docker Compose v2 and jq. auto-deploy.sh uses jq to read the
# non-interpolated Compose project and build-service list before a recreate.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
INSTALL_USER="${SUDO_USER:-$(id -un)}"

# systemd unit files field-split on whitespace and expand '%' as a specifier
# (e.g. %h, %H) inside directive values — a checkout path containing either
# cannot be embedded as a plain WorkingDirectory=/ExecStart= value at all, no
# matter how it is escaped for sed. Reject it outright rather than install a
# unit that silently misparses its own paths.
if [[ "$PROJECT_ROOT" == *%* || "$PROJECT_ROOT" =~ [[:space:]] ]]; then
    echo "ERROR: checkout path '$PROJECT_ROOT' contains '%' or whitespace." >&2
    echo "systemd unit files treat '%' as specifier expansion and split fields on" >&2
    echo "whitespace, so this path cannot be embedded into WorkingDirectory=/ExecStart=." >&2
    echo "Move or rename the checkout to a path without '%' or spaces and re-run." >&2
    exit 1
fi

SERVICE_SOURCE="$SCRIPT_DIR/songmaker-autodeploy.service"
SERVICE_TARGET="/etc/systemd/system/songmaker-autodeploy.service"
TIMER_SOURCE="$SCRIPT_DIR/songmaker-autodeploy.timer"
TIMER_TARGET="/etc/systemd/system/songmaker-autodeploy.timer"
DEPLOY_SCRIPT="$SCRIPT_DIR/auto-deploy.sh"
# The shared alert template unit (issue #333) — songmaker-autodeploy.service
# above declares OnFailure=songmaker-alert@%n.service, so it must exist
# before that unit is installed. install-autostart.sh installs the same
# file for songmaker.service; both installers are idempotent and derive
# the same WorkingDirectory/User from their own checkout, so running
# either (or both) converges on one identical installed unit.
ALERT_SERVICE_SOURCE="$SCRIPT_DIR/songmaker-alert@.service"
ALERT_SERVICE_TARGET="/etc/systemd/system/songmaker-alert@.service"
ALERT_SCRIPT="$SCRIPT_DIR/alert.sh"
# Sourced by alert.sh (and by auto-deploy.sh) for the .env keys that
# configure the channel — a checkout missing it has no alert channel at
# all, which is exactly what must not be discovered during an outage.
ALERT_CONFIG_LIB="$SCRIPT_DIR/alert-config.sh"

if [[ ! -f "$SERVICE_SOURCE" ]]; then
    echo "ERROR: $SERVICE_SOURCE not found." >&2
    exit 1
fi

if [[ ! -f "$TIMER_SOURCE" ]]; then
    echo "ERROR: $TIMER_SOURCE not found." >&2
    exit 1
fi

if [[ ! -x "$DEPLOY_SCRIPT" ]]; then
    echo "ERROR: $DEPLOY_SCRIPT not found or not executable." >&2
    exit 1
fi

if [[ ! -f "$ALERT_SERVICE_SOURCE" ]]; then
    echo "ERROR: $ALERT_SERVICE_SOURCE not found." >&2
    exit 1
fi

if [[ ! -x "$ALERT_SCRIPT" ]]; then
    echo "ERROR: $ALERT_SCRIPT not found or not executable." >&2
    exit 1
fi

if [[ ! -f "$ALERT_CONFIG_LIB" ]]; then
    echo "ERROR: $ALERT_CONFIG_LIB not found." >&2
    exit 1
fi

if [[ "$INSTALL_USER" = "root" ]]; then
    echo "ERROR: refusing to install a unit that runs as root." >&2
    echo "You're running this as root directly (no SUDO_USER set), so the unit" >&2
    echo "would get User=root and HOME=/root — that silently breaks the .env and" >&2
    echo "docker group membership the deploy needs from the stack owner's account." >&2
    echo "Log in as the user the stack belongs to and run:" >&2
    echo "  sudo ./scripts/install-autodeploy.sh" >&2
    exit 1
fi

command -v jq >/dev/null || {
    echo "ERROR: jq is required for the pre-recreate rollback tagging but is not installed." >&2
    exit 1
}

# Escape backslash, the sed delimiter (#), and & (which sed would otherwise
# expand to "whatever matched the pattern" in the replacement text). The
# guard above already rejected the '%'/whitespace that systemd itself would
# choke on; this only has to protect sed's own substitution syntax, not
# systemd's parsing of the result.
sed_escape_replacement() {
    printf '%s' "$1" | sed -e 's/[\&#]/\\&/g'
}

ESCAPED_PROJECT_ROOT="$(sed_escape_replacement "$PROJECT_ROOT")"
ESCAPED_INSTALL_USER="$(sed_escape_replacement "$INSTALL_USER")"
ESCAPED_DEPLOY_SCRIPT="$(sed_escape_replacement "$PROJECT_ROOT/scripts/auto-deploy.sh")"
ESCAPED_ALERT_SCRIPT="$(sed_escape_replacement "$PROJECT_ROOT/scripts/alert.sh")"

TMP_SERVICE="$(mktemp)"
TMP_ALERT_SERVICE="$(mktemp)"
trap 'rm -f "$TMP_SERVICE" "$TMP_ALERT_SERVICE"' EXIT

sed -e "s#^WorkingDirectory=.*#WorkingDirectory=$ESCAPED_PROJECT_ROOT#" \
    -e "s#^ExecStart=.*#ExecStart=$ESCAPED_DEPLOY_SCRIPT#" \
    -e "s#^User=.*#User=$ESCAPED_INSTALL_USER#" \
    "$SERVICE_SOURCE" >"$TMP_SERVICE"

# ExecStart carries fixed arguments after the script path (the alert
# subject/body) — only the path prefix up to alert.sh itself is
# substituted, unlike the single-argument ExecStart above.
sed -e "s#^WorkingDirectory=.*#WorkingDirectory=$ESCAPED_PROJECT_ROOT#" \
    -e "s#^ExecStart=.*/scripts/alert\.sh#ExecStart=$ESCAPED_ALERT_SCRIPT#" \
    -e "s#^User=.*#User=$ESCAPED_INSTALL_USER#" \
    "$ALERT_SERVICE_SOURCE" >"$TMP_ALERT_SERVICE"

echo "Installing $ALERT_SERVICE_TARGET (WorkingDirectory=$PROJECT_ROOT, ExecStart=$PROJECT_ROOT/scripts/alert.sh ..., User=$INSTALL_USER)..."
sudo install -m 0644 "$TMP_ALERT_SERVICE" "$ALERT_SERVICE_TARGET"

echo "Installing $SERVICE_TARGET (WorkingDirectory=$PROJECT_ROOT, ExecStart=$PROJECT_ROOT/scripts/auto-deploy.sh, User=$INSTALL_USER)..."
sudo install -m 0644 "$TMP_SERVICE" "$SERVICE_TARGET"

echo "Installing $TIMER_TARGET..."
sudo install -m 0644 "$TIMER_SOURCE" "$TIMER_TARGET"

echo "Reloading systemd unit files..."
sudo systemctl daemon-reload

echo "Enabling and starting songmaker-autodeploy.timer..."
sudo systemctl enable --now songmaker-autodeploy.timer

echo
echo "Done. songmaker-autodeploy.timer is armed and will tick every ~2 minutes."
echo "The first tick runs within 2 minutes and is safe to run against the live"
echo "stack: auto-deploy.sh only pulls + redeploys when origin/main has moved,"
echo "the local tree is clean and fast-forwardable, and no jobs are active."
echo
echo "songmaker-alert@.service is installed alongside it (issue #333):"
echo "songmaker-autodeploy.service emails ALERT_EMAIL_TO once three deploy"
echo "attempts in a row have failed (~6 minutes while the ticks are quick,"
echo "longer when one of them waits out a slow deploy), then again once an"
echo "hour for as long as it stays stuck."
echo "Set ALERT_EMAIL_TO/SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD in"
echo ".env for this to actually send — without them the stack's alertmanager"
echo "refuses to start and auto-deploy.sh refuses to deploy, both naming the"
echo "missing keys, instead of silently doing nothing."
echo
echo "To verify what's installed:"
echo "  systemctl status songmaker-autodeploy.timer"
echo "  systemctl list-timers songmaker-autodeploy.timer"
echo "  journalctl -t songmaker-autodeploy -f"
echo
echo "Acceptance step: wait for the first tick (up to 2 minutes), then confirm"
echo "it actually ran before walking away:"
echo "  journalctl -t songmaker-autodeploy -n 5"

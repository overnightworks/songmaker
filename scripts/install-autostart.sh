#!/bin/bash
# Installs the Songmaker boot-autostart systemd unit (issue #256).
#
# `restart: unless-stopped` only revives a container that has already
# started at least once. A container docker compose merely *created* but
# never started (e.g. a failed `docker compose up` after a driver mismatch)
# is ignored by dockerd on every daemon start and survives any number of
# reboots on its own. This unit closes that gap: it runs
# `docker compose up -d` (no `--build`) once per boot, after docker.service
# is up, which starts every container regardless of the state it was left
# in — running, exited, or created.
#
# The OPERATOR runs this script, not an agent. It only touches
# /etc/systemd/system/ and the systemd unit cache. `systemctl enable` takes
# effect on the NEXT boot only — it does not touch the running stack.
# Starting the unit immediately (see the final message this script prints)
# runs `docker compose up -d` against whatever is running right now: if
# .env or code changed since the containers were last started, compose may
# recreate them (and re-run the migrate container), which can kill an
# in-flight generation. Do that deliberately, in a maintenance window —
# this script does not do it for you.
#
# WorkingDirectory is derived from where this script lives, not hardcoded,
# so running it from a worktree installs a unit pointing at that worktree
# rather than silently at the main checkout. User is derived from who is
# running the installer (SUDO_USER when invoked via `sudo`, otherwise the
# current user) — NOT from where the script lives — because that's whose
# stack (.env, docker group membership, Claude CLI credentials) the unit
# should run as. Run this script as your normal user (with sudo prompting
# inline), not from an already-root login: see the root check below.
#
# Idempotent for `enable`: rerunning it re-copies the unit file and
# re-applies enable, both no-ops if already applied. If the unit file
# content changed since the last install (e.g. this script itself is a
# newer version), `daemon-reload` picks up the new file immediately, but a
# unit that is already active (RemainAfterExit=yes) only picks up a new
# ExecStart on the next boot or an explicit `systemctl restart` — see
# docs/acestep.md.
#
# Usage:
#   ./scripts/install-autostart.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
INSTALL_USER="${SUDO_USER:-$(id -un)}"
UNIT_SOURCE="$SCRIPT_DIR/songmaker.service"
UNIT_TARGET="/etc/systemd/system/songmaker.service"
# The shared alert template unit (issue #333) — songmaker.service above
# declares OnFailure=songmaker-alert@%n.service, so it must exist before
# that unit is installed. install-autodeploy.sh installs the same file
# for songmaker-autodeploy.service; both installers are idempotent and
# derive the same WorkingDirectory/User from their own checkout, so
# running either (or both) converges on one identical installed unit.
ALERT_UNIT_SOURCE="$SCRIPT_DIR/songmaker-alert@.service"
ALERT_UNIT_TARGET="/etc/systemd/system/songmaker-alert@.service"
ALERT_SCRIPT="$SCRIPT_DIR/alert.sh"
# Sourced by alert.sh (and by auto-deploy.sh) for the .env keys that
# configure the channel — a checkout missing it has no alert channel at
# all, which is exactly what must not be discovered during an outage.
ALERT_CONFIG_LIB="$SCRIPT_DIR/alert-config.sh"

if [ ! -f "$UNIT_SOURCE" ]; then
    echo "ERROR: $UNIT_SOURCE not found." >&2
    exit 1
fi

if [ ! -f "$ALERT_UNIT_SOURCE" ]; then
    echo "ERROR: $ALERT_UNIT_SOURCE not found." >&2
    exit 1
fi

if [ ! -x "$ALERT_SCRIPT" ]; then
    echo "ERROR: $ALERT_SCRIPT not found or not executable." >&2
    exit 1
fi

if [ ! -f "$ALERT_CONFIG_LIB" ]; then
    echo "ERROR: $ALERT_CONFIG_LIB not found." >&2
    exit 1
fi

if [ "$INSTALL_USER" = "root" ]; then
    echo "ERROR: refusing to install a unit that runs as root." >&2
    echo "You're running this as root directly (no SUDO_USER set), so the unit" >&2
    echo "would get User=root and HOME=/root — that silently breaks the Claude" >&2
    echo "CLI bind mounts co-writer/lyrical_coherence depend on (docker-compose.yml" >&2
    echo "expects them under the stack owner's home, not /root)." >&2
    echo "Log in as the user the stack belongs to and run:" >&2
    echo "  sudo ./scripts/install-autostart.sh" >&2
    exit 1
fi

# Escape backslash, the sed delimiter (#), and & (which sed would otherwise
# expand to "whatever matched the pattern" in the replacement text) so an
# unusual PROJECT_ROOT or INSTALL_USER can never corrupt or misdirect the
# substitution below.
sed_escape_replacement() {
    printf '%s' "$1" | sed -e 's/[\&#]/\\&/g'
}

ESCAPED_PROJECT_ROOT="$(sed_escape_replacement "$PROJECT_ROOT")"
ESCAPED_INSTALL_USER="$(sed_escape_replacement "$INSTALL_USER")"
ESCAPED_ALERT_SCRIPT="$(sed_escape_replacement "$PROJECT_ROOT/scripts/alert.sh")"

TMP_UNIT="$(mktemp)"
TMP_ALERT_UNIT="$(mktemp)"
trap 'rm -f "$TMP_UNIT" "$TMP_ALERT_UNIT"' EXIT

sed -e "s#^WorkingDirectory=.*#WorkingDirectory=$ESCAPED_PROJECT_ROOT#" \
    -e "s#^User=.*#User=$ESCAPED_INSTALL_USER#" \
    "$UNIT_SOURCE" > "$TMP_UNIT"

# ExecStart carries fixed arguments after the script path (the alert
# subject/body) — only the path prefix up to alert.sh itself is
# substituted.
sed -e "s#^WorkingDirectory=.*#WorkingDirectory=$ESCAPED_PROJECT_ROOT#" \
    -e "s#^ExecStart=.*/scripts/alert\.sh#ExecStart=$ESCAPED_ALERT_SCRIPT#" \
    -e "s#^User=.*#User=$ESCAPED_INSTALL_USER#" \
    "$ALERT_UNIT_SOURCE" > "$TMP_ALERT_UNIT"

echo "Installing $ALERT_UNIT_TARGET (WorkingDirectory=$PROJECT_ROOT, ExecStart=$PROJECT_ROOT/scripts/alert.sh ..., User=$INSTALL_USER)..."
sudo install -m 0644 "$TMP_ALERT_UNIT" "$ALERT_UNIT_TARGET"

echo "Installing $UNIT_TARGET (WorkingDirectory=$PROJECT_ROOT, User=$INSTALL_USER)..."
sudo install -m 0644 "$TMP_UNIT" "$UNIT_TARGET"

echo "Reloading systemd unit files..."
sudo systemctl daemon-reload

echo "Enabling songmaker.service to run on every future boot..."
sudo systemctl enable songmaker.service

echo
echo "Done. songmaker.service will run 'docker compose up -d' starting with the NEXT boot."
echo "It has NOT touched the currently running stack."
echo
echo "To verify what's installed:"
echo "  systemctl status songmaker.service"
echo "  docker compose -f $PROJECT_ROOT/docker-compose.yml ps -a"
echo
echo "To apply it right now instead of waiting for a reboot (touches the live"
echo "stack — may recreate containers and kill an in-flight generation if .env"
echo "or code changed since the last start; do this in a maintenance window):"
echo "  sudo systemctl start songmaker.service"

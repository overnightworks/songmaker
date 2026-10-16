#!/bin/bash
# Installs the Songmaker agent-CLI login mirror (issue #350).
#
# scripts/mirror_agent_cli_credentials.py copies the operator's claude, grok
# and codex logins into ~/.songmaker/agent-cli-credentials/ — the only place
# the containers are allowed to read them from, and read-only at that. See
# that script's header for why a copy is needed rather than a mount of the
# real file, and docs/security.md, "Agent-CLI Mounts", for the trust model.
#
# Three units, all pointing at the same oneshot service:
#   .service  does the copy, at boot and whenever it is triggered
#   .path     re-runs it the moment a login file changes (a token refresh)
#   .timer    re-runs it every 10 minutes as a safety net, because a missed
#             inotify event would otherwise leave the containers on a stale
#             token until someone noticed the co-writer had died
#
# The OPERATOR runs this script, not an agent. It only touches
# /etc/systemd/system/, the systemd unit cache, and the operator's own
# ~/.songmaker/agent-cli-credentials/.
#
# RUN IT BEFORE DEPLOYING THE COMMIT THAT ADDS THESE MOUNTS. The stack mounts
# the mirrored files with `create_host_path: false`; deploying first would
# leave compose refusing to start until the mirror exists.
#
# ONLY FROM THE MAIN CHECKOUT. These units outlive whatever shell installed
# them: ExecStart points at this checkout forever, so installing from a
# throwaway issue worktree means the mirror — and with it the co-writer —
# stops the day that worktree is removed. Git itself is asked which checkout
# is the main one (`git rev-parse --git-common-dir`), and a run from a linked
# worktree is refused rather than warned about.
#
# It also refuses to silently replace an installed unit that points somewhere
# else: that is either a second checkout taking over or a hand-edited unit,
# and both deserve a look before they disappear. --force says "yes, mine now".
#
# User is SUDO_USER under sudo (otherwise the current user), refusing outright
# if that resolves to root, so the mirror runs as the person whose logins it
# copies. The mirror directory is resolved ONCE here, from .env if it names
# one, and that single answer is written into the unit, into
# the check this script runs — and, once the containers mount these files,
# into that unit's preflight too.
#
# Idempotent: rerunning re-copies the unit files, re-applies enable/start, and
# refreshes the mirror once — all no-ops if already applied.
#
# Usage:
#   ./scripts/install-cli-credentials-mirror.sh [--force]

set -euo pipefail

FORCE=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force) FORCE=1; shift ;;
        *) echo "ERROR: unknown argument '$1'. Usage: $0 [--force]" >&2; exit 2 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
INSTALL_USER="${SUDO_USER:-$(id -un)}"

# The units run as this user and mirror this user's logins. Resolving to root
# means the script was started from a root login rather than with sudo: it
# would then install units that mirror /root's logins — which are not the ones
# the co-writer uses — and the operator would find an empty mirror with no
# error to explain it.
if [[ "$INSTALL_USER" = "root" ]]; then
    echo "ERROR: refusing to install units that would run as root." >&2
    echo "SUDO_USER is unset, so this looks like a root login rather than" >&2
    echo "sudo. The units would mirror /root's agent-CLI logins, not the" >&2
    echo "operator's. Log in as the account the stack belongs to and run:" >&2
    echo "  sudo ./scripts/install-cli-credentials-mirror.sh" >&2
    exit 1
fi

# shellcheck source=scripts/agent-cli-paths.sh
source "$SCRIPT_DIR/agent-cli-paths.sh"
require_main_checkout "$PROJECT_ROOT" install-cli-credentials-mirror.sh || exit 1

INSTALL_HOME="$(getent passwd "$INSTALL_USER" | cut -d: -f6)"
if [[ -z "$INSTALL_HOME" ]]; then
    echo "ERROR: could not resolve the home directory of '$INSTALL_USER'." >&2
    exit 1
fi

# One resolution of the mirror directory, owned by the mirror script itself,
# so the unit, the preflight and this script can never look at different files
# than compose will mount.
MIRROR_DIR="$(resolve_mirror_dir "$PROJECT_ROOT" "$INSTALL_HOME")" || exit 1

# Where units are installed. Overridable for exactly one reason: nothing else
# can prove this script runs, and two crashes shipped in it because nothing
# ever did (see tests/test_install_cli_credentials_mirror.py). systemd itself
# only ever reads /etc/systemd/system.
UNIT_DIR="${SONGMAKER_UNIT_DIR:-/etc/systemd/system}"

SERVICE_SOURCE="$SCRIPT_DIR/songmaker-cli-credentials-mirror.service"
SERVICE_TARGET="$UNIT_DIR/songmaker-cli-credentials-mirror.service"
PATH_SOURCE="$SCRIPT_DIR/songmaker-cli-credentials-mirror.path"
PATH_TARGET="$UNIT_DIR/songmaker-cli-credentials-mirror.path"
TIMER_SOURCE="$SCRIPT_DIR/songmaker-cli-credentials-mirror.timer"
TIMER_TARGET="$UNIT_DIR/songmaker-cli-credentials-mirror.timer"
MIRROR_SCRIPT="$SCRIPT_DIR/mirror_agent_cli_credentials.py"
CHECK_SCRIPT="$SCRIPT_DIR/check_agent_cli_mounts.sh"
# The shared alert template unit (issue #333) — the mirror service declares
# OnFailure=songmaker-alert@%n.service, so it must exist before that unit is
# installed. install-autostart.sh and install-autodeploy.sh install the same
# file; all of them are idempotent and derive the same WorkingDirectory/User
# from their own checkout.
ALERT_SERVICE_SOURCE="$SCRIPT_DIR/songmaker-alert@.service"
ALERT_SERVICE_TARGET="$UNIT_DIR/songmaker-alert@.service"
ALERT_SCRIPT="$SCRIPT_DIR/alert.sh"

for required in "$SERVICE_SOURCE" "$PATH_SOURCE" "$TIMER_SOURCE" "$ALERT_SERVICE_SOURCE"; do
    if [[ ! -f "$required" ]]; then
        echo "ERROR: $required not found." >&2
        exit 1
    fi
done

for required in "$MIRROR_SCRIPT" "$CHECK_SCRIPT" "$ALERT_SCRIPT"; do
    if [[ ! -x "$required" ]]; then
        echo "ERROR: $required not found or not executable." >&2
        exit 1
    fi
done

# Escape backslash, the sed delimiter (#), and & (which sed would otherwise
# expand to "whatever matched the pattern" in the replacement text).
sed_escape_replacement() {
    printf '%s' "$1" | sed -e 's/[\&#]/\\&/g'
}

ESCAPED_PROJECT_ROOT="$(sed_escape_replacement "$PROJECT_ROOT")"
ESCAPED_INSTALL_USER="$(sed_escape_replacement "$INSTALL_USER")"
ESCAPED_MIRROR_SCRIPT="$(sed_escape_replacement "$MIRROR_SCRIPT")"
ESCAPED_ALERT_SCRIPT="$(sed_escape_replacement "$PROJECT_ROOT/scripts/alert.sh")"
ESCAPED_HOME="$(sed_escape_replacement "$INSTALL_HOME")"
ESCAPED_MIRROR_DIR="$(sed_escape_replacement "$MIRROR_DIR")"
ESCAPED_CHECK_SCRIPT="$(sed_escape_replacement "$CHECK_SCRIPT")"

MIRROR_EXEC="$MIRROR_SCRIPT --home $INSTALL_HOME --mirror-dir $MIRROR_DIR"
ALERT_EXEC_PREFIX="$PROJECT_ROOT/scripts/alert.sh"

# The path unit's watches are compared as a SET, not one by one. Proving that
# the three expected lines are present says nothing about a fourth: a foreign
# PathChanged=, or any PathModified= this run would not write, sat there
# unnoticed. Everything the installed unit watches must be exactly what this
# run watches — no more, no less.
_watches_are_ours() {
    local target="$1"
    shift
    local installed expected
    [[ -f "$target" ]] || return 0
    installed="$(sed -n 's/^Path\(Changed\|Modified\|Exists\)=//p' "$target" \
        | LC_ALL=C sort -u)"
    expected="$(printf '%s\n' "$@" | LC_ALL=C sort -u)"
    [[ "$installed" != "$expected" ]] || return 0

    if [[ "$FORCE" = "1" ]]; then
        echo "Replacing $target (--force): it watches something else"
        return 0
    fi
    echo "ERROR: $target belongs to something else." >&2
    echo "  it watches:" >&2
    printf '    %s\n' $installed >&2
    echo "  this run watches:" >&2
    printf '    %s\n' $expected >&2
    echo "Another checkout installed it, or it was edited by hand. Look" >&2
    echo "first; re-run with --force to take it over." >&2
    return 1
}

# EVERY check before the FIRST write. Half an installation is worse than none:
# a run that replaces the alert unit and then refuses at the mirror unit
# leaves two checkouts owning one machine's systemd, which is exactly the
# state --force exists to make someone look at.
# ExecStart is a command with arguments, so ours-with-other-arguments is still
# ours. PathChanged and Unit hold one value, so they are compared exactly —
# and the path unit's watches are compared as a whole set against the home
# this run installs for, so neither a missing watch nor an extra one gets
# through.
refuse_silent_takeover "$SERVICE_TARGET" ExecStart "$MIRROR_SCRIPT" "$FORCE" command || exit 1
refuse_silent_takeover "$ALERT_SERVICE_TARGET" ExecStart "$ALERT_EXEC_PREFIX" "$FORCE" command || exit 1
refuse_silent_takeover "$TIMER_TARGET" Unit \
    "songmaker-cli-credentials-mirror.service" "$FORCE" || exit 1
_watches_are_ours "$PATH_TARGET" \
    "$INSTALL_HOME/.claude/.credentials.json" \
    "$INSTALL_HOME/.grok/auth.json" \
    "$INSTALL_HOME/.codex/auth.json" || exit 1

TMP_SERVICE="$(mktemp)"
TMP_PATH="$(mktemp)"
TMP_ALERT_SERVICE="$(mktemp)"
trap 'rm -f "$TMP_SERVICE" "$TMP_PATH" "$TMP_ALERT_SERVICE"' EXIT

sed -e "s#^WorkingDirectory=.*#WorkingDirectory=$ESCAPED_PROJECT_ROOT#" \
    -e "s#^ExecStart=.*#ExecStart=$ESCAPED_MIRROR_SCRIPT --home $ESCAPED_HOME --mirror-dir $ESCAPED_MIRROR_DIR#" \
    -e "s#^User=.*#User=$ESCAPED_INSTALL_USER#" \
    "$SERVICE_SOURCE" >"$TMP_SERVICE"

# Only the home prefix of each watched login path is substituted; the
# per-CLI suffix is part of the unit.
sed -e "s#^\(Path[A-Za-z]*=\)/home/[^/]*/#\1$ESCAPED_HOME/#" \
    "$PATH_SOURCE" >"$TMP_PATH"

sed -e "s#^WorkingDirectory=.*#WorkingDirectory=$ESCAPED_PROJECT_ROOT#" \
    -e "s#^ExecStart=.*/scripts/alert\.sh#ExecStart=$ESCAPED_ALERT_SCRIPT#" \
    -e "s#^User=.*#User=$ESCAPED_INSTALL_USER#" \
    "$ALERT_SERVICE_SOURCE" >"$TMP_ALERT_SERVICE"

echo "Installing $ALERT_SERVICE_TARGET (WorkingDirectory=$PROJECT_ROOT, User=$INSTALL_USER)..."
sudo install -m 0644 "$TMP_ALERT_SERVICE" "$ALERT_SERVICE_TARGET"

echo "Installing $SERVICE_TARGET (ExecStart=$MIRROR_EXEC)..."
sudo install -m 0644 "$TMP_SERVICE" "$SERVICE_TARGET"

echo "Installing $PATH_TARGET (watching $INSTALL_HOME/.claude, .grok, .codex)..."
sudo install -m 0644 "$TMP_PATH" "$PATH_TARGET"

echo "Installing $TIMER_TARGET..."
sudo install -m 0644 "$TIMER_SOURCE" "$TIMER_TARGET"

echo "Reloading systemd unit files..."
sudo systemctl daemon-reload

echo "Enabling the mirror at boot, before the stack..."
sudo systemctl enable songmaker-cli-credentials-mirror.service

echo "Enabling and starting the login watch and its safety-net timer..."
sudo systemctl enable --now songmaker-cli-credentials-mirror.path
sudo systemctl enable --now songmaker-cli-credentials-mirror.timer

echo "Writing the mirror once, now..."
sudo systemctl start songmaker-cli-credentials-mirror.service

echo
echo "Verifying every mount source the stack expects, as $INSTALL_USER..."
# As the install user, not as root under sudo: the check must look at the same
# home and the same mirror directory compose will mount from.
sudo -u "$INSTALL_USER" "$CHECK_SCRIPT" --home "$INSTALL_HOME" --mirror-dir "$MIRROR_DIR"

echo
echo "Done. The containers may now be started; they mount only"
echo "$MIRROR_DIR/, read-only, and no renewal secret is in any of those files."
echo
echo "Nothing mounts these copies yet — that is the container-side change,"
echo "which must not land before this installer has been run."
echo
echo "To verify what's installed:"
echo "  systemctl status songmaker-cli-credentials-mirror.path"
echo "  systemctl list-timers songmaker-cli-credentials-mirror.timer"
echo "  journalctl -u songmaker-cli-credentials-mirror.service -n 20 --no-pager"
echo
echo "If the co-writer ever reports Claude unavailable, the first thing to"
echo "check is whether this mirror is still running — a stopped mirror leaves"
echo "the containers on the token they started with, and no container can"
echo "refresh one. Restart it with:"
echo "  sudo systemctl start songmaker-cli-credentials-mirror.service"

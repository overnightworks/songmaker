#!/bin/bash
# Checks that every host path docker-compose.yml bind-mounts for the agent
# CLIs is there AND is the kind of thing it is supposed to be (issue #350).
#
# Why a type check and not just an existence check: compose mounts these with
# `bind: create_host_path: false`, so a missing path already fails the stack
# loudly. What that flag cannot catch is a path of the WRONG KIND — a
# credential file that is a symlink to somewhere else, one with a second hard
# link, one another account owns, or one still carrying a renewal token
# because somebody copied a real login in by hand. Those mount happily and
# either break at runtime or quietly widen what the container reaches.
#
# The credential files are checked by mirror_agent_cli_credentials.py itself
# (`--verify`), not re-implemented here: it opens each file with O_NOFOLLOW,
# checks owner, link count and mode on the open descriptor, parses the JSON
# and refuses any renewal token in it. A shell `test -f` plus a grep promises
# less than it claims — it follows symlinks and knows neither owner nor JSON.
# One check, two callers.
#
# The CLI binaries may be symlinks — that is how grok and codex are installed
# — but must resolve to a regular executable file.
#
# There is ONE answer to "where does the mirror live", and that same module
# owns it: the environment, then .env, exactly as compose reads them. Called
# with no arguments — as the auto-deploy tick does (#364) — this script
# resolves that answer, so the tick, the systemd units and the installer
# cannot check different files than compose mounts. The flags override it for
# the installer and for the units, which bake the resolved path in.
#
# Run it before deploying, and after installing or updating any of the CLIs:
#   ./scripts/check_agent_cli_mounts.sh [--home DIR] [--mirror-dir DIR]
#
# Exits 0 when the stack can be started, non-zero with one line per problem.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
MIRROR_SCRIPT="$SCRIPT_DIR/mirror_agent_cli_credentials.py"
# shellcheck source=scripts/agent-cli-paths.sh
source "$SCRIPT_DIR/agent-cli-paths.sh"

HOME_DIR=""
CREDENTIALS_DIR=""

while [ $# -gt 0 ]; do
    case "$1" in
        --mirror-dir) [ $# -ge 2 ] || { echo "ERROR: --mirror-dir needs a directory." >&2; exit 2; }
                      CREDENTIALS_DIR="$2"; shift 2 ;;
        --mirror-dir=*) CREDENTIALS_DIR="${1#--mirror-dir=}"; shift ;;
        --home) [ $# -ge 2 ] || { echo "ERROR: --home needs a directory." >&2; exit 2; }
                HOME_DIR="$2"; shift 2 ;;
        --home=*) HOME_DIR="${1#--home=}"; shift ;;
        *) echo "ERROR: unknown argument '$1'." >&2
           echo "Usage: $0 [--home DIR] [--mirror-dir DIR]" >&2
           exit 2 ;;
    esac
done

: "${HOME_DIR:=$(owner_home)}"
if [ -z "$HOME_DIR" ]; then
    echo "ERROR: could not resolve the stack owner's home directory." >&2
    exit 2
fi
if [ -z "$CREDENTIALS_DIR" ]; then
    CREDENTIALS_DIR="$(resolve_mirror_dir "$PROJECT_ROOT" "$HOME_DIR")" || exit 2
fi

CLAUDE_CLI="${SONGMAKER_CLAUDE_CLI:-$HOME_DIR/.local/bin/claude}"
GROK_CLI="${SONGMAKER_GROK_CLI:-$HOME_DIR/.grok/bin/grok}"
CODEX_CLI="${SONGMAKER_CODEX_CLI:-$HOME_DIR/.local/node/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex}"

problems=0

problem() {
    echo "ERROR: $*" >&2
    problems=$((problems + 1))
}

check_binary() {
    local label="$1" path="$2"
    if [ ! -e "$path" ]; then
        problem "$label CLI '$path' is missing. Install the CLI, or point" \
            "SONGMAKER_${label^^}_CLI at where it really lives."
        return
    fi
    local resolved
    resolved="$(readlink -f "$path")"
    if [ ! -f "$resolved" ]; then
        problem "$label CLI '$path' resolves to '$resolved', which is not a" \
            "regular file."
        return
    fi
    if [ ! -x "$resolved" ]; then
        problem "$label CLI '$resolved' is not executable."
        return
    fi
    echo "ok: $label CLI at $path -> $resolved"
}

# Files alone are not enough. Old-but-valid copies pass every content check
# while nothing keeps them current: if the mirror unit was never installed, or
# was disabled, the next token refresh on the host silently strands whatever
# reads these — and it strands it hours later, with no change to blame.
check_mirror_is_running() {
    local unit="songmaker-cli-credentials-mirror.service"
    if ! command -v systemctl >/dev/null 2>&1; then
        problem "systemctl is not available, so it cannot be confirmed that" \
            "$unit keeps the mirror current."
        return
    fi
    if ! systemctl list-unit-files "$unit" >/dev/null 2>&1 \
        || [ -z "$(systemctl list-unit-files --no-legend "$unit" 2>/dev/null)" ]; then
        problem "$unit is not installed. Nothing keeps the mirrored logins" \
            "current; the containers would strand on the token they started" \
            "with. Run: sudo ./scripts/install-cli-credentials-mirror.sh"
        return
    fi
    if ! systemctl is-enabled --quiet "$unit" 2>/dev/null; then
        problem "$unit is installed but not enabled, so a reboot leaves the" \
            "mirror unwritten. Run: sudo systemctl enable $unit"
        return
    fi
    echo "ok: $unit is installed and enabled"
}

if ! "$MIRROR_SCRIPT" --verify --mirror-dir "$CREDENTIALS_DIR" --home "$HOME_DIR"; then
    problems=$((problems + 1))
fi

check_mirror_is_running

check_binary claude "$CLAUDE_CLI"
check_binary grok "$GROK_CLI"
check_binary codex "$CODEX_CLI"

if [ "$problems" -gt 0 ]; then
    echo >&2
    echo "docker compose would either refuse to start or mount something the" >&2
    echo "CLIs cannot use — see docs/security.md, \"Agent-CLI Mounts\"." >&2
    exit 1
fi

echo "All agent-CLI mount sources are present and of the expected type."

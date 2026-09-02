#!/bin/bash
# What both installers and the mount preflight must agree on (issue #350).
#
# Two things live here because two callers each would otherwise answer them
# differently, and a difference is invisible until it matters:
#
#   resolve_mirror_dir      where the agent-CLI login mirror lives. Delegates
#                           to scripts/mirror_agent_cli_credentials.py, which
#                           owns the grammar — the environment, then .env,
#                           exactly as compose reads them. Shelling out keeps
#                           one parser rather than a bash imitation of dotenv
#                           that disagrees about quotes and comments.
#
#   require_main_checkout   permanent units may only be installed from the
#                           checkout that is not disposable.
#   refuse_silent_takeover  and may not silently replace a unit that runs
#                           something else.
#
# Sourced, never executed:
#   source "$SCRIPT_DIR/agent-cli-paths.sh"

# The account that owns the stack, read from passwd rather than from $HOME:
# under `sudo -H` the environment says /root while compose still mounts out of
# the operator's home, and that gap is how a check passes for files nobody
# mounts.
owner_home() {
    getent passwd "$(id -un)" | cut -d: -f6
}

resolve_mirror_dir() {
    local project_root="$1" install_home="$2"
    "$project_root/scripts/mirror_agent_cli_credentials.py" \
        --print-mirror-dir --project-root "$project_root" --home "$install_home"
}

# A linked worktree's admin directory lives inside the main checkout's .git,
# so the common dir names the one checkout that is not disposable. Installing
# from a throwaway worktree would point ExecStart there forever; the day the
# worktree is removed, the unit stops — and for the mirror unit that takes the
# co-writer with it.
require_main_checkout() {
    local project_root="$1" installer="$2" git_common_dir main_checkout
    git_common_dir="$(git -C "$project_root" rev-parse --path-format=absolute \
        --git-common-dir 2>/dev/null || true)"
    if [ -z "$git_common_dir" ]; then
        echo "ERROR: $project_root is not a git checkout." >&2
        return 1
    fi
    main_checkout="$(dirname "$git_common_dir")"
    if [ "$main_checkout" != "$project_root" ]; then
        echo "ERROR: refusing to install permanent units from a linked worktree." >&2
        echo "  this checkout: $project_root" >&2
        echo "  main checkout: $main_checkout" >&2
        echo "The units would keep pointing here after this worktree is removed." >&2
        echo "Run:" >&2
        echo "  cd $main_checkout && sudo ./scripts/$installer" >&2
        return 1
    fi
}

# Replacing a unit that belongs to somebody else is either a second checkout
# taking over or a hand-edited unit. Both deserve a look before they vanish.
#
# Ownership is read from ONE directive per unit rather than by comparing whole
# files: a unit legitimately changes between versions of this repository, and a
# guard that fired on every upgrade would be turned off within a week. The
# directive is the one that names who the unit belongs to — the script an
# ExecStart runs, the home a PathChanged watches, the service a timer drives.
#
# Two ways this used to wave a stranger through, both closed:
#
#   * a unit WITHOUT that directive counted as ours. It is now foreign: a file
#     we cannot identify is exactly the one to stop at.
#   * the comparison was an unbounded prefix, so `…/mirror.py.evil` passed as
#     `…/mirror.py`. It now has to match to a token boundary — end of string,
#     or a space before the arguments — which is what keeps our own unit with
#     changed arguments ours while a lookalike is not.
#
# The third weakness was in the caller, not here: the path unit was compared
# against the operator's home rather than the file it watches, so a second
# checkout watching the same operator passed. It is compared against the full
# path now.
#
#   refuse_silent_takeover TARGET DIRECTIVE EXPECTED FORCE
refuse_silent_takeover() {
    local target="$1" directive="$2" expected="$3" force="$4"
    local installed reason=""
    [ -f "$target" ] || return 0
    installed="$(sed -n "s/^${directive}=//p" "$target" | head -1)"

    if [ -z "$installed" ]; then
        reason="it has no $directive= line, so it cannot be identified"
    else
        case "$installed" in
            "$expected"|"$expected "*) ;;
            *) reason="its $directive is: $installed" ;;
        esac
    fi
    [ -n "$reason" ] || return 0

    if [ "$force" = "1" ]; then
        echo "Replacing $target (--force): $reason"
        return 0
    fi
    echo "ERROR: $target belongs to something else." >&2
    echo "  $reason" >&2
    echo "  this run expects $directive: $expected" >&2
    echo "Another checkout installed it, or it was edited by hand. Look first;" >&2
    echo "re-run with --force to take it over." >&2
    return 1
}

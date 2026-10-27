#!/bin/bash
# Moves the live stack's deploy checkout from the work clone ~/git/songmaker to
# the release clone ~/srv/songmaker, or moves it back (issue #1880, the host
# steps of #1812).
#
#   scripts/switch_deploy_checkout.sh <tag>      switch, e.g. v2026.10.27.1
#   scripts/switch_deploy_checkout.sh --backout  return to ~/git/songmaker
#
# The OPERATOR runs this once, as themselves (not as root). It prints each step
# before it runs it and stops at the first failed check, naming the step, what
# failed and the command that backs out. It never touches the running stack: no
# `docker compose up`, `down` or `restart`, and no start of songmaker.service.
# sudo is used only for `systemctl` on the autodeploy timer and for the three
# installers; it asks for a password itself. .env is only ever compared or
# copied, never read or printed.
#
# The backout holds until the old .env is deleted and until the first release
# has deployed from ~/srv/songmaker; after either, the fix is a newer tag.
set -uo pipefail

WORK_CLONE="$HOME/git/songmaker"
RELEASE_CLONE="$HOME/srv/songmaker"
TIMER=songmaker-autodeploy.timer
UNITS=(songmaker-autodeploy.service songmaker.service songmaker-cli-credentials-mirror.service songmaker-alert@.service)
REPOSITORY_URL=https://github.com/overnightworks/songmaker.git

step_label=""
last_safe_step=4
installers_started=no

begin() {
    step_label=$1
    printf '%s: %s\n' "$step_label" "$2"
}

# Succeeds when every WorkingDirectory= and every absolute script path in the
# Exec* lines names the directory, and nothing names the other clone. The docker
# executable of songmaker.service names no checkout and is not a script path.
units_name_only() {
    local directory=$1 other=$2 output working scripts
    output=$(systemctl cat "${UNITS[@]}") || return 1
    working=$(grep -E '^WorkingDirectory=' <<<"$output") || return 1
    scripts=$(grep -E '^Exec' <<<"$output" | grep -oE '(^|[ =])/[^ ]+\.(sh|py)' | sed -E 's/^[ =]//') || return 1
    ! grep -v -x -F -e "WorkingDirectory=$directory" <<<"$working" >/dev/null || return 1
    ! grep -v -F -e "$directory/" <<<"$scripts" >/dev/null || return 1
    ! grep -F -e "$other" <<<"$output" >/dev/null
}

compose_project_name() {
    docker compose config --no-interpolate --format json |
        python3 -c 'import json, sys; print(json.load(sys.stdin)["name"])'
}

compose_config_files() {
    docker compose ls --format json |
        python3 -c '
import json, sys
for project in json.load(sys.stdin):
    if project.get("Name") == "songmaker":
        print(project.get("ConfigFiles", ""))'
}

stop_with() {
    printf 'stopped at %s: %s\n' "$step_label" "$1" >&2
    exit 1
}

# `step 5` and later (switch): the clone, the copies or the units may have changed.
stop_switch() {
    local failed_number=${step_label#step }
    local consequence=""
    if ((failed_number <= last_safe_step)); then
        if sudo systemctl start "$TIMER"; then
            consequence="; nothing changed, the timer is running again"
        else
            consequence="; nothing changed, but the timer could not be restarted (run: sudo systemctl start $TIMER)"
        fi
    fi
    printf 'stopped at %s: %s%s\n' "$step_label" "$1" "$consequence" >&2
    printf 'back out with: %s --backout\n' "$0" >&2
    exit 1
}

# Before B4 nothing was reinstalled, so a refusal leaves the old deployer running.
stop_backout() {
    local consequence=""
    if [[ $installers_started == no ]]; then
        if sudo systemctl start "$TIMER"; then
            consequence="; nothing changed, the timer is running again"
        else
            consequence="; nothing changed, but the timer could not be restarted (run: sudo systemctl start $TIMER)"
        fi
    fi
    printf 'stopped at %s: %s%s\n' "$step_label" "$1" "$consequence" >&2
    printf 'the later backout steps were not run; tell the head\n' >&2
    exit 1
}

announce_sudo() {
    printf 'sudo is used only for systemctl on %s and for the installers in scripts/; it asks for a password itself.\n' "$TIMER"
    printf 'The running containers are not touched, and .env contents are never read or printed.\n'
}

switch() {
    local tag=$1 answer
    git ls-remote --exit-code --tags "$REPOSITORY_URL" "refs/tags/$tag" >/dev/null ||
        { printf 'not a tag of %s: %s\n' "$REPOSITORY_URL" "$tag" >&2; exit 2; }
    announce_sudo

    begin "step 1" "stop the autodeploy timer"
    sudo systemctl stop "$TIMER" || stop_switch "the timer did not stop"

    begin "step 2" "wait until no tick holds the deploy lock"
    flock "$WORK_CLONE/.git/songmaker-autodeploy.lock" true || stop_switch "the deploy lock could not be taken"
    local service_state
    service_state=$(systemctl is-active songmaker-autodeploy.service)
    [[ $service_state == inactive || $service_state == failed ]] ||
        stop_switch "songmaker-autodeploy.service is $service_state"

    begin "step 3" "create ~/srv"
    mkdir -p "$HOME/srv" || stop_switch "~/srv could not be created"

    begin "step 4" "check that ~/srv is on the file system of ~/git/songmaker"
    local devices
    devices=$(stat -c %d "$WORK_CLONE" "$HOME/srv") || stop_switch "stat failed"
    [[ $(sort -u <<<"$devices" | wc -l) -eq 1 ]] || stop_switch "~/srv is on another file system"

    begin "step 5" "clone the repository to ~/srv/songmaker"
    git clone "$REPOSITORY_URL" "$RELEASE_CLONE" || stop_switch "the clone failed"

    begin "step 6" "check out $tag detached"
    git -C "$RELEASE_CLONE" checkout --detach "refs/tags/$tag" || stop_switch "$tag could not be checked out"

    begin "step 7" "initialise vendor/acestep"
    git -C "$RELEASE_CLONE" submodule update --init vendor/acestep || stop_switch "the submodule update failed"

    begin "step 8" "copy .env with its mode"
    cp -p "$WORK_CLONE/.env" "$RELEASE_CLONE/.env" || stop_switch ".env could not be copied"

    begin "step 9" "hard-link the ACE-Step checkpoints"
    cp -al "$WORK_CLONE/vendor/acestep/checkpoints" "$RELEASE_CLONE/vendor/acestep/" || stop_switch "the checkpoints could not be linked"

    begin "step 10" "check that the compose project is named songmaker"
    local project_name
    project_name=$(cd "$RELEASE_CLONE" && compose_project_name) || stop_switch "docker compose config failed"
    [[ $project_name == songmaker ]] || stop_switch "the compose project is named '$project_name', not songmaker"

    begin "step 11" "install the agent-CLI login mirror"
    (cd "$RELEASE_CLONE" && sudo ./scripts/install-cli-credentials-mirror.sh --force) || stop_switch "install-cli-credentials-mirror.sh failed"

    begin "step 12" "install the boot autostart unit"
    (cd "$RELEASE_CLONE" && sudo ./scripts/install-autostart.sh --force) || stop_switch "install-autostart.sh failed"

    begin "step 13" "install the autodeploy timer (starts it again)"
    (cd "$RELEASE_CLONE" && sudo ./scripts/install-autodeploy.sh) || stop_switch "install-autodeploy.sh failed"

    begin "step 14" "check that every unit names $RELEASE_CLONE"
    units_name_only "$RELEASE_CLONE" "$WORK_CLONE" || stop_switch "a unit does not name $RELEASE_CLONE"

    begin "step 15" "wait 2 minutes for the first tick, then read the journal"
    sleep 120
    local tag_commit
    tag_commit=$(git -C "$RELEASE_CLONE" rev-parse HEAD) || stop_switch "the release commit could not be read"
    journalctl -t songmaker-autodeploy -n 5 --no-pager | grep -F "adopted running state $tag_commit" ||
        stop_switch "the journal does not say 'adopted running state $tag_commit'"

    begin "step 16" "delete the old $WORK_CLONE/.env after cmp (needs your confirmation)"
    read -r -p "Delete $WORK_CLONE/.env now? Type yes to confirm: " answer
    if [[ ${answer:-} != yes ]]; then
        printf 'not confirmed: the old %s/.env stays. The backout still works; delete it yourself once you are sure.\n' "$WORK_CLONE"
        return 0
    fi
    cmp -s "$WORK_CLONE/.env" "$RELEASE_CLONE/.env" || stop_with "the two .env files differ; the old one stays"
    rm "$WORK_CLONE/.env" || stop_with "the old .env could not be deleted"
    printf 'switched to %s.\n' "$tag"
}

backout() {
    announce_sudo

    begin "backout B1" "stop the autodeploy timer"
    sudo systemctl stop "$TIMER" || stop_backout "the timer did not stop"

    begin "backout B2" "wait until no tick from ~/srv holds its lock"
    if [[ -d $RELEASE_CLONE/.git ]]; then
        flock "$RELEASE_CLONE/.git/songmaker-autodeploy.lock" true || stop_backout "the lock could not be taken"
    fi

    # Before any unit changes: once a release deployed from the release clone, a refusal must leave the units alone.
    begin "backout B7b" "check that no release deployed from $RELEASE_CLONE"
    local config_files
    config_files=$(compose_config_files) || stop_backout "docker compose ls failed"
    if [[ $config_files == *"$RELEASE_CLONE"* ]]; then
        stop_backout "a release already deployed from $RELEASE_CLONE; ~/srv is not removed, there is no way back, cut a newer tag"
    fi
    [[ $config_files == "$WORK_CLONE/docker-compose.yml" ]] ||
        stop_backout "the songmaker project's compose file is '$config_files', not $WORK_CLONE/docker-compose.yml"

    begin "backout B3" "check that the old .env is still there"
    [[ -f $WORK_CLONE/.env ]] || stop_backout "$WORK_CLONE/.env is gone; there is no way back, cut a newer tag"

    installers_started=yes
    begin "backout B4" "reinstall the agent-CLI login mirror from the work clone"
    (cd "$WORK_CLONE" && sudo ./scripts/install-cli-credentials-mirror.sh --force) || stop_backout "install-cli-credentials-mirror.sh failed"

    begin "backout B5" "reinstall the boot autostart unit from the work clone"
    (cd "$WORK_CLONE" && sudo ./scripts/install-autostart.sh --force) || stop_backout "install-autostart.sh failed"

    begin "backout B6" "reinstall the autodeploy timer from the work clone"
    (cd "$WORK_CLONE" && sudo ./scripts/install-autodeploy.sh) || stop_backout "install-autodeploy.sh failed"

    begin "backout B7" "check that every unit names $WORK_CLONE"
    units_name_only "$WORK_CLONE" "$RELEASE_CLONE" || stop_backout "a unit does not name $WORK_CLONE"

    begin "backout B8" "remove the release clone $RELEASE_CLONE"
    rm -rf "$RELEASE_CLONE" || stop_backout "$RELEASE_CLONE could not be removed"
    printf 'backed out: the timer runs from %s again.\n' "$WORK_CLONE"
}

[[ $EUID -ne 0 ]] || { echo "run as yourself, not as root: the installers use SUDO_USER" >&2; exit 2; }
case "${1:-}" in
    --backout) [[ $# -eq 1 ]] || { echo "usage: $0 <tag> | --backout" >&2; exit 2; }; backout ;;
    "" | -*) echo "usage: $0 <tag> | --backout" >&2; exit 2 ;;
    *) [[ $# -eq 1 ]] || { echo "usage: $0 <tag> | --backout" >&2; exit 2; }; switch "$1" ;;
esac

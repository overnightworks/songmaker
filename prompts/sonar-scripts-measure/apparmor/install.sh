#!/usr/bin/env bash
# Installs an AppArmor profile from this directory persistently and loads it.
#
# songmaker-web refuses to start without its profile in the kernel. A profile
# loaded only into the running kernel is gone after a reboot, so the copy goes
# under /etc/apparmor.d/, where apparmor.service loads it at every boot before
# docker.service starts anything. Run this once per profile change, as root.
#
# The boot-loaded pathname only ever holds a complete profile that parsed: the
# profile is copied to a dotfile beside it, those staged bytes are validated
# and must declare the requested profile and no other, and a rename puts them
# in place. apparmor_parser skips dotfiles when it loads
# a directory, so a staged copy never reaches the boot load. If the kernel does
# not load or report the new copy, the previous one goes back. The copy is made
# without preserving timestamps, so its fresh mtime invalidates any cached
# compilation of an older version. Running the script twice leaves the same
# file and the same loaded profile.
set -euo pipefail

readonly profile_name="${1:-songmaker-web}"
readonly script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly profile_path="${script_dir}/${profile_name}"
readonly installed_dir="${SONGMAKER_APPARMOR_DIR:-/etc/apparmor.d}"
readonly installed_path="${installed_dir}/${profile_name}"
staged_path=""
previous_copy_path=""

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

remove_staged_files() {
  local path
  for path in "${staged_path}" "${previous_copy_path}"; do
    [[ -z "${path}" ]] || rm -f -- "${path}"
  done
}

# A symlink beside the script could point anywhere on the host, so only a
# regular file that canonically lives in this directory names a profile.
is_profile_beside_script() {
  [[ "${profile_name}" != */* && -f "${profile_path}" && ! -L "${profile_path}" ]] \
    && [[ ! "${profile_path}" -ef "${BASH_SOURCE[0]}" ]] \
    && [[ "$(realpath -e -- "${profile_path}")" == "${profile_path}" ]]
}

stage_in_installed_dir() {
  mktemp "${installed_dir}/.${profile_name}.XXXXXX"
}

stage_profile() {
  staged_path="$(stage_in_installed_dir)" \
    || fail "Could not stage the ${profile_name} profile in ${installed_dir}."
  cp -- "${profile_path}" "${staged_path}" \
    || fail "Could not copy the ${profile_name} profile into ${installed_dir}."
  chmod 0644 "${staged_path}"
}

keep_previous_copy() {
  [[ -e "${installed_path}" ]] || return 0
  previous_copy_path="$(stage_in_installed_dir)"
  cp -p -- "${installed_path}" "${previous_copy_path}"
}

# A file that declares another profile, or one more, would load that under
# its own name while an older requested profile stays loaded and still answers
# aa-status; at the next boot only what the file declares would come up.
refuse_unless_only_the_requested_profile_is_declared() {
  local declared_profiles
  declared_profiles="$(apparmor_parser -QK -N "${staged_path}")" \
    || fail "The ${profile_name} profile does not parse; nothing was installed."
  if [[ "${declared_profiles}" != "${profile_name}" ]]; then
    fail "${profile_path} must declare the ${profile_name} profile and nothing else; it declares: ${declared_profiles//$'\n'/ }. Nothing was installed."
  fi
}

# Every whole line is one record; a profile is listed alone on its line, a
# process with its pid and profile, so a name that merely contains the
# requested one never counts.
kernel_reports_profile() {
  aa-status | wanted="${profile_name}" awk '
    NF == 1 && $1 == ENVIRON["wanted"] { found = 1 }
    END { exit !found }
  '
}

restore_previous_copy() {
  if [[ -z "${previous_copy_path}" ]]; then
    rm -f -- "${installed_path}"
    printf 'Removed %s again; there was no copy before.\n' "${installed_path}" >&2
    return
  fi
  if ! mv -f -- "${previous_copy_path}" "${installed_path}"; then
    printf 'Could not put the previous copy back; it is kept as %s.\n' "${previous_copy_path}" >&2
    previous_copy_path=""
    return
  fi
  previous_copy_path=""
  if apparmor_parser -r "${installed_path}"; then
    printf 'Put the previous %s back and reloaded it.\n' "${installed_path}" >&2
  else
    printf 'Put the previous %s back, but the kernel did not reload it either.\n' "${installed_path}" >&2
  fi
}

if ! is_profile_beside_script; then
  fail "${profile_name} is not the name of a profile file next to this script."
fi

if [[ "$(id -u)" != 0 ]]; then
  fail 'Run this script as root: installing an AppArmor profile changes the host kernel policy.'
fi

if ! command -v apparmor_parser >/dev/null; then
  fail 'apparmor_parser is required to load the AppArmor profile.'
fi

if ! command -v aa-status >/dev/null; then
  fail 'aa-status is required to confirm that AppArmor is enabled.'
fi

if ! aa-status --enabled; then
  fail 'AppArmor is not enabled; refusing to load the profile.'
fi

trap remove_staged_files EXIT
stage_profile

if ! apparmor_parser -QK "${staged_path}"; then
  fail "The ${profile_name} profile does not parse; nothing was installed."
fi
refuse_unless_only_the_requested_profile_is_declared

keep_previous_copy
mv -f -- "${staged_path}" "${installed_path}"

if ! apparmor_parser -r "${installed_path}"; then
  restore_previous_copy
  fail "The kernel did not load ${installed_path}."
fi

if ! kernel_reports_profile; then
  restore_previous_copy
  fail "AppArmor did not report the ${profile_name} profile after loading it."
fi

printf 'Installed AppArmor profile %s as %s and loaded it; it loads again at every boot. Next: docker compose up -d songmaker-web\n' "${profile_name}" "${installed_path}"

#!/usr/bin/env bash
# Installs an AppArmor profile from this directory persistently and loads it.
#
# songmaker-web refuses to start without its profile in the kernel. A profile
# loaded only into the running kernel is gone after a reboot, so the copy goes
# under /etc/apparmor.d/, where apparmor.service loads it at every boot before
# docker.service starts anything. Run this once per profile change, as root.
#
# A profile that does not parse is never written there: a broken copy would be
# loaded at the next boot. The copy is made without preserving timestamps, so
# its fresh mtime invalidates any cached compilation of an older version.
# Running the script twice leaves the same file and the same loaded profile.
set -euo pipefail

readonly profile_name="${1:-songmaker-web}"
readonly script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly profile_path="${script_dir}/${profile_name}"
readonly installed_dir="${SONGMAKER_APPARMOR_DIR:-/etc/apparmor.d}"
readonly installed_path="${installed_dir}/${profile_name}"

if [[ "${profile_name}" == */* || ! -f "${profile_path}" || "${profile_path}" -ef "${BASH_SOURCE[0]}" ]]; then
  printf '%s is not the name of a profile file next to this script.\n' "${profile_name}" >&2
  exit 1
fi

if [[ "$(id -u)" != 0 ]]; then
  printf '%s\n' 'Run this script as root: installing an AppArmor profile changes the host kernel policy.' >&2
  exit 1
fi

if ! command -v apparmor_parser >/dev/null; then
  printf '%s\n' 'apparmor_parser is required to load the AppArmor profile.' >&2
  exit 1
fi

if ! command -v aa-status >/dev/null; then
  printf '%s\n' 'aa-status is required to confirm that AppArmor is enabled.' >&2
  exit 1
fi

if ! aa-status --enabled; then
  printf '%s\n' 'AppArmor is not enabled; refusing to load the profile.' >&2
  exit 1
fi

if ! apparmor_parser -QK "${profile_path}"; then
  printf 'The %s profile does not parse; nothing was installed.\n' "${profile_name}" >&2
  exit 1
fi

if ! install -m 0644 "${profile_path}" "${installed_path}"; then
  printf 'Could not install the %s profile as %s.\n' "${profile_name}" "${installed_path}" >&2
  exit 1
fi

if ! apparmor_parser -r "${installed_path}"; then
  printf 'Installed %s, but the kernel did not load it.\n' "${installed_path}" >&2
  exit 1
fi

if ! aa-status | grep --fixed-strings --quiet "${profile_name}"; then
  printf 'AppArmor did not report the %s profile after loading it.\n' "${profile_name}" >&2
  exit 1
fi

printf 'Installed AppArmor profile %s as %s and loaded it; it loads again at every boot. Next: docker compose up -d songmaker-web\n' "${profile_name}" "${installed_path}"

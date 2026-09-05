#!/usr/bin/env bash
set -euo pipefail

readonly profile_name='songmaker-web'
readonly script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly profile_path="${script_dir}/${profile_name}"

if (( EUID != 0 )); then
  printf '%s\n' 'Run this script as root: loading an AppArmor profile changes the host kernel policy.' >&2
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

apparmor_parser -r "${profile_path}"

if ! aa-status | grep --fixed-strings --quiet "${profile_name}"; then
  printf 'AppArmor did not report the %s profile after loading it.\n' "${profile_name}" >&2
  exit 1
fi

printf 'Loaded AppArmor profile %s. Run this before rollout: songmaker-web will not start without it. Next: docker compose up -d songmaker-web\n' "${profile_name}"

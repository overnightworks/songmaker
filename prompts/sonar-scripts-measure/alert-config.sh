#!/bin/bash
# The one place that knows which .env keys configure the alert channel
# (issue #333), sourced by both users of that answer: scripts/alert.sh,
# which needs the values to send, and scripts/auto-deploy.sh, which only
# needs to know whether a deploy is even possible before it starts
# containers whose alertmanager refuses to run without them.
#
# Not executable on its own — `source` it, then call load_alert_config.

# .env is this project's own trusted, operator-owned config file (the same
# one Pydantic Settings loads for the app itself), so it is sourced rather
# than hand-parsed: a hand-rolled parser would mishandle a quoted value
# differently than the app does. It is deliberately sourced WITHOUT
# `set -a`: the values stay variables of the calling shell instead of
# becoming environment, so no child process the caller starts afterwards
# (curl, git, docker) inherits the whole .env — least privilege for a file
# that holds every secret this project has.
ALERT_CONFIG_KEYS=(ALERT_EMAIL_TO SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD)

load_alert_config() {
    local env_file="$1"

    if [[ ! -f "$env_file" ]]; then
        echo "no .env at $env_file — the alert channel has no configuration" >&2
        return 1
    fi

    # shellcheck source=/dev/null
    source "$env_file"

    local missing=()
    local key
    for key in "${ALERT_CONFIG_KEYS[@]}"; do
        if [[ -z "${!key:-}" ]]; then
            missing+=("$key")
        fi
    done

    if ((${#missing[@]} > 0)); then
        echo "missing ${missing[*]} in $env_file" >&2
        return 1
    fi
}

# One line of a curl config file (`curl --config <file>`) carrying the SMTP
# credentials. This exists so the password never travels in argv, where
# `ps` and /proc expose it to every user on the host for the duration of
# the send — see how scripts/alert.sh feeds the result to curl on a file
# descriptor.
#
# curl's config parser treats a double-quoted value as escaped text: \\ is
# a backslash and \" a quote. Those two characters therefore have to be
# escaped, and no others — every remaining character a generated app
# password routinely contains (&, |, #, spaces) is carried literally.
_escape_curl_config_value() {
    local value="${1//\\/\\\\}"
    printf '%s' "${value//\"/\\\"}"
}

curl_credentials_config() {
    local user="$1"
    local password="$2"
    printf 'user = "%s:%s"\n' \
        "$(_escape_curl_config_value "$user")" \
        "$(_escape_curl_config_value "$password")"
}

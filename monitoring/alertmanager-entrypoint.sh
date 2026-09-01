#!/bin/sh
# Entrypoint of the alertmanager container (issue #333), replacing the
# image's own /bin/alertmanager ENTRYPOINT so the config can be assembled
# first. Runs on the image's busybox /bin/sh: no bash, no envsubst, no
# python — sed is the substitution tool that exists here.
#
# Alertmanager's config format has no ${VAR} substitution of its own, so
# the four non-secret values of the one alert channel are substituted into
# monitoring/alertmanager.yml.template at container start. The fifth,
# SMTP_PASSWORD, deliberately never passes through this script: Docker
# mounts it as a secret file and Alertmanager reads that file itself via
# smtp_auth_password_file (see the template), so the password is in no
# process argument, no `docker inspect` output, and no generated config.
#
# The three paths below default to what the compose service mounts; the
# overrides exist so this exact script can be driven outside the image —
# by a test, or by an operator checking what their .env renders to —
# rather than a second copy of the substitution being written for that
# purpose. Same reasoning as the SONGMAKER_AUTODEPLOY_* state-path
# overrides in scripts/auto-deploy.sh.

set -eu

CONFIG_TEMPLATE="${ALERTMANAGER_CONFIG_TEMPLATE:-/etc/alertmanager/alertmanager.yml.template}"
GENERATED_CONFIG="${ALERTMANAGER_GENERATED_CONFIG:-/tmp/alertmanager.yml}"
SMTP_PASSWORD_FILE="${ALERTMANAGER_SMTP_PASSWORD_FILE:-/run/secrets/smtp_password}"

if [ ! -s "$SMTP_PASSWORD_FILE" ]; then
    echo "alertmanager: $SMTP_PASSWORD_FILE is missing or empty (SMTP_PASSWORD unset in .env) -- refusing to start with an incomplete SMTP config" >&2
    exit 1
fi

NEWLINE='
'
CARRIAGE_RETURN="$(printf '\r')"

MISSING=""
for NAME in ALERT_EMAIL_TO SMTP_HOST SMTP_PORT SMTP_USER; do
    eval "VALUE=\${$NAME:-}"
    if [ -z "$VALUE" ]; then
        MISSING="$MISSING $NAME"
        continue
    fi
    # A single-quoted YAML scalar written on one line cannot carry a line
    # break at all, so there is no substitution that would mean what the
    # operator wrote. Refuse by name instead of silently writing a config
    # that says something else.
    case "$VALUE" in
        *"$NEWLINE"* | *"$CARRIAGE_RETURN"*)
            echo "alertmanager: $NAME contains a line break -- refusing to build a config from it" >&2
            exit 1
            ;;
    esac
done
if [ -n "$MISSING" ]; then
    echo "alertmanager: missing$MISSING in .env -- refusing to start with an incomplete SMTP config" >&2
    exit 1
fi

# Each value crosses two languages on its way into the config, so both
# escapes apply, innermost first.
#
# YAML: the template puts every value inside a single-quoted scalar, where
# the only escape that exists is a doubled apostrophe. Without it a
# perfectly ordinary address like o'connor@example.com closes the scalar
# early and Alertmanager refuses to load the file.
#
# sed: the result is then substitution text, where an unescaped `&` stands
# for the whole match, `\` starts an escape, and `|` would close the
# s|…|…| expression early.
escape_yaml_value_for_sed() {
    printf '%s' "$1" | sed -e "s/'/''/g" -e 's/[\\&|]/\\&/g'
}

sed \
    -e "s|__SMTP_HOST__|$(escape_yaml_value_for_sed "$SMTP_HOST")|g" \
    -e "s|__SMTP_PORT__|$(escape_yaml_value_for_sed "$SMTP_PORT")|g" \
    -e "s|__SMTP_USER__|$(escape_yaml_value_for_sed "$SMTP_USER")|g" \
    -e "s|__ALERT_EMAIL_TO__|$(escape_yaml_value_for_sed "$ALERT_EMAIL_TO")|g" \
    "$CONFIG_TEMPLATE" >"$GENERATED_CONFIG"

# Alertmanager's own parser, run before the daemon rather than by it: a
# config it cannot read otherwise turns into a container that restarts
# forever with the reason buried in the loop. amtool ships in this image
# and reads exactly the same schema the daemon does, so what passes here
# starts. It prints no secret — the password lives in the file the config
# only points at.
if ! CHECK_OUTPUT="$(amtool check-config "$GENERATED_CONFIG" 2>&1)"; then
    echo "alertmanager: the config built from .env is not valid -- $CHECK_OUTPUT" >&2
    exit 1
fi

exec alertmanager --config.file="$GENERATED_CONFIG" --storage.path=/alertmanager

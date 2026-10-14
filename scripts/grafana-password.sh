#!/bin/bash
# scripts/grafana-password.sh — gives Grafana a strong admin password the
# operator never has to know (issue #1359).
#
# Usage, once, from the main checkout with the stack running:
#   ./scripts/grafana-password.sh
#
# 1. If .env has no GRAFANA_PASSWORD, an empty one, or a publicly known one
#    (`admin`, anything starting with `CHANGEME`), a fresh `openssl rand -hex
#    32` replaces that line in place (or is appended). Every other line stays
#    byte-identical; .env keeps its owner and mode.
# 2. Either way the .env value is applied to the running Grafana through
#    `grafana cli admin reset-admin-password --password-from-stdin`, so the
#    real admin password is the .env one even when Grafana's database was
#    created with admin/admin.
# 3. Only after that apply succeeded does it print `set` (step 1 wrote a fresh
#    value) or `already set` (step 1 kept the existing one). If the apply
#    fails it exits non-zero and says whether .env was already updated; the
#    fix is to start the stack and run this again — the second run finds the
#    value and only applies it.
#
# The value never reaches any argv, stdout, stderr or error message: it only
# travels through bash variables, the builtin printf, and pipes. .env is read
# as data, never sourced. It understands the subset of Compose's dotenv this
# key needs (unquoted, single- or double-quoted, optional `export`, a
# whitespace-led trailing `# comment`) and refuses, by key name, anything that
# would need escapes or interpolation instead of guessing differently from
# Compose.
#
# SONGMAKER_GRAFANA_ENV_FILE overrides the .env path (tests only).

set -euo pipefail

readonly KEY=GRAFANA_PASSWORD
readonly KEY_LINE_PATTERN="^[[:space:]]*(export[[:space:]]+)?${KEY}[[:space:]]*[=:](.*)$"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${SONGMAKER_GRAFANA_ENV_FILE:-$REPO_ROOT/.env}"
TEMP_FILE=""

remove_temp_file() {
    if [[ -n "$TEMP_FILE" ]]; then
        rm -f -- "$TEMP_FILE"
    fi
}
trap remove_temp_file EXIT

fail() {
    echo "grafana-password: $*" >&2
    exit 1
}

# The line number of the key's effective (last) assignment, or nothing.
key_line_number() {
    grep -nE "$KEY_LINE_PATTERN" "$ENV_FILE" | tail -n 1 | cut -d: -f1 || true
}

trim() {
    local text="$1"
    text="${text#"${text%%[![:space:]]*}"}"
    printf '%s' "${text%"${text##*[![:space:]]}"}"
}

# The value Compose would hand to Grafana for the raw text after `KEY=`.
dotenv_value() {
    local raw quote inner trailing
    raw="$(trim "$1")"
    quote="${raw:0:1}"
    if [[ "$quote" == "'" || "$quote" == '"' ]]; then
        inner="${raw:1}"
        [[ "$inner" == *"$quote"* ]] || fail "$KEY in $ENV_FILE has an unclosed quote"
        trailing="$(trim "${inner#*"$quote"}")"
        inner="${inner%%"$quote"*}"
        [[ -z "$trailing" || "$trailing" == "#"* ]] \
            || fail "$KEY in $ENV_FILE has text after its closing quote"
        if [[ "$quote" == '"' && "$inner" == *[\\\$]* ]]; then
            fail "$KEY in $ENV_FILE uses an escape or interpolation; write it without \\ or \$"
        fi
        printf '%s' "$inner"
        return
    fi
    if [[ "$raw" =~ [[:space:]]# ]]; then
        raw="${raw%%"${BASH_REMATCH[0]}"*}"
    fi
    [[ "$raw" != *'$'* ]] || fail "$KEY in $ENV_FILE uses interpolation; write it without \$"
    trim "$raw"
}

current_value() {
    local line_number="$1" line
    [[ -n "$line_number" ]] || return 0
    line="$(sed -n "${line_number}p" "$ENV_FILE")"
    [[ "$line" =~ $KEY_LINE_PATTERN ]]
    dotenv_value "${BASH_REMATCH[2]}"
}

is_publicly_known() {
    local value="$1"
    [[ -z "$value" || "$value" == "admin" || "$value" == CHANGEME* ]]
}

ends_without_newline() {
    [[ -s "$1" && -n "$(tail -c 1 "$1")" ]]
}

# Writes .env with the key's line replaced (or appended) via a same-directory
# temp file that already carries .env's owner and mode, then renames it over
# .env, so a reader sees either the old file or the new one, never half.
write_value() {
    local value="$1" line_number="$2"
    TEMP_FILE="$(mktemp "$(dirname "$ENV_FILE")/.env.grafana-password.XXXXXX")"
    {
        if [[ -n "$line_number" ]]; then
            head -n "$((line_number - 1))" "$ENV_FILE"
            printf '%s=%s\n' "$KEY" "$value"
            tail -n "+$((line_number + 1))" "$ENV_FILE"
        else
            cat "$ENV_FILE"
            if ends_without_newline "$ENV_FILE"; then
                printf '\n'
            fi
            printf '%s=%s\n' "$KEY" "$value"
        fi
    } > "$TEMP_FILE"
    chown --reference="$ENV_FILE" "$TEMP_FILE"
    chmod --reference="$ENV_FILE" "$TEMP_FILE"
    mv -f -- "$TEMP_FILE" "$ENV_FILE"
}

# Grafana's reply stays hidden on success; on failure it is shown with the
# value redacted, in case anything in the chain ever echoes its input.
apply_to_grafana() {
    local value="$1" env_status="$2" reply
    if reply="$(printf '%s\n' "$value" | (cd "$REPO_ROOT" \
            && docker compose exec -T grafana \
                grafana cli admin reset-admin-password --password-from-stdin) 2>&1)"; then
        return 0
    fi
    printf '%s\n' "${reply//"$value"/<redacted>}" >&2
    fail "applying $KEY to the running Grafana failed ($env_status);" \
        "start the stack (docker compose up -d) and run this command again"
}

main() {
    [[ $# -eq 0 ]] || fail "takes no arguments; usage: scripts/grafana-password.sh"
    [[ -f "$ENV_FILE" ]] || fail "no .env at $ENV_FILE"

    local line_number value outcome env_status
    line_number="$(key_line_number)"
    value="$(current_value "$line_number")"

    if is_publicly_known "$value"; then
        value="$(openssl rand -hex 32)"
        [[ "$value" =~ ^[0-9a-f]{64}$ ]] || fail "openssl rand -hex 32 did not yield 64 hex digits"
        write_value "$value" "$line_number"
        outcome="set"
        env_status=".env already holds the fresh $KEY"
    else
        outcome="already set"
        env_status=".env was not changed"
    fi

    apply_to_grafana "$value" "$env_status"
    echo "$outcome"
}

main "$@"

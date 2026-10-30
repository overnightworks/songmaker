#!/bin/bash
# scripts/alert.sh — the one channel every host-level alert source (issue
# #333) uses to reach the operator: a single email. Prometheus alerts go
# through Alertmanager's own SMTP client instead (monitoring/
# alertmanager.yml.template — same .env account, same inbox, see its
# comment for why); this script is for systemd's OnFailure= path, where
# there is no such engine and a plain synchronous send is all one failed
# unit needs.
#
# Usage: scripts/alert.sh "<subject>" "<body>"
#
# Configuration comes exclusively from .env at the project root (resolved
# from this script's own location, same SCRIPT_DIR/REPO_ROOT pattern as
# auto-deploy.sh — running a copy from a worktree reads that worktree's
# own .env), loaded and validated by scripts/alert-config.sh, which owns
# the list of the five keys. Missing or empty configuration exits non-zero
# with a named reason on stderr instead of silently skipping the send —
# this script never reports success unless curl itself reported success.
#
# curl's built-in SMTP client (--ssl-reqd smtp://...) sends the mail
# without installing sendmail/msmtp/ssmtp: curl already ships on this host
# (verified: `curl --version` lists smtp/smtps among its protocols) and is
# already a project dependency elsewhere, so this avoids adding a second
# mail-transport package to keep patched for a single outbound message a
# few times a month. SMTP_HOST/SMTP_PORT are expected to be a STARTTLS
# endpoint (Gmail's documented app-password setup: smtp.gmail.com:587,
# which is what --ssl-reqd upgrades to TLS on connect) — an implicit-TLS
# endpoint (port 465) would need smtps:// instead, not needed here.

set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "usage: $(basename "$0") <subject> <body>" >&2
    exit 1
fi

SUBJECT="$1"
BODY="$2"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${SONGMAKER_ALERT_ENV_FILE:-$REPO_ROOT/.env}"

# shellcheck source=scripts/alert-config.sh
source "$SCRIPT_DIR/alert-config.sh"

if ! load_alert_config "$ENV_FILE"; then
    echo "alert.sh: refusing to pretend this sent" >&2
    exit 1
fi

MESSAGE="Subject: ${SUBJECT}
From: ${SMTP_USER}
To: ${ALERT_EMAIL_TO}

${BODY}
"

# The credentials reach curl through a named pipe as its --config file
# instead of as a --user argument: anything in argv is world-readable in `ps`
# and /proc for as long as the send lasts (argv only carries the pipe's
# path). They are built first, in a variable of this shell that is never
# exported, so a failing producer stops the send here instead of running on
# in the background where nothing checks its status. A background job then
# only writes that variable into the pipe: a pipe keeps no data on this
# host's disk, in a directory only this user can enter, and no other process
# gets the credentials in its arguments or its environment (see
# curl_credentials_config for the quoting rule curl applies to what it reads
# there).
CURL_CREDENTIALS="$(curl_credentials_config "$SMTP_USER" "$SMTP_PASSWORD")" || {
    echo "alert.sh: could not build the SMTP credentials; refusing to pretend this sent" >&2
    exit 1
}

CREDENTIAL_PIPE_DIR="$(mktemp -d)"
trap 'rm -rf "$CREDENTIAL_PIPE_DIR"' EXIT
CREDENTIAL_PIPE="$CREDENTIAL_PIPE_DIR/curl-config"
mkfifo "$CREDENTIAL_PIPE"

# The writer is an ordinary job of this shell, so a plain `wait` on its pid
# gives its status; a process substitution's pid has no such guarantee. The
# writer's open blocks until a reader appears, and a curl that failed before
# reading the pipe never appears: opening it once read-write here releases
# that writer, and closing it again leaves the writer no reader, so its write
# fails instead of hanging.
printf '%s' "$CURL_CREDENTIALS" >"$CREDENTIAL_PIPE" &
CREDENTIAL_WRITER_PID=$!

CURL_STATUS=0
CURL_OUTPUT="$(curl --silent --show-error --fail \
    --ssl-reqd \
    --url "smtp://${SMTP_HOST}:${SMTP_PORT}" \
    --mail-from "$SMTP_USER" \
    --mail-rcpt "$ALERT_EMAIL_TO" \
    --config "$CREDENTIAL_PIPE" \
    --upload-file - <<<"$MESSAGE" 2>&1)" || CURL_STATUS=$?

exec 3<>"$CREDENTIAL_PIPE" 3<&-
WRITER_STATUS=0
wait "$CREDENTIAL_WRITER_PID" || WRITER_STATUS=$?

# A write that failed (curl closed the pipe first) does not count as sent.
if ((CURL_STATUS != 0 || WRITER_STATUS != 0)); then
    # Defense in depth: curl does not echo back credentials on a protocol
    # error, but scrub the password from whatever it did print before this
    # line reaches the journal, in case a future curl version ever changes
    # what an error message includes.
    CURL_OUTPUT="${CURL_OUTPUT//"$SMTP_PASSWORD"/[REDACTED]}"
    echo "alert.sh: SMTP send to $SMTP_HOST:$SMTP_PORT failed (curl exit $CURL_STATUS, credential write exit $WRITER_STATUS): $CURL_OUTPUT" >&2
    exit 1
fi

echo "alert.sh: sent \"$SUBJECT\" to $ALERT_EMAIL_TO"

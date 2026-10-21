"""Signs e2e accounts in without the password form.

Runs inside the web container, where the app's settings and database are
mounted. The script itself arrives on stdin and the request as JSON in the
``SEED_SESSIONS_REQUEST`` environment variable:

    docker compose exec -T -e SEED_SESSIONS_REQUEST='{"seed": [{"username": "e2e-x"}]}' \
        songmaker-web /app/.venv/bin/python - < seed_sessions.py

A request holds ``seed`` (entries ``username`` and optional ``role`` and ``password``).

``seed`` finds or creates each account and opens a database session for it,
printing the signed session cookie and CSRF cookie the app itself would have
issued at login. The helper never ships: it lives outside ``scripts/``, which the image copies.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone

from webauth.cookies import (
    DEFAULT_COOKIE_SAMESITE,
    PLAIN_CSRF_COOKIE_NAME,
    PLAIN_SESSION_COOKIE_NAME,
    default_cookie_name,
    generate_csrf_token,
    sign_session_id,
)

from songmaker_cli.app_context import build_password_hasher
from songmaker_cli.db.engine import connect_db, resolve_database_url
from songmaker_cli.db.queries.auth import (
    create_session,
    create_user,
    get_user_by_username,
)
from songmaker_cli.settings import get_settings

REQUEST_ENVIRONMENT_VARIABLE = "SEED_SESSIONS_REQUEST"


def _seed(session, entry: dict[str, str]) -> dict[str, str]:
    settings = get_settings()
    signing_key = settings.session_secret.get_secret_value().encode()
    user = get_user_by_username(session, entry["username"])
    if user is None and entry.get("role") == "admin":
        raise SystemExit(f"Admin account {entry['username']!r} is missing; never created here.")
    if user is None:
        # Without a password nobody signs in with this hash: the account only ever
        # holds a seeded session.
        password = entry.get("password") or secrets.token_urlsafe(32)
        password_hash = build_password_hasher().hash(password)
        user = create_user(
            session,
            entry["username"],
            password_hash,
            entry.get("role", "user"),
        )
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.session_max_age_seconds)
    record = create_session(session, user.id, expires_at)
    secure = settings.cookie_secure
    return {
        "user_id": user.id,
        "username": user.username,
        "session_cookie_name": default_cookie_name(PLAIN_SESSION_COOKIE_NAME, secure=secure),
        "session_cookie_value": sign_session_id(record.id, signing_key),
        "csrf_cookie_name": default_cookie_name(PLAIN_CSRF_COOKIE_NAME, secure=secure),
        "csrf_cookie_value": generate_csrf_token(record.id, signing_key),
        "secure": secure,
        "same_site": DEFAULT_COOKIE_SAMESITE,
    }


def main() -> int:
    request = json.loads(os.environ[REQUEST_ENVIRONMENT_VARIABLE])
    with connect_db(resolve_database_url())() as session:
        seeded = [_seed(session, entry) for entry in request.get("seed", [])]
        session.commit()
    print(json.dumps(seeded))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Signs e2e accounts in without Keycloak.

Runs inside the web container, where the app's settings and database are
mounted. The script itself arrives on stdin and the request as JSON in the
``SEED_SESSIONS_REQUEST`` environment variable:

    docker compose exec -T -e SEED_SESSIONS_REQUEST='{"seed": [{"username": "e2e-x"}]}' \
        songmaker-web /app/.venv/bin/python - < seed_sessions.py

A request holds ``seed`` (entries ``username`` and optional ``role``) and
``delete`` (user ids).

``seed`` finds or creates each account and opens a database session for it,
printing the signed session cookie and CSRF cookie exactly as the app issues
them after a Keycloak login. The stack has no admin bootstrap, so this is the
only place an e2e admin account comes into being. ``delete`` removes accounts
made earlier, with their albums. The helper never ships: it lives outside
``scripts/``, which the image copies.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from pathlib import Path

from starlette.responses import Response
from webauth.config import WebAuthConfig
from webauth.cookies import issue_session_cookies

from songmaker_cli.app_context import AppContext, build_web_auth_config, parse_trusted_proxies
from songmaker_cli.auth_stores import DatabaseSessionRecordStore, DatabaseSubjectUserStore
from songmaker_cli.db.engine import connect_db, resolve_database_url
from songmaker_cli.db.queries.auth import (
    delete_user_sessions,
    get_user_by_username,
    hard_delete_user,
)
from songmaker_cli.redis_client import create_redis
from songmaker_cli.settings import get_settings

REQUEST_ENVIRONMENT_VARIABLE = "SEED_SESSIONS_REQUEST"
DEFAULT_ROLE = "user"
# Issuing cookies reads the signing key and the lifetime only.
UNUSED_DIRECTORY = Path("/nonexistent")


def _auth_config(session_factory) -> WebAuthConfig:
    settings = get_settings()
    context = AppContext(
        db=session_factory,
        audio_dir=UNUSED_DIRECTORY,
        data_dir=UNUSED_DIRECTORY,
        signing_key=settings.session_secret.get_secret_value().encode(),
        redis=create_redis(settings.redis_url),
        trusted_proxies=parse_trusted_proxies(settings),
    )
    return build_web_auth_config(context, settings)


def _issued_cookies(session_id: str, config: WebAuthConfig) -> SimpleCookie:
    response = Response()
    issue_session_cookies(response, session_id, config)
    cookies = SimpleCookie()
    for header in response.headers.getlist("set-cookie"):
        cookies.load(header)
    return cookies


def _seed(session, config: WebAuthConfig, entry: dict[str, str]) -> dict[str, str]:
    accounts = DatabaseSubjectUserStore(session)
    user = get_user_by_username(session, entry["username"]) or accounts.create_for_subject(
        str(uuid.uuid4()), entry["username"], entry.get("role", DEFAULT_ROLE),
    )
    now = datetime.now(timezone.utc).replace(microsecond=0)
    record = DatabaseSessionRecordStore(session).create(
        user.id,
        now=now,
        expires_at=now + timedelta(seconds=config.session_lifetime.idle_seconds),
    )
    cookies = _issued_cookies(record.id, config)
    return {
        "user_id": user.id,
        "username": user.username,
        "session_cookie_name": config.session_cookie_name,
        "session_cookie_value": cookies[config.session_cookie_name].value,
        "csrf_cookie_name": config.csrf_cookie_name,
        "csrf_cookie_value": cookies[config.csrf_cookie_name].value,
        "secure": config.cookie_secure,
        "same_site": config.cookie_samesite,
    }


def _delete(session, user_id: str) -> None:
    delete_user_sessions(session, user_id)
    # Audio files of the removed albums stay in the throwaway stack's volume.
    hard_delete_user(session, user_id)


def main() -> int:
    request = json.loads(os.environ[REQUEST_ENVIRONMENT_VARIABLE])
    session_factory = connect_db(resolve_database_url())
    config = _auth_config(session_factory)
    with session_factory() as session:
        seeded = [_seed(session, config, entry) for entry in request.get("seed", [])]
        for user_id in request.get("delete", []):
            _delete(session, user_id)
        session.commit()
    print(json.dumps(seeded))
    return 0


if __name__ == "__main__":
    sys.exit(main())

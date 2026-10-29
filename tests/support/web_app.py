"""The songmaker web app for tests: full app, bare router, their client, accounts and Redis."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Final

import fakeredis
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from webauth.ports import AuthenticatedUser

from songmaker_cli.app_context import AppContext

TEST_SECRET = b"a" * 64
TEST_ORIGIN: Final = "https://testserver"


def make_fake_redis() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


def web_client(app, **kwargs) -> TestClient:
    """Build a TestClient that reaches a songmaker web app over its real HTTPS origin.

    A request naming neither `Origin` nor `Sec-Fetch-Site` carries what a same-origin
    browser sends; one naming either goes out as written."""
    client = TestClient(app, base_url=TEST_ORIGIN, **kwargs)
    client.event_hooks = {"request": [_add_same_origin_fetch_metadata]}
    return client


def _add_same_origin_fetch_metadata(request: httpx.Request) -> None:
    if "origin" not in request.headers and "sec-fetch-site" not in request.headers:
        request.headers["Sec-Fetch-Site"] = "same-origin"


def install_app_context(app, ctx) -> None:
    """Give a bare test app what ``create_app`` installs on the real one.

    An app that serves any auth-protected or rate-limited route needs both the
    context and the ``WebAuthConfig`` built from it, or it fails loudly on the
    first request. The settings are read uncached, so a test that shapes its
    environment after building its app still gets its own values back from
    ``get_settings()``.
    """
    from webauth.config import install_web_auth_config

    from songmaker_cli.app_context import build_web_auth_config
    from songmaker_cli.settings import Settings

    app.state.ctx = ctx
    install_web_auth_config(app, build_web_auth_config(ctx, Settings()))



def make_router_ctx(
    tmp_path: Path,
    *,
    db: sessionmaker[Session] | None = None,
    seed_db: Callable[[Session], None] | None = None,
) -> AppContext:
    """Build a router context, preserving an existing DB and committing seed data."""
    from songmaker_cli.db.engine import init_test_db

    ctx = AppContext(
        db=db if db is not None else init_test_db(tmp_path / "test.db"),
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        signing_key=TEST_SECRET,
        redis=make_fake_redis(),
    )
    if seed_db is not None:
        with ctx.db() as session:
            seed_db(session)
            session.commit()
    return ctx


def make_router_app(ctx: AppContext, *, user: AuthenticatedUser | None = None) -> FastAPI:
    """Mount the API router on an existing context, without middleware or lifecycle.

    Without a user override, requests exercise real authentication.
    """
    from songmaker_cli.api import router
    from songmaker_cli.audio_paths import AudioPathRejectedError
    from songmaker_cli.auth_dependencies import get_current_user
    from songmaker_cli.server import audio_path_rejected_handler

    app = FastAPI()
    app.add_exception_handler(AudioPathRejectedError, audio_path_rejected_handler)
    install_app_context(app, ctx)
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    app.include_router(router)
    return app


def seed_user(
    session: Session, username: str, role: str = "user", *, user_id: str | None = None,
):
    """Add an account the way admission would: its id is the issuer's subject."""
    import uuid

    from songmaker_cli.db.queries.auth import create_user

    return create_user(session, user_id or str(uuid.uuid4()), username, role)


def make_test_app(
    tmp_path: Path,
    seed_db: Callable | None = None,
    index_html: str = "<html>Songmaker</html>",
    factory: sessionmaker[Session] | None = None,
) -> tuple:
    """Create a full test app with real middleware on ``factory`` or a fresh SQLite file.

    Returns (TestClient, sessionmaker) so callers can seed data or log in.
    ``seed_db`` receives a Session to add models before the app starts;
    ``index_html`` is the built page whose inline scripts the policy hashes.
    """
    from songmaker_cli.db.engine import init_test_db as init_db
    from songmaker_cli.server import create_app

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(exist_ok=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True, exist_ok=True)
    (sk_dir / "index.html").write_text(index_html)

    factory = factory or init_db(data_dir / "songmaker.db")
    with factory() as session:
        if seed_db is not None:
            seed_db(session)
        session.commit()

    redis = make_fake_redis()
    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=data_dir,
        signing_key=TEST_SECRET, redis=redis,
    )
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
    client = web_client(app, cookies={})
    return client, factory


def make_authenticated_user(
    user_id: str,
    *,
    role: str = "user",
    username: str | None = None,
) -> AuthenticatedUser:
    """Build a user, using the ID as the default username."""
    return AuthenticatedUser(
        id=user_id,
        username=user_id if username is None else username,
        role=role,
    )


def issued_cookies(session_id: str, config) -> dict[str, str]:
    """The session cookie the library issues for ``session_id``, by name."""
    from fastapi import Response
    from webauth.cookies import issue_session_cookies

    carrier = Response()
    issue_session_cookies(carrier, session_id, config)
    return {
        name: rest.partition(";")[0]
        for name, _, rest in (h.partition("=") for h in carrier.headers.getlist("set-cookie"))
    }


def seed_session(client, username: str) -> None:
    """Open a session for the seeded ``username``.

    Writes the session row straight to the database and issues the cookies the
    callback would, because signing in itself needs the issuer.
    """
    from datetime import datetime, timedelta, timezone

    from webauth.config import installed_web_auth_config

    from songmaker_cli.auth_stores import DatabaseSessionRecordStore
    from songmaker_cli.db.models import User

    config = installed_web_auth_config(client.app)
    now = datetime.now(timezone.utc)
    with client.app.state.ctx.db() as session:
        user_id = session.query(User).filter_by(username=username).one().id
        idle = timedelta(seconds=config.session_lifetime.idle_seconds)
        record = DatabaseSessionRecordStore(session).create(
            user_id, now=now, expires_at=now + idle, refresh_token=None, id_token=None,
        )
        session.commit()
        session_id = record.id
    for name, value in issued_cookies(session_id, config).items():
        client.cookies.set(name, value)

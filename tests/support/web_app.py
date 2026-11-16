"""The songmaker web app for tests: full app, bare router, their client, accounts and Redis."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Final

import fakeredis
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from support.owner_lease_epoch import aged_owner_lease_epoch, settled_epoch
from support.session_ids import a_session_id
from webauth.ports import AuthenticatedUser

from songmaker_cli.app_context import AppContext
from songmaker_cli.words import SOURCE_LANGUAGE, Key, text

if TYPE_CHECKING:
    from redis import Redis

    from songmaker_cli.oidc_client import OidcSignIn

TEST_SECRET = b"a" * 64
TEST_ORIGIN: Final = "https://testserver"


def make_fake_redis() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


class _KeyView:
    """The keys of a fake Redis server, read and written from the test's own thread."""

    def __init__(self, server: fakeredis.FakeServer) -> None:
        self._view = fakeredis.FakeRedis(server=server, decode_responses=True)

    def __contains__(self, key: str) -> bool:
        return bool(self._view.exists(key))

    def __getitem__(self, key: str) -> str:
        return self._view.get(key)

    def __setitem__(self, key: str, value: str) -> None:
        self._view.set(key, value)


class SettledFakeAsyncRedis(fakeredis.FakeAsyncRedis):
    """A process's asyncio client on a server that has run longer than any lock or lease lasts.

    ``store`` reads and writes the server's keys from the test's thread; ``another_process`` is a
    second client on the same server.
    """

    def __init__(self) -> None:
        self.server = fakeredis.FakeServer()
        super().__init__(server=self.server)
        self.store = _KeyView(self.server)
        epoch_key, epoch_ms = settled_epoch()
        self.store[epoch_key] = str(epoch_ms)

    def another_process(self) -> fakeredis.FakeAsyncRedis:
        return fakeredis.FakeAsyncRedis(server=self.server)


def make_fake_async_redis() -> fakeredis.FakeAsyncRedis:
    """The asyncio client of a process's leases; it holds nothing the sync fake holds."""
    return fakeredis.FakeAsyncRedis()


def arrange_fake_async_redis(
    async_redis: fakeredis.FakeAsyncRedis,
    arrangement: Callable[[fakeredis.FakeAsyncRedis], Awaitable[object]],
) -> None:
    """Run ``arrangement`` in its own event loop and free the fake's connection of that loop.

    A connection a fake keeps after the loop ended cannot serve the next loop.
    """

    async def arrange_and_disconnect() -> None:
        try:
            await arrangement(async_redis)
        finally:
            await async_redis.connection_pool.disconnect()

    asyncio.run(arrange_and_disconnect())


async def settle_owner_leases(async_redis: fakeredis.FakeAsyncRedis) -> None:
    """Date the epoch of the owner leases a lease span back, so an absent lease reads GONE."""
    await async_redis.set(*aged_owner_lease_epoch())


def refusal_body(key: Key, **values: str) -> dict[str, object]:
    """The body a `Refusal` of this key answers, its sentence read from the catalog."""
    return {
        "detail": text(SOURCE_LANGUAGE, key, **values),
        "message": {"key": key, "values": values},
    }


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


def make_app_context(
    *, db: sessionmaker[Session], audio_dir: Path, data_dir: Path, redis,
) -> AppContext:
    """A context on fakes for the asyncio side, over the caller's database and sync Redis."""
    return AppContext(
        db=db, audio_dir=audio_dir, data_dir=data_dir, signing_key=TEST_SECRET, redis=redis,
        async_redis=make_fake_async_redis(),
    )


def make_router_ctx(
    tmp_path: Path,
    *,
    db: sessionmaker[Session],
    seed_db: Callable[[Session], None] | None = None,
) -> AppContext:
    """Build a router context on the required ``db``, committing seed data.

    The caller passes its database; no default builds one."""
    ctx = AppContext(
        db=db,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        signing_key=TEST_SECRET,
        redis=make_fake_redis(), async_redis=make_fake_async_redis(),
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
    from songmaker_cli.refusals import install_refusal_handler
    from songmaker_cli.server import audio_path_rejected_handler

    app = FastAPI()
    app.add_exception_handler(AudioPathRejectedError, audio_path_rejected_handler)
    install_refusal_handler(app)
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

    from webauth.ports import AccountKind

    from songmaker_cli.db.queries.auth import create_user

    return create_user(
        session, user_id or str(uuid.uuid4()), username, role, AccountKind.PERSON,
    )


def make_test_app(
    tmp_path: Path,
    seed_db: Callable | None = None,
    index_html: str = "<html>Songmaker</html>",
    *,
    factory: sessionmaker[Session],
    oidc_sign_in: OidcSignIn | None = None,
    redis: Redis | None = None,
) -> tuple:
    """Create a full test app with real middleware on the required ``factory``.

    The caller passes its database; no default builds one. ``redis`` replaces the
    fake sync client, for a test that needs a Redis that fails.

    Returns (TestClient, sessionmaker) so callers can seed data or log in.
    ``seed_db`` receives a Session to add models before the app starts;
    ``index_html`` is the built page whose inline scripts the policy hashes.
    """
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

    with factory() as session:
        if seed_db is not None:
            seed_db(session)
        session.commit()

    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=data_dir,
        signing_key=TEST_SECRET, redis=make_fake_redis() if redis is None else redis,
        async_redis=make_fake_async_redis(),
    )
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx, oidc_sign_in=oidc_sign_in)
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
        agent=None,
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
            user_id, session_id=a_session_id(), now=now, expires_at=now + idle,
            refresh_token=None, id_token=None, account_language=None,
        )
        session.commit()
        session_id = record.id
    for name, value in issued_cookies(session_id, config).items():
        client.cookies.set(name, value)

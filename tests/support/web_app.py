"""The songmaker web app for tests: full app, bare router, their client, accounts and Redis."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Final

import fakeredis
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from support.fake_oidc_issuer import IssuerSlot
from support.job_owner import an_owner
from support.object_store import an_object_store
from support.owner_lease_epoch import settled_epoch
from support.session_ids import a_session_id
from tandem.testing import settle_epoch
from webauth.ports import AuthenticatedUser

from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import REDIS_KEY_PREFIX
from songmaker_cli.page_language import LANGUAGE_PLACEHOLDER
from songmaker_cli.words import SOURCE_LANGUAGE, Key, text
from songmaker_cli.worker_liveness import MUSIC_WORKER_KIND, worker_kind_leases

if TYPE_CHECKING:
    from redis import Redis
    from support.fake_oidc_issuer import FakeIssuer

TEST_SECRET = b"a" * 64
TEST_ORIGIN: Final = "https://testserver"
BUILT_SHELL: Final = f'<html lang="{LANGUAGE_PLACEHOLDER}">Songmaker</html>'


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

    async def execute_command(self, *args, **options):
        """Run the command on a fresh connection, then free the idle one: a request of a
        ``TestClient`` that is not entered runs on a loop of its own, a fake's connection serves
        only its first, and a background task that the ending loop cancelled can leave its
        connection idle without having freed it."""
        await self.connection_pool.disconnect(inuse_connections=False)
        try:
            return await super().execute_command(*args, **options)
        finally:
            await self.connection_pool.disconnect(inuse_connections=False)


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


def hold_a_music_lease(async_redis: fakeredis.FakeAsyncRedis) -> None:
    """Make a music worker hold a live lease on the fake, as its process would."""
    arrange_fake_async_redis(
        async_redis,
        lambda redis: worker_kind_leases(redis, MUSIC_WORKER_KIND).renew("music-worker"),
    )


async def settle_owner_leases(async_redis: fakeredis.FakeAsyncRedis) -> None:
    """Settle the app's epoch, so an absent lease reads GONE."""
    await settle_epoch(async_redis, key_prefix=REDIS_KEY_PREFIX)


def refusal_body(key: Key, **values: str) -> dict[str, object]:
    """The body a `Refusal` of this key answers, its sentence read from the catalog."""
    return {
        "detail": text(SOURCE_LANGUAGE, key, **values),
        "message": {"key": key, "values": values},
    }


class _SettledReleasesTestClient(TestClient):
    """A client whose request that is not entered ends only after its stream slot releases ran.

    That request runs on a loop of its own, which cancels a background release not yet done."""

    @contextlib.contextmanager
    def _portal_factory(self):
        with super()._portal_factory() as portal:
            yield portal
            if self.portal is None:
                ctx = getattr(self.app.state, "ctx", None)
                if ctx is not None:
                    portal.call(ctx.slot_releases.drain)


def web_client(app, **kwargs) -> TestClient:
    """Build a TestClient that reaches a songmaker web app over its real HTTPS origin.

    A request naming neither `Origin` nor `Sec-Fetch-Site` carries what a same-origin
    browser sends; one naming either goes out as written."""
    client = _SettledReleasesTestClient(app, base_url=TEST_ORIGIN, **kwargs)
    client.event_hooks = {"request": [_add_same_origin_fetch_metadata]}
    return client


def _add_same_origin_fetch_metadata(request: httpx.Request) -> None:
    if "origin" not in request.headers and "sec-fetch-site" not in request.headers:
        request.headers["Sec-Fetch-Site"] = "same-origin"


def install_app_context(app, ctx) -> None:
    """Give a bare test app what ``create_app`` installs on the real one: the context and the
    composition call, whose stack answers every request.

    Call it after the app's last route. The realm is unreachable until a test calls
    ``FakeIssuer.serve(app)``. The settings are read uncached, so a test that shapes its
    environment after building its app still gets its own values back from ``get_settings()``.
    """
    from songmaker_cli.redis_client import RedisHttpMetrics
    from songmaker_cli.server import build_web_auth
    from songmaker_cli.settings import RealmSettings, Settings

    slot = IssuerSlot()
    app.state.ctx = ctx
    app.state.issuer_slot = slot
    app.state.http_metrics = RedisHttpMetrics(ctx.redis)
    auth = build_web_auth(
        ctx, Settings(), RealmSettings(),
        script_hashes=(), issuer_calls=slot.calls(), wall_clock=slot.clock,
    )
    app.state.web_auth = auth
    auth.install(app, bearer=None)


def make_app_context(
    *, db: sessionmaker[Session], audio_dir: Path, data_dir: Path, redis,
) -> AppContext:
    """A context on fakes for the asyncio side, over the caller's database and sync Redis."""
    ctx = AppContext(
        object_store=an_object_store(),
        db=db, audio_dir=audio_dir, data_dir=data_dir, signing_key=TEST_SECRET, redis=redis,
        async_redis=make_fake_async_redis(),
    )
    ctx.owner = an_owner(ctx.owner_id)
    return ctx


def make_router_ctx(
    tmp_path: Path,
    *,
    db: sessionmaker[Session],
    seed_db: Callable[[Session], None] | None = None,
) -> AppContext:
    """Build a router context on the required ``db``, committing seed data.

    The caller passes its database; no default builds one."""
    ctx = AppContext(
        object_store=an_object_store(),
        db=db,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        signing_key=TEST_SECRET,
        redis=make_fake_redis(), async_redis=make_fake_async_redis(),
    )
    ctx.owner = an_owner(ctx.owner_id)
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
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    app.include_router(router)
    install_app_context(app, ctx)
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
    index_html: str = BUILT_SHELL,
    *,
    factory: sessionmaker[Session],
    issuer: FakeIssuer | None = None,
    redis: Redis | None = None,
) -> tuple:
    """Create a full test app with real middleware on the required ``factory``.

    The caller passes its database; no default builds one. ``redis`` replaces the
    fake sync client, for a test that needs a Redis that fails. ``issuer`` is the realm the
    app's relying party talks to; without it the realm is unreachable.

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
        object_store=an_object_store(),
        db=factory, audio_dir=audio_dir, data_dir=data_dir,
        signing_key=TEST_SECRET, redis=make_fake_redis() if redis is None else redis,
        async_redis=SettledFakeAsyncRedis(),
    )
    slot = IssuerSlot()
    app = create_app(
        audio_dir, data_dir, project_root, ctx=ctx,
        issuer_calls=slot.calls(), wall_clock=slot.clock,
    )
    app.state.issuer_slot = slot
    if issuer is not None:
        issuer.serve(app)
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

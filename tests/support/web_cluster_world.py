"""Fixtures for tests that run several web processes against one database and one Redis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from agents.backend.fake_gateway import completion
from pydantic import SecretStr
from redis import Redis
from support.app_processes import OIDC_CLIENT_ID, StandIns, WebProcesses, web_processes
from support.cowriter_gateway import MEMBER_GROUPS, HeldGateway
from support.fake_oidc_issuer import Person
from support.gateway_server import serve_gateway
from support.https_issuer import HttpsIssuer, serve_issuer
from support.redis_proxy import redis_proxy
from support.session_ids import a_session_id
from support.web_app import issued_cookies, seed_user

from songmaker_cli.app_context import AppContext, build_web_auth_config
from songmaker_cli.auth_stores import DatabaseSessionRecordStore

SCRIPTED_REPLY = "The reply the gateway stand-in scripted."


@dataclass(frozen=True)
class SignedInPerson:
    """An account and the cookies that sign a request in as it on any process of the case."""

    user_id: str
    cookies: dict[str, str]


def sign_in_person(
    cluster: WebProcesses, factory, redis_url: str, username: str,
    *, refresh_token: str | None = None,
) -> SignedInPerson:
    """Open a session through the production session store and issue its cookie."""
    now = datetime.now(timezone.utc)
    settings = cluster.settings()
    with factory() as session:
        person = seed_user(session, username)
        record = DatabaseSessionRecordStore(session).create(
            person.id,
            session_id=a_session_id(),
            now=now,
            expires_at=now + timedelta(seconds=settings.session_idle_seconds),
            refresh_token=None if refresh_token is None else SecretStr(refresh_token),
            id_token=None,
            account_language=None,
        )
        session.commit()
        session_id, user_id = record.id, person.id
    context = AppContext(
        db=factory,
        audio_dir=cluster.audio_dir,
        data_dir=cluster.root,
        signing_key=cluster.session_secret.encode(),
        redis=Redis.from_url(redis_url),
    )
    config = build_web_auth_config(context, settings)
    return SignedInPerson(user_id, issued_cookies(session_id, config))


@pytest.fixture
def case_factory(extra_pg_factory):
    """A session factory on a database of the case's own, which the per-test reset leaves alone."""
    return extra_pg_factory()


@pytest.fixture
def database_url(case_factory) -> str:
    return case_factory.kw["bind"].url.render_as_string(hide_password=False)


@pytest.fixture
def web_cluster(tmp_path: Path, case_factory, database_url: str, redis_url: str):
    """The processes of one case, on a database and a Redis of its own; none is started yet."""
    with web_processes(tmp_path, database_url=database_url, redis_url=redis_url) as cluster:
        yield cluster, case_factory


@pytest.fixture
def two_processes(web_cluster):
    """A and B, running against one database and one Redis."""
    cluster, factory = web_cluster
    return cluster, factory, cluster.start("a"), cluster.start("b")


@pytest.fixture
def proxied_cluster(tmp_path: Path, case_factory, database_url: str, redis_url: str):
    """The processes of one case reach Redis through a proxy that cuts the line on demand."""
    with redis_proxy(redis_url) as proxy:
        with web_processes(tmp_path, database_url=database_url, redis_url=proxy.url) as cluster:
            yield cluster, case_factory, proxy


@dataclass(frozen=True)
class StandInCluster:
    """A case whose processes reach a held gateway and an HTTPS realm; none is started yet."""

    cluster: WebProcesses
    factory: object
    gateway: HeldGateway
    issuer: HttpsIssuer

    def sign_in(self, redis_url: str, username: str, *, refresh_token: str) -> SignedInPerson:
        """Sign a new account in on every process; the realm vouches for it at each renewal."""
        person = sign_in_person(
            self.cluster, self.factory, redis_url, username, refresh_token=refresh_token,
        )
        self.issuer.realm.person = Person(subject=person.user_id, groups=MEMBER_GROUPS)
        return person


@pytest.fixture
def stand_in_cluster(tmp_path: Path, case_factory, database_url: str, redis_url: str):
    """The processes of one case reach a held gateway over HTTP and a realm over HTTPS."""
    gateway = HeldGateway(completion(SCRIPTED_REPLY))
    with (
        serve_gateway(gateway) as gateway_origin,
        serve_issuer(tmp_path, client_id=OIDC_CLIENT_ID) as issuer,
    ):
        stand_ins = StandIns(gateway_origin, issuer.url, issuer.ca_file)
        with web_processes(
            tmp_path, database_url=database_url, redis_url=redis_url, stand_ins=stand_ins,
        ) as cluster:
            yield StandInCluster(cluster, case_factory, gateway, issuer)

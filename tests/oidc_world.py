"""A fake Keycloak realm in front of a full test app, for the sign-in and logout tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from conftest import make_test_app, seed_user
from fake_oidc_issuer import FakeIssuer, Person, a_fake_issuer

from songmaker_cli.db.models import User, UserSession

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient
    from httpx import Response
    from sqlalchemy.orm import sessionmaker


@dataclass
class World:
    client: TestClient
    factory: sessionmaker
    issuer: FakeIssuer

    def users(self) -> list[tuple[str, str, str]]:
        with self.factory() as session:
            return sorted((u.id, u.username, u.role) for u in session.query(User).all())

    def session_count(self) -> int:
        with self.factory() as session:
            return session.query(UserSession).count()

    def seed(self, user_id: str, username: str, role: str = "user") -> None:
        with self.factory() as session:
            seed_user(session, username, role, user_id=user_id)
            session.commit()

    def start(self, next_path: str | None = None) -> Response:
        query = {} if next_path is None else {"next": next_path}
        return self.client.get("/login/oidc", params=query, follow_redirects=False)

    def callback(self, person: Person, started: Response, state: str | None = None) -> Response:
        issued_state, code = self.issuer.remember_authorization(started.headers["location"])
        self.issuer.person = person
        return self.client.get(
            "/auth/callback",
            params={"code": code, "state": issued_state if state is None else state},
            follow_redirects=False,
        )

    def sign_in(self, person: Person, next_path: str | None = None) -> Response:
        return self.callback(person, self.start(next_path))


@pytest.fixture
def world(tmp_path: Path) -> World:
    client, factory = make_test_app(tmp_path)
    issuer = a_fake_issuer()
    client.app.state.oidc_sign_in = issuer.relying_party_for_app()
    return World(client, factory, issuer)

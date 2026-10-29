"""The person-token scenario: the gated app, a fake realm and a header-exact client."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pytest
from fake_oidc_issuer import FakeIssuer, a_fake_issuer
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from support.web_app import TEST_ORIGIN, make_test_app, seed_user

from songmaker_cli.constants import OIDC_LOGIN_GROUP
from songmaker_cli.db.models import Album, AuditLog, Generation, Song, User, Version


@dataclass
class TokenWorld:
    """The full app with the person-path gate on, a fake realm, and a header-exact client.

    It also owns the scenario's people and token values.
    """

    HAL: ClassVar = "hal"
    ALICE: ClassVar = "6f1d2c3b-aaaa-4bbb-8ccc-0123456789ab"
    BOB: ClassVar = "0a9b8c7d-dddd-4eee-8fff-ba9876543210"
    TOKEN_LIFETIME_SECONDS: ClassVar = 300

    client: TestClient
    factory: sessionmaker[Session]
    issuer: FakeIssuer
    audio_dir: Path

    def token(
        self,
        subject: str = ALICE,
        *,
        groups: tuple[str, ...] = (OIDC_LOGIN_GROUP,),
        username: str = "alice",
        **claims: object,
    ) -> str:
        now = int(self.issuer.now)
        body: dict[str, object] = {
            "iss": self.issuer.issuer,
            "aud": self.issuer.client_id,
            "sub": subject,
            "azp": self.HAL,
            "preferred_username": username,
            "groups": list(groups),
            "iat": now,
            "exp": now + self.TOKEN_LIFETIME_SECONDS,
            **claims,
        }
        return self.issuer.sign(
            {name: value for name, value in body.items() if value is not None},
            token_type="at+jwt",
        )

    def bearer(self, subject: str = ALICE, **options: object) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(subject, **options)}"}

    def rows(self, model: type, *columns: str) -> list[tuple]:
        with self.factory() as session:
            found = [
                tuple(getattr(row, column) for column in columns)
                for row in session.query(model).all()
            ]
        return sorted(found, key=repr)

    def users(self) -> list[tuple[str, str, str]]:
        return self.rows(User, "id", "username", "role")

    def audits(self) -> list[tuple[str | None, str, str, str]]:
        return [
            (user_id, action, resource, resource_id)
            for user_id, action, resource, resource_id in self.rows(
                AuditLog, "user_id", "action", "resource_type", "resource_id",
            )
        ]

    def albums(self) -> list[tuple[str, str | None]]:
        return self.rows(Album, "title", "created_by")

    def seed_take(self, owner: str, name: str) -> str:
        """An album with one song and one take whose file exists; returns the take's id."""
        with self.factory() as session:
            if session.get(User, owner) is None:
                seed_user(session, f"user-{owner[:4]}", user_id=owner)
            session.add(Album(
                id=f"album-{name}", title=f"Album {name}", artist="", created_by=owner,
            ))
            session.add(Song(id=f"song-{name}", title=f"Song {name}", album_id=f"album-{name}",
                             track_number=1, slug=f"song-{name}"))
            session.add(Version(id=f"version-{name}", song_id=f"song-{name}", version_number=1,
                                lyrics="la", prompt="pop"))
            session.add(Generation(id=f"take-{name}", song_id=f"song-{name}",
                                   version_id=f"version-{name}", generation_number=1,
                                   mp3_path=f"{owner}/{name}.mp3", seed=1))
            session.commit()
        (self.audio_dir / owner).mkdir(parents=True, exist_ok=True)
        (self.audio_dir / owner / f"{name}.mp3").write_bytes(b"ID3 not really audio")
        return f"take-{name}"


def make_token_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, factory: sessionmaker | None = None,
) -> TokenWorld:
    from songmaker_cli.settings import get_settings

    get_settings.cache_clear()
    issuer = a_fake_issuer()
    app_client, factory = make_test_app(
        tmp_path, factory=factory, oidc_sign_in=issuer.relying_party_for_app(),
    )
    # A client that adds no Fetch Metadata: a request names exactly the headers a test gives it.
    client = TestClient(app_client.app, base_url=TEST_ORIGIN, cookies={},
                        raise_server_exceptions=False)
    return TokenWorld(client, factory, issuer, tmp_path / "audio")

"""Albums of alice, bob and an admin on a fresh test database, with alice signed in.

alice's session holds a refresh grant and the realm names her a member of the API group, so
Suggest passes its click-time check and the cover runs through ``FakeGateway``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel
from support.cowriter_gateway import attach_cowriter_gateway
from support.web_app import make_authenticated_user, make_test_app
from webauth.ports import AuthenticatedUser

from songmaker_cli.db.models import Album, User


def seed_cover_albums(session) -> None:
    alice = User(username="alice", role="user")
    bob = User(username="bob", role="user")
    admin = User(username="admin", role="admin")
    session.add_all([alice, bob, admin])
    session.flush()
    session.add_all([
        Album(id="alice-album", title="Alice", artist="Alice", created_by=alice.id),
        Album(id="bob-album", title="Bob", artist="Bob", created_by=bob.id),
    ])


def album_owner(session, album_id: str = "alice-album") -> AuthenticatedUser:
    album = session.query(Album).filter_by(id=album_id).one()
    return make_authenticated_user(album.created_by or "")


@pytest.fixture
def cover_album_app(tmp_path: Path, pg_factory) -> tuple[TestClient, object]:
    client, factory = make_test_app(tmp_path, seed_db=seed_cover_albums, factory=pg_factory)
    with factory() as session:
        alice_id = session.query(User).filter_by(username="alice").one().id
    attach_cowriter_gateway(client, factory, tmp_path, alice_id)
    return client, factory


def declared_suggest_refusal(status: int) -> type[BaseModel]:
    """The error body the Suggest route declares for ``status`` in its API contract."""
    from songmaker_cli.album_api import router

    [suggest] = [
        route for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/albums/{album_id}/cover-suggestions"
        and "POST" in route.methods
    ]
    return suggest.responses[status]["model"]

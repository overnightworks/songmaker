"""The router fixture seeds committed data and keeps authentication explicit."""

from pathlib import Path

import pytest
from conftest import make_authenticated_user, make_router_app, make_router_ctx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from songmaker_cli.db.models import Album, User


@pytest.mark.parametrize("authenticated", [False, True])
def test_seeded_router_data_is_committed_before_authenticated_requests(
    tmp_path: Path, authenticated: bool,
) -> None:
    def seed_album(session: Session) -> None:
        session.add(User(id="owner", username="owner", password_hash="unused", role="user"))
        session.flush()
        session.add(Album(id="album", title="Seeded album", artist="Artist", created_by="owner"))

    user = make_authenticated_user("owner")
    app = make_router_app(
        make_router_ctx(tmp_path, seed_db=seed_album), user=user if authenticated else None
    )

    with app.state.ctx.db() as session:
        assert session.get(Album, "album").title == "Seeded album"
    response = TestClient(app).get("/api/albums")
    assert response.status_code == (200 if authenticated else 401)
    if authenticated:
        assert response.json()["items"][0]["title"] == "Seeded album"

"""Several people signed in to the settings routes of one test database."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.db.models import User


def sign_in_people(
    tmp_path: Path,
    factory: sessionmaker[Session],
    roles: dict[str, str],
) -> dict[str, TestClient]:
    """One client per name in `roles` (name to role), each person's id being `u-<name>`."""

    def seed(session: Session) -> None:
        session.add_all(
            [User(id=f"u-{name}", username=name, role=role) for name, role in roles.items()],
        )

    ctx = make_router_ctx(tmp_path, db=factory, seed_db=seed)
    return {
        name: web_client(
            make_router_app(ctx, user=make_authenticated_user(f"u-{name}", role=role)),
        )
        for name, role in roles.items()
    }

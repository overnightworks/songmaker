"""A client signed in as an admin on a fresh test database."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.db.engine import init_test_db


def build_admin_client(
    tmp_path: Path,
    seed_db: Callable[[Session], None],
    *,
    user_id: str,
    username: str,
    database_name: str = "admin.db",
) -> tuple[TestClient, sessionmaker[Session]]:
    """Seed a fresh database, then sign in as its admin ``user_id`` on the API router.

    ``seed_db`` must add the account ``user_id``; the router app takes the
    authenticated user from the builder, not from a session cookie.
    """
    ctx = make_router_ctx(tmp_path, db=init_test_db(tmp_path / database_name), seed_db=seed_db)
    admin = make_authenticated_user(user_id, role="admin", username=username)
    app = make_router_app(ctx, user=admin)
    return web_client(app), ctx.db

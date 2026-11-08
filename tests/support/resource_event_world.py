"""Authenticated users, seeded events and SSE frame readers for the resource-event stream tests."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from support.web_app import TEST_SECRET, make_test_app, seed_user, web_client
from webauth.cookies import DEFAULT_SESSION_COOKIE_NAME, sign_session_id

from songmaker_cli.db.models import User
from songmaker_cli.db.queries.auth import create_session
from songmaker_cli.db.queries.resource_events import create_generation_created_event


def _seed_stream_users(session) -> None:
    seed_user(session, "alice", role="user")
    seed_user(session, "bob", role="user")
    seed_user(session, "admin", role="admin")


def _authenticated_clients(tmp_path: Path, pg_factory):
    base_client, factory = make_test_app(tmp_path, factory=pg_factory, seed_db=_seed_stream_users)
    clients: dict[str, TestClient] = {}
    user_ids: dict[str, str] = {}
    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    with factory() as session:
        for username in ("alice", "bob", "admin"):
            user = session.query(User).filter_by(username=username).one()
            user_ids[username] = user.id
            user_session = create_session(session, user.id, expires_at)
            session.flush()
            client = (
                base_client
                if username == "alice"
                else web_client(
                    base_client.app,
                    cookies={},
                )
            )
            client.cookies.set(
                DEFAULT_SESSION_COOKIE_NAME,
                sign_session_id(user_session.id, TEST_SECRET),
            )
            clients[username] = client
        session.commit()
    return clients, factory, user_ids


def _create_event(factory, user_id: str, number: int) -> str:
    generation_id = f"generation-{number}"
    with factory() as session:
        create_generation_created_event(
            session,
            user_id=user_id,
            song_id=f"song-{number}",
            generation_id=generation_id,
        )
        session.commit()
    return generation_id


def _parse_sse(chunk: str) -> dict:
    if chunk.startswith(":"):
        return {"comment": chunk.removeprefix(":").strip()}
    parsed: dict[str, object] = {}
    for line in chunk.strip().splitlines():
        field, _, value = line.partition(":")
        value = value.lstrip()
        if field == "data":
            parsed[field] = json.loads(value)
        else:
            parsed[field] = value
    return parsed


async def _take_frames(generator, count: int) -> list[dict]:
    frames = []
    try:
        for _ in range(count):
            frames.append(_parse_sse(await anext(generator)))
    finally:
        await generator.aclose()
    return frames


def _collect(generator, count: int) -> list[dict]:
    return asyncio.run(_take_frames(generator, count))

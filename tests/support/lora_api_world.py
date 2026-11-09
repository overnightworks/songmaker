"""Shared arrangement of the LoRA route tests: users, clients, LoRA and take builders."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.app_context import AppContext
from songmaker_cli.db.models import Album, Generation, Song, User, Version
from songmaker_cli.db.queries.loras import create_user_lora

USER_A = "u-alice"
USER_B = "u-bob"


def seed_users(session: Session) -> None:
    session.add(User(id=USER_A, username="alice", role="user"))
    session.add(User(id=USER_B, username="bob", role="user"))


@pytest.fixture
def client_and_ctx(tmp_path: Path, pg_factory) -> tuple[TestClient, AppContext]:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    with pg_factory() as session:
        seed_users(session)
        session.commit()

    app = make_router_app(
        make_router_ctx(tmp_path, db=pg_factory), user=make_authenticated_user(USER_A)
    )
    ctx = app.state.ctx
    return web_client(app), ctx


@pytest.fixture
def client_a(client_and_ctx: tuple[TestClient, AppContext]) -> TestClient:
    client, _ = client_and_ctx
    return client



def make_lora(ctx: AppContext, user_id: str = USER_A) -> str:
    with ctx.db() as session:
        lora = create_user_lora(session, user_id, "L", "l")
        session.commit()
        return lora.id


def make_take(
    ctx: AppContext,
    *,
    owner_id: str = USER_A,
    take_id: str = "take-1",
    caption: str = "Warm tenor over piano",
    lyrics: str = "A line from the take",
    audio: bytes = b"ID3 source audio",
    is_archived: bool = False,
    has_version: bool = True,
) -> str:
    album_id = f"album-{take_id}"
    song_id = f"song-{take_id}"
    version_id = f"version-{take_id}" if has_version else None
    audio_path = f"{owner_id}/{take_id}.mp3"
    with ctx.db() as session:
        session.add(Album(
            id=album_id,
            title=f"Song for {take_id}",
            artist="Test artist",
            created_by=owner_id,
        ))
        session.add(Song(
            id=song_id,
            title=f"Take song {take_id}",
            album_id=album_id,
            track_number=1,
        ))
        if version_id:
            session.add(Version(
                id=version_id,
                song_id=song_id,
                version_number=1,
                prompt=caption,
                lyrics=lyrics,
            ))
        session.add(Generation(
            id=take_id,
            song_id=song_id,
            version_id=version_id,
            generation_number=4,
            mp3_path=audio_path,
            is_archived=is_archived,
        ))
        session.commit()
    source = ctx.audio_dir / audio_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(audio)
    return take_id


def client_for_user(ctx: AppContext, user_id: str, role: str = "user") -> TestClient:
    app = make_router_app(ctx, user=make_authenticated_user(user_id, role=role))
    return web_client(app)


def post_sample_from_take(client: TestClient, lora_id: str, take_id: str):
    return client.post(
        f"/api/loras/{lora_id}/samples/from-generation",
        json={"generation_id": take_id},
    )


def post_sample_upload(client: TestClient, lora_id: str, _take_id: str):
    return client.post(
        f"/api/loras/{lora_id}/samples",
        data={"caption": "chill verse", "lyrics": "oh yeah"},
        files={"audio": ("clip.wav", b"RIFFxxxxWAVE", "audio/wav")},
    )


sample_routes = pytest.mark.parametrize(
    "post_sample", [post_sample_from_take, post_sample_upload],
    ids=["from-generation", "upload"],
)

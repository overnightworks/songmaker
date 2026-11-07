"""Body-size path rules and real create_app() upload budgets."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.web_app import make_test_app, seed_session

from songmaker_cli.constants import (
    AUDIO_UPLOAD_BODY_MAX_BYTES,
    COVER_UPLOAD_BODY_MAX_BYTES,
    JSON_REQUEST_BODY_MAX_BYTES,
    REFERENCE_AUDIO_MAX_BYTES,
)
from songmaker_cli.db.models import Album, User
from songmaker_cli.db.queries.loras import create_user_lora
from songmaker_cli.request_policies import build_body_size_policy
from songmaker_cli.settings import get_settings


@pytest.mark.parametrize("path", [
    "/api/loras/abc-id/samples/extra",
    "/api/other/samples",
    "/api/loras//samples",
    "/api/playlists//cover",
])
def test_a_route_that_only_looks_like_an_upload_keeps_the_json_budget(path: str) -> None:
    assert build_body_size_policy(get_settings()).max_bytes(path, "POST") == (
        JSON_REQUEST_BODY_MAX_BYTES
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/songs", JSON_REQUEST_BODY_MAX_BYTES),
        ("/api/references", AUDIO_UPLOAD_BODY_MAX_BYTES),
        ("/api/loras/x/samples", AUDIO_UPLOAD_BODY_MAX_BYTES),
        ("/api/playlists/x/cover", COVER_UPLOAD_BODY_MAX_BYTES),
    ],
)
def test_body_limits_keep_json_small_and_uploads_larger(path: str, expected: int) -> None:
    assert build_body_size_policy(get_settings()).max_bytes(path, "POST") == expected


def test_the_audio_upload_budget_leaves_room_for_the_file() -> None:
    assert AUDIO_UPLOAD_BODY_MAX_BYTES > REFERENCE_AUDIO_MAX_BYTES


def _seed_owner(session) -> None:
    session.add(User(id="owner-id", username="owner"))
    session.flush()
    session.add(Album(id="a1", title="A", artist="A", created_by="owner-id"))


def _authed_app(tmp_path: Path, factory) -> TestClient:
    client, _ = make_test_app(tmp_path, seed_db=_seed_owner, factory=factory)
    seed_session(client, "owner")
    return client


def test_create_app_accepts_2mib_reference_audio(tmp_path: Path, pg_factory) -> None:
    client = _authed_app(tmp_path, pg_factory)
    payload = b"RIFF" + b"\x00" * (2 * 1024 * 1024)
    resp = client.post(
        "/api/references",
        files={"file": ("ref.wav", payload, "audio/wav")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["filename"] == "ref.wav"
    assert resp.json()["size_bytes"] == len(payload)


def test_create_app_accepts_2mib_lora_sample(tmp_path: Path, pg_factory) -> None:
    client, factory = make_test_app(tmp_path, seed_db=_seed_owner, factory=pg_factory)
    seed_session(client, "owner")
    with factory() as session:
        lora = create_user_lora(session, "owner-id", "Voice", "v")
        session.commit()
        lora_id = lora.id
    payload = b"RIFF" + b"\x00" * (2 * 1024 * 1024)
    resp = client.post(
        f"/api/loras/{lora_id}/samples",
        data={"caption": "verse", "lyrics": "la"},
        files={"audio": ("clip.wav", payload, "audio/wav")},
    )
    assert resp.status_code == 200, resp.text


def test_json_route_still_rejects_over_1mib(tmp_path: Path, pg_factory) -> None:
    client = _authed_app(tmp_path, pg_factory)
    resp = client.post(
        "/api/songs",
        content=b"x" * (JSON_REQUEST_BODY_MAX_BYTES + 10),
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 413

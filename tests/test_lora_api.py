"""Tests for LoRA CRUD + training HTTP endpoints."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from conftest import TEST_SECRET, make_fake_redis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import (
    ARQ_MUSIC_QUEUE_NAME,
    USER_LORA_MAX_SAMPLES,
    USER_LORA_SAMPLE_MAX_BYTES,
    JobStatus,
    LoraStatus,
)
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import (
    LORA_SLUG_MAX_LENGTH,
    Album,
    Generation,
    Job,
    Song,
    User,
    UserLora,
    UserLoraSample,
    Version,
)
from songmaker_cli.db.queries import (
    add_user_lora_sample,
    create_user_lora,
    update_user_lora,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

USER_A = "u-alice"
USER_B = "u-bob"


def _seed_users(session: Session) -> None:
    session.add(User(id=USER_A, username="alice", password_hash="x", role="user"))
    session.add(User(id=USER_B, username="bob", password_hash="x", role="user"))


def _user_dep(user_id: str, role: str = "user"):
    def _dep() -> AuthenticatedUser:
        return AuthenticatedUser(
            id=user_id, username=user_id, role=role, is_active=True,
        )
    return _dep


def _build_app(tmp_path: Path, user_id: str = USER_A) -> tuple[TestClient, AppContext]:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    factory = init_test_db(data_dir / "songmaker.db")
    with factory() as session:
        _seed_users(session)
        session.commit()

    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=data_dir,
        session_secret=TEST_SECRET, redis=make_fake_redis(),
    )

    from songmaker_cli.api import router
    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _user_dep(user_id)
    app.include_router(router)
    return TestClient(app), ctx


@pytest.fixture
def client_a(tmp_path: Path) -> TestClient:
    client, _ = _build_app(tmp_path, USER_A)
    yield client


@pytest.fixture
def client_and_ctx(tmp_path: Path) -> tuple[TestClient, AppContext]:
    return _build_app(tmp_path, USER_A)


@contextmanager
def _mock_arq():
    mock_pool = AsyncMock()
    with patch("songmaker_cli.lora_api.get_arq_pool", return_value=mock_pool):
        yield mock_pool


# ── Create ────────────────────────────────────────────────────────────


def test_create_lora_happy_path(client_a: TestClient) -> None:
    resp = client_a.post("/api/loras", json={"name": "My Voice"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "My Voice"
    assert data["slug"] == "my-voice"
    assert data["status"] == LoraStatus.DRAFT
    assert data["samples"] == []


def test_create_lora_allows_requests_below_configured_voice_limit(
    client_a: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_USER_LORAS", "2")

    first = client_a.post("/api/loras", json={"name": "First"})
    second = client_a.post("/api/loras", json={"name": "Second"})

    assert first.status_code == 200
    assert second.status_code == 200


def test_create_lora_returns_named_voice_limit_error(
    client_a: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_USER_LORAS", "1")
    assert client_a.post("/api/loras", json={"name": "First"}).status_code == 200

    response = client_a.post("/api/loras", json={"name": "Second"})

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Could not create voice\n"
        "You have reached the limit of 1 voices. Delete a voice before creating another.",
        "reason": "voice_limit",
    }


def test_create_lora_does_not_count_a_deleted_voice_toward_the_limit(
    client_a: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_USER_LORAS", "1")
    first = client_a.post("/api/loras", json={"name": "First"})
    assert first.status_code == 200
    assert client_a.delete(f"/api/loras/{first.json()['id']}").status_code == 200

    replacement = client_a.post("/api/loras", json={"name": "Replacement"})

    assert replacement.status_code == 200


def test_create_lora_slug_collision_appends_suffix(client_a: TestClient) -> None:
    first = client_a.post("/api/loras", json={"name": "My Voice"})
    assert first.status_code == 200
    assert first.json()["slug"] == "my-voice"

    second = client_a.post("/api/loras", json={"name": "My Voice"})
    assert second.status_code == 200
    assert second.json()["slug"] == "my-voice-2"

    third = client_a.post("/api/loras", json={"name": "My Voice"})
    assert third.status_code == 200
    assert third.json()["slug"] == "my-voice-3"


def test_create_lora_empty_name_rejected(client_a: TestClient) -> None:
    resp = client_a.post("/api/loras", json={"name": "   "})
    assert resp.status_code == 422


def test_create_lora_with_100_char_name_succeeds(client_a: TestClient) -> None:
    resp = client_a.post("/api/loras", json={"name": "a" * 100})
    assert resp.status_code == 200
    assert len(resp.json()["slug"]) <= LORA_SLUG_MAX_LENGTH


def test_create_lora_with_cjk_name_succeeds(client_a: TestClient) -> None:
    resp = client_a.post("/api/loras", json={"name": "音" * 100})
    assert resp.status_code == 200
    assert len(resp.json()["slug"]) <= LORA_SLUG_MAX_LENGTH


def test_create_lora_slug_collision_at_budget_edge_appends_suffix(
    client_a: TestClient,
) -> None:
    """Two CJK names that only differ in their last character collide on
    the same base slug: 99 CJK characters transliterate to far more than
    LORA_SLUG_MAX_LENGTH characters, so truncation always lands inside the
    shared 99-character prefix regardless of the exact budget — the second
    create must still fit within LORA_SLUG_MAX_LENGTH once the "-2" counter
    suffix is appended."""
    name_a = "音" * 99 + "A"
    name_b = "音" * 99 + "B"

    first = client_a.post("/api/loras", json={"name": name_a})
    assert first.status_code == 200
    first_slug = first.json()["slug"]
    assert len(first_slug) <= LORA_SLUG_MAX_LENGTH

    second = client_a.post("/api/loras", json={"name": name_b})
    assert second.status_code == 200
    second_slug = second.json()["slug"]
    assert second_slug == f"{first_slug}-2"
    assert len(second_slug) <= LORA_SLUG_MAX_LENGTH


def test_create_lora_integrity_error(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    from sqlalchemy.exc import IntegrityError

    with patch(
        "songmaker_cli.lora_api.create_user_lora",
        side_effect=IntegrityError("x", "y", Exception("boom")),
    ):
        resp = client.post("/api/loras", json={"name": "Boom"})
    assert resp.status_code == 409


# ── List / Get ────────────────────────────────────────────────────────


def test_list_loras_excludes_soft_deleted_by_default(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    with ctx.db() as session:
        keep = create_user_lora(session, USER_A, "Keep", "keep")
        gone = create_user_lora(session, USER_A, "Gone", "gone")
        session.commit()
        keep_id = keep.id
        gone_id = gone.id
        from songmaker_cli.db.queries import soft_delete_user_lora
        soft_delete_user_lora(session, gone_id)
        session.commit()

    resp = client.get("/api/loras")
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()["loras"]}
    assert ids == {keep_id}

    resp = client.get("/api/loras?include_deleted=true")
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()["loras"]}
    assert ids == {keep_id, gone_id}


def test_lora_response_includes_its_training_model_mode(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    with ctx.db() as session:
        lora = create_user_lora(
            session,
            USER_A,
            "Turbo Voice",
            "turbo-voice",
            model_mode="turbo",
        )
        session.commit()
        lora_id = lora.id

    response = client.get(f"/api/loras/{lora_id}")

    assert response.status_code == 200
    assert response.json()["model_mode"] == "turbo"


def test_get_lora_returns_samples_in_position_order(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    with ctx.db() as session:
        lora = create_user_lora(session, USER_A, "L", "l")
        add_user_lora_sample(
            session, lora.id, "a/1.wav", caption="c1", lyrics="y1", position=2,
        )
        add_user_lora_sample(
            session, lora.id, "a/2.wav", caption="c2", lyrics="y2", position=0,
        )
        add_user_lora_sample(
            session, lora.id, "a/3.wav", caption="c3", lyrics="y3", position=1,
        )
        session.commit()
        lora_id = lora.id

    resp = client.get(f"/api/loras/{lora_id}")
    assert resp.status_code == 200
    positions = [s["position"] for s in resp.json()["samples"]]
    assert positions == [0, 1, 2]


def test_get_lora_missing_returns_404(client_a: TestClient) -> None:
    resp = client_a.get("/api/loras/missing")
    assert resp.status_code == 404


def test_cross_user_access_is_404(tmp_path: Path) -> None:
    client_a, ctx = _build_app(tmp_path, USER_A)
    with ctx.db() as session:
        lora_a = create_user_lora(session, USER_A, "Secret", "secret")
        session.commit()
        lora_id = lora_a.id

    app_b = FastAPI()
    app_b.state.ctx = ctx
    from songmaker_cli.api import router
    app_b.dependency_overrides[get_current_user] = _user_dep(USER_B)
    app_b.include_router(router)
    client_b = TestClient(app_b)

    assert client_b.get(f"/api/loras/{lora_id}").status_code == 404
    assert client_b.delete(f"/api/loras/{lora_id}").status_code == 404
    assert client_b.post(f"/api/loras/{lora_id}/train").status_code == 404
    assert client_b.get("/api/loras").json()["loras"] == []


def test_admin_cannot_access_another_users_lora(tmp_path: Path) -> None:
    _, ctx = _build_app(tmp_path, USER_A)
    lora_id = _make_lora(ctx, USER_A)
    with ctx.db() as session:
        sample = add_user_lora_sample(
            session, lora_id, "alice/sample.wav", caption="c", lyrics="l",
        )
        session.commit()
        sample_id = sample.id
    admin = _client_for_user(ctx, "u-admin", role="admin")

    assert admin.get(f"/api/loras/{lora_id}").status_code == 404
    assert admin.delete(f"/api/loras/{lora_id}").status_code == 404
    assert admin.post(f"/api/loras/{lora_id}/train").status_code == 404
    assert admin.patch(
        f"/api/loras/{lora_id}/samples/{sample_id}", json={"caption": "x"},
    ).status_code == 404
    assert admin.delete(f"/api/loras/{lora_id}/samples/{sample_id}").status_code == 404


# ── Delete ────────────────────────────────────────────────────────────


def test_delete_lora_soft_deletes(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    with ctx.db() as session:
        lora = create_user_lora(session, USER_A, "Bye", "bye")
        session.commit()
        lora_id = lora.id

    resp = client.delete(f"/api/loras/{lora_id}")
    assert resp.status_code == 200

    with ctx.db() as session:
        row = session.query(UserLora).filter_by(id=lora_id).first()
        assert row is not None
        assert row.deleted_at is not None

    resp = client.get("/api/loras")
    assert lora_id not in {r["id"] for r in resp.json()["loras"]}


def test_delete_lora_rejected_if_active(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    with ctx.db() as session:
        lora = create_user_lora(session, USER_A, "Busy", "busy")
        update_user_lora(session, lora.id, status=LoraStatus.TRAINING)
        session.commit()
        lora_id = lora.id

    resp = client.delete(f"/api/loras/{lora_id}")
    assert resp.status_code == 409


def test_delete_lora_missing_returns_404(client_a: TestClient) -> None:
    resp = client_a.delete("/api/loras/missing")
    assert resp.status_code == 404


# ── Samples ───────────────────────────────────────────────────────────


def _make_lora(ctx: AppContext, user_id: str = USER_A) -> str:
    with ctx.db() as session:
        lora = create_user_lora(session, user_id, "L", "l")
        session.commit()
        return lora.id


def _make_take(
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


def _client_for_user(ctx: AppContext, user_id: str, role: str = "user") -> TestClient:
    app = FastAPI()
    app.state.ctx = ctx
    from songmaker_cli.api import router
    app.dependency_overrides[get_current_user] = _user_dep(user_id, role)
    app.include_router(router)
    return TestClient(app)


def test_add_sample_from_own_take_copies_audio_and_take_version(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)
    take_id = _make_take(ctx, audio=b"source take bytes")

    response = client.post(
        f"/api/loras/{lora_id}/samples/from-generation",
        json={"generation_id": take_id},
    )

    assert response.status_code == 200, response.text
    sample = response.json()
    assert sample["caption"] == "Warm tenor over piano"
    assert sample["lyrics"] == "A line from the take"
    assert (ctx.audio_dir / sample["audio_path"]).read_bytes() == b"source take bytes"
    assert sample["audio_path"] != f"{USER_A}/{take_id}.mp3"


def test_add_sample_from_foreign_take_returns_404(tmp_path: Path) -> None:
    _, ctx = _build_app(tmp_path, USER_A)
    lora_id = _make_lora(ctx, USER_B)
    take_id = _make_take(ctx, owner_id=USER_A)
    client_b = _client_for_user(ctx, USER_B)

    response = client_b.post(
        f"/api/loras/{lora_id}/samples/from-generation",
        json={"generation_id": take_id},
    )

    assert response.status_code == 404


def test_add_sample_from_unplayable_take_is_rejected(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)
    take_id = _make_take(ctx, is_archived=True)

    response = client.post(
        f"/api/loras/{lora_id}/samples/from-generation",
        json={"generation_id": take_id},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Generation is not playable"


def test_add_sample_from_missing_take_returns_404(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)

    response = client.post(
        f"/api/loras/{lora_id}/samples/from-generation",
        json={"generation_id": "missing"},
    )

    assert response.status_code == 404


def test_add_sample_from_take_with_escaping_audio_path_returns_404(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)
    take_id = _make_take(ctx)
    (ctx.audio_dir.parent / "secret.mp3").write_bytes(b"secret audio")
    with ctx.db() as session:
        session.get(Generation, take_id).mp3_path = "../secret.mp3"
        session.commit()

    response = client.post(
        f"/api/loras/{lora_id}/samples/from-generation",
        json={"generation_id": take_id},
    )

    assert response.status_code == 404
    assert not (ctx.audio_dir / "user_loras").exists()
    with ctx.db() as session:
        assert session.query(UserLoraSample).filter_by(user_lora_id=lora_id).count() == 0


def test_versionless_own_take_is_listed_and_copied_with_empty_metadata(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)
    take_id = _make_take(ctx, has_version=False, audio=b"reimported take")

    catalogue = client.get("/api/loras/own-takes")
    response = client.post(
        f"/api/loras/{lora_id}/samples/from-generation",
        json={"generation_id": take_id},
    )

    assert catalogue.status_code == 200
    assert catalogue.json()["takes"][0] == {
        "generation_id": take_id,
        "song_title": f"Take song {take_id}",
        "generation_number": 4,
        "audio_url": f"/audio/{USER_A}/{take_id}.mp3",
        "caption": "",
        "lyrics": "",
    }
    assert response.status_code == 200, response.text
    sample = response.json()
    assert sample["caption"] == ""
    assert sample["lyrics"] == ""
    assert (ctx.audio_dir / sample["audio_path"]).read_bytes() == b"reimported take"


def test_add_sample_from_generation_rejects_audio_path_payload(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)
    take_id = _make_take(ctx)

    response = client.post(
        f"/api/loras/{lora_id}/samples/from-generation",
        json={"generation_id": take_id, "audio_path": "/etc/passwd"},
    )

    assert response.status_code == 422
    with ctx.db() as session:
        assert session.query(UserLoraSample).filter_by(user_lora_id=lora_id).count() == 0


def test_own_take_catalogue_only_returns_callers_playable_takes(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    own_take = _make_take(ctx, take_id="own-take")
    _make_take(ctx, owner_id=USER_B, take_id="foreign-take")
    _make_take(ctx, take_id="archived-take", is_archived=True)

    response = client.get("/api/loras/own-takes")

    assert response.status_code == 200
    assert response.json() == {
        "takes": [{
            "generation_id": own_take,
            "song_title": "Take song own-take",
            "generation_number": 4,
            "audio_url": f"/audio/{USER_A}/own-take.mp3",
            "caption": "Warm tenor over piano",
            "lyrics": "A line from the take",
        }],
    }


def test_admin_cannot_browse_or_copy_another_users_takes(tmp_path: Path) -> None:
    _, ctx = _build_app(tmp_path, USER_A)
    lora_id = _make_lora(ctx, USER_A)
    take_id = _make_take(ctx)
    admin = _client_for_user(ctx, "u-admin", role="admin")

    catalogue = admin.get("/api/loras/own-takes")
    response = admin.post(
        f"/api/loras/{lora_id}/samples/from-generation",
        json={"generation_id": take_id},
    )

    assert catalogue.status_code == 200
    assert catalogue.json() == {"takes": []}
    assert response.status_code == 404


def test_add_sample_happy_path(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)

    resp = client.post(
        f"/api/loras/{lora_id}/samples",
        data={"caption": "chill verse", "lyrics": "oh yeah"},
        files={"audio": ("clip.wav", b"RIFFxxxxWAVE" + b"\0" * 200, "audio/wav")},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["caption"] == "chill verse"
    assert payload["lyrics"] == "oh yeah"
    assert payload["audio_path"].endswith(".wav")
    on_disk = ctx.audio_dir / payload["audio_path"]
    assert on_disk.exists()


def test_add_sample_rejects_wrong_extension(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)

    resp = client.post(
        f"/api/loras/{lora_id}/samples",
        data={"caption": "c", "lyrics": "l"},
        files={"audio": ("clip.ogg", b"oggg", "audio/ogg")},
    )
    assert resp.status_code == 422


def test_add_sample_rejects_empty_filename(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)

    resp = client.post(
        f"/api/loras/{lora_id}/samples",
        data={"caption": "c", "lyrics": "l"},
        files={"audio": ("", b"data", "audio/wav")},
    )
    assert resp.status_code == 422


def test_add_sample_rejects_empty_file(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)

    resp = client.post(
        f"/api/loras/{lora_id}/samples",
        data={"caption": "c", "lyrics": "l"},
        files={"audio": ("clip.wav", b"", "audio/wav")},
    )
    assert resp.status_code == 422


def test_add_sample_rejects_empty_caption(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)

    resp = client.post(
        f"/api/loras/{lora_id}/samples",
        data={"caption": "   ", "lyrics": "hello"},
        files={"audio": ("c.wav", b"abc" * 50, "audio/wav")},
    )
    assert resp.status_code == 422


def test_add_sample_rejects_empty_lyrics(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)

    resp = client.post(
        f"/api/loras/{lora_id}/samples",
        data={"caption": "cap", "lyrics": "   "},
        files={"audio": ("c.wav", b"abc" * 50, "audio/wav")},
    )
    assert resp.status_code == 422


def test_add_sample_rejects_oversize(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)

    big = b"\0" * (USER_LORA_SAMPLE_MAX_BYTES + 1)
    resp = client.post(
        f"/api/loras/{lora_id}/samples",
        data={"caption": "c", "lyrics": "l"},
        files={"audio": ("clip.wav", big, "audio/wav")},
    )
    assert resp.status_code == 413


def test_add_sample_rejects_when_max_reached(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)
    with ctx.db() as session:
        for i in range(USER_LORA_MAX_SAMPLES):
            add_user_lora_sample(
                session, lora_id, f"p{i}.wav",
                caption=f"c{i}", lyrics=f"l{i}",
            )
        session.commit()

    resp = client.post(
        f"/api/loras/{lora_id}/samples",
        data={"caption": "c", "lyrics": "l"},
        files={"audio": ("c.wav", b"abc" * 100, "audio/wav")},
    )
    assert resp.status_code == 409


def test_add_sample_rejected_on_active_status(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)
    with ctx.db() as session:
        update_user_lora(session, lora_id, status=LoraStatus.TRAINING)
        session.commit()

    resp = client.post(
        f"/api/loras/{lora_id}/samples",
        data={"caption": "c", "lyrics": "l"},
        files={"audio": ("c.wav", b"abc" * 50, "audio/wav")},
    )
    assert resp.status_code == 409


def test_add_sample_rejected_on_deleted_lora(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)
    with ctx.db() as session:
        from songmaker_cli.db.queries import soft_delete_user_lora
        soft_delete_user_lora(session, lora_id)
        session.commit()

    resp = client.post(
        f"/api/loras/{lora_id}/samples",
        data={"caption": "c", "lyrics": "l"},
        files={"audio": ("c.wav", b"abc" * 50, "audio/wav")},
    )
    assert resp.status_code == 409


def test_add_sample_rollback_on_write_failure(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)

    with (
        patch("pathlib.Path.write_bytes", side_effect=OSError("disk full")),
        pytest.raises(OSError, match="disk full"),
    ):
        client.post(
            f"/api/loras/{lora_id}/samples",
            data={"caption": "c", "lyrics": "l"},
            files={"audio": ("c.wav", b"abc" * 50, "audio/wav")},
        )
    with ctx.db() as session:
        count = session.query(UserLoraSample).filter_by(user_lora_id=lora_id).count()
    assert count == 0


def test_add_sample_missing_lora_404(client_a: TestClient) -> None:
    resp = client_a.post(
        "/api/loras/missing/samples",
        data={"caption": "c", "lyrics": "l"},
        files={"audio": ("c.wav", b"abc" * 50, "audio/wav")},
    )
    assert resp.status_code == 404


def test_add_sample_cross_user_404(tmp_path: Path) -> None:
    client_a, ctx = _build_app(tmp_path, USER_A)
    lora_id = _make_lora(ctx, USER_A)

    from songmaker_cli.api import router
    app_b = FastAPI()
    app_b.state.ctx = ctx
    app_b.dependency_overrides[get_current_user] = _user_dep(USER_B)
    app_b.include_router(router)
    client_b = TestClient(app_b)
    resp = client_b.post(
        f"/api/loras/{lora_id}/samples",
        data={"caption": "c", "lyrics": "l"},
        files={"audio": ("c.wav", b"abc" * 50, "audio/wav")},
    )
    assert resp.status_code == 404


# ── Patch sample ──────────────────────────────────────────────────────


def test_patch_sample_partial_update(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)
    with ctx.db() as session:
        sample = add_user_lora_sample(
            session, lora_id, "a/1.wav", caption="old", lyrics="old lyrics",
        )
        session.commit()
        sample_id = sample.id

    resp = client.patch(
        f"/api/loras/{lora_id}/samples/{sample_id}",
        json={"caption": "new caption"},
    )
    assert resp.status_code == 200
    assert resp.json()["caption"] == "new caption"
    assert resp.json()["lyrics"] == "old lyrics"


def test_patch_sample_reorders_positions(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)
    with ctx.db() as session:
        s1 = add_user_lora_sample(session, lora_id, "a/1.wav", caption="c", lyrics="l")
        s2 = add_user_lora_sample(session, lora_id, "a/2.wav", caption="c", lyrics="l")
        s3 = add_user_lora_sample(session, lora_id, "a/3.wav", caption="c", lyrics="l")
        session.commit()
        s1_id, s2_id, s3_id = s1.id, s2.id, s3.id

    resp = client.patch(
        f"/api/loras/{lora_id}/samples/{s1_id}",
        json={"position": 2},
    )
    assert resp.status_code == 200
    with ctx.db() as session:
        positions = {
            s.id: s.position
            for s in session.query(UserLoraSample).filter_by(user_lora_id=lora_id).all()
        }
    assert positions[s2_id] == 0
    assert positions[s3_id] == 1
    assert positions[s1_id] == 2


def test_patch_sample_empty_caption_rejected(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)
    with ctx.db() as session:
        sample = add_user_lora_sample(
            session, lora_id, "a/1.wav", caption="c", lyrics="l",
        )
        session.commit()
        sample_id = sample.id

    resp = client.patch(
        f"/api/loras/{lora_id}/samples/{sample_id}",
        json={"caption": "   "},
    )
    assert resp.status_code == 422


def test_patch_sample_empty_lyrics_rejected(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)
    with ctx.db() as session:
        sample = add_user_lora_sample(
            session, lora_id, "a/1.wav", caption="c", lyrics="l",
        )
        session.commit()
        sample_id = sample.id

    resp = client.patch(
        f"/api/loras/{lora_id}/samples/{sample_id}",
        json={"lyrics": "  "},
    )
    assert resp.status_code == 422


def test_patch_sample_lora_mismatch_404(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)
    with ctx.db() as session:
        other = create_user_lora(session, USER_A, "Other", "other")
        sample = add_user_lora_sample(
            session, other.id, "a/1.wav", caption="c", lyrics="l",
        )
        session.commit()
        sample_id = sample.id

    resp = client.patch(
        f"/api/loras/{lora_id}/samples/{sample_id}",
        json={"caption": "x"},
    )
    assert resp.status_code == 404


def test_patch_sample_active_parent_rejected(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)
    with ctx.db() as session:
        sample = add_user_lora_sample(
            session, lora_id, "a/1.wav", caption="c", lyrics="l",
        )
        update_user_lora(session, lora_id, status=LoraStatus.QUEUED)
        session.commit()
        sample_id = sample.id

    resp = client.patch(
        f"/api/loras/{lora_id}/samples/{sample_id}",
        json={"caption": "x"},
    )
    assert resp.status_code == 409


def test_patch_sample_missing_404(client_a: TestClient) -> None:
    resp = client_a.patch(
        "/api/loras/any/samples/missing",
        json={"caption": "x"},
    )
    assert resp.status_code == 404


def test_patch_sample_cross_user_404(tmp_path: Path) -> None:
    client_a, ctx = _build_app(tmp_path, USER_A)
    lora_id = _make_lora(ctx, USER_A)
    with ctx.db() as session:
        sample = add_user_lora_sample(
            session, lora_id, "a/1.wav", caption="c", lyrics="l",
        )
        session.commit()
        sample_id = sample.id

    from songmaker_cli.api import router
    app_b = FastAPI()
    app_b.state.ctx = ctx
    app_b.dependency_overrides[get_current_user] = _user_dep(USER_B)
    app_b.include_router(router)
    client_b = TestClient(app_b)
    resp = client_b.patch(
        f"/api/loras/{lora_id}/samples/{sample_id}",
        json={"caption": "x"},
    )
    assert resp.status_code == 404


# ── Delete sample ─────────────────────────────────────────────────────


def test_delete_sample_removes_row_and_file(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)

    resp = client.post(
        f"/api/loras/{lora_id}/samples",
        data={"caption": "c", "lyrics": "l"},
        files={"audio": ("c.wav", b"abc" * 100, "audio/wav")},
    )
    assert resp.status_code == 200
    sample = resp.json()
    file_path = ctx.audio_dir / sample["audio_path"]
    assert file_path.exists()

    resp = client.delete(f"/api/loras/{lora_id}/samples/{sample['id']}")
    assert resp.status_code == 200
    assert not file_path.exists()

    with ctx.db() as session:
        assert (
            session.query(UserLoraSample).filter_by(id=sample["id"]).first() is None
        )


def test_delete_sample_unlink_failure_is_logged(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)
    with ctx.db() as session:
        sample = add_user_lora_sample(
            session, lora_id, "nonexistent/path.wav", caption="c", lyrics="l",
        )
        session.commit()
        sample_id = sample.id

    with patch("pathlib.Path.unlink", side_effect=OSError("boom")):
        resp = client.delete(f"/api/loras/{lora_id}/samples/{sample_id}")
    assert resp.status_code == 200


def test_delete_sample_active_parent_rejected(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)
    with ctx.db() as session:
        sample = add_user_lora_sample(
            session, lora_id, "a/1.wav", caption="c", lyrics="l",
        )
        update_user_lora(session, lora_id, status=LoraStatus.TRAINING)
        session.commit()
        sample_id = sample.id

    resp = client.delete(f"/api/loras/{lora_id}/samples/{sample_id}")
    assert resp.status_code == 409


def test_delete_sample_mismatched_lora_404(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)
    with ctx.db() as session:
        other = create_user_lora(session, USER_A, "Other", "other")
        sample = add_user_lora_sample(
            session, other.id, "a/1.wav", caption="c", lyrics="l",
        )
        session.commit()
        sample_id = sample.id

    resp = client.delete(f"/api/loras/{lora_id}/samples/{sample_id}")
    assert resp.status_code == 404


def test_delete_sample_missing_404(client_a: TestClient) -> None:
    resp = client_a.delete("/api/loras/any/samples/missing")
    assert resp.status_code == 404


def test_delete_sample_cross_user_404(tmp_path: Path) -> None:
    client_a, ctx = _build_app(tmp_path, USER_A)
    lora_id = _make_lora(ctx, USER_A)
    with ctx.db() as session:
        sample = add_user_lora_sample(
            session, lora_id, "a/1.wav", caption="c", lyrics="l",
        )
        session.commit()
        sample_id = sample.id

    from songmaker_cli.api import router
    app_b = FastAPI()
    app_b.state.ctx = ctx
    app_b.dependency_overrides[get_current_user] = _user_dep(USER_B)
    app_b.include_router(router)
    client_b = TestClient(app_b)
    resp = client_b.delete(f"/api/loras/{lora_id}/samples/{sample_id}")
    assert resp.status_code == 404


# ── Training preflight ────────────────────────────────────────────────


def _seed_trainable_lora(ctx: AppContext) -> str:
    with ctx.db() as session:
        lora = create_user_lora(session, USER_A, "Trainable", "trainable")
        for i in range(3):
            add_user_lora_sample(
                session, lora.id, f"a/{i}.wav",
                caption=f"caption {i}", lyrics=f"lyrics {i}",
            )
        session.commit()
        return lora.id


def test_train_rejects_below_min_samples(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)
    with ctx.db() as session:
        add_user_lora_sample(
            session, lora_id, "a/1.wav", caption="c", lyrics="l",
        )
        session.commit()

    resp = client.post(f"/api/loras/{lora_id}/train")
    assert resp.status_code == 422


def test_train_rejects_when_caption_or_lyrics_empty(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _make_lora(ctx)
    with ctx.db() as session:
        add_user_lora_sample(session, lora_id, "a/1.wav", caption="c", lyrics="l")
        add_user_lora_sample(session, lora_id, "a/2.wav", caption="c", lyrics="l")
        add_user_lora_sample(session, lora_id, "a/3.wav", caption="", lyrics="l")
        session.commit()

    resp = client.post(f"/api/loras/{lora_id}/train")
    assert resp.status_code == 422


def test_train_rejects_when_already_active(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _seed_trainable_lora(ctx)
    with ctx.db() as session:
        update_user_lora(session, lora_id, status=LoraStatus.TRAINING)
        session.commit()

    resp = client.post(f"/api/loras/{lora_id}/train")
    assert resp.status_code == 409


def test_train_returns_named_training_queue_limit_error(
    client_and_ctx: tuple[TestClient, AppContext], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, ctx = client_and_ctx
    monkeypatch.setenv("MAX_QUEUED_LORA_TRAINING_JOBS", "1")
    lora_id = _seed_trainable_lora(ctx)
    with ctx.db() as session:
        session.add(Job(
            id="already-waiting", type="lora_training", status=JobStatus.QUEUED,
        ))
        session.commit()

    response = client.post(f"/api/loras/{lora_id}/train")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Training queue is full\n"
        "1 trainings are already waiting. Try again when one training starts or finishes.",
        "reason": "training_queue_full",
    }


def test_train_rejects_when_soft_deleted(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _seed_trainable_lora(ctx)
    with ctx.db() as session:
        from songmaker_cli.db.queries import soft_delete_user_lora
        soft_delete_user_lora(session, lora_id)
        session.commit()

    resp = client.post(f"/api/loras/{lora_id}/train")
    assert resp.status_code == 404


def test_train_happy_path_enqueues_and_audits(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _seed_trainable_lora(ctx)

    with _mock_arq() as mock_pool:
        resp = client.post(f"/api/loras/{lora_id}/train")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == LoraStatus.QUEUED
    assert data["training_job_id"]
    mock_pool.enqueue_job.assert_awaited_once()
    call_args = mock_pool.enqueue_job.await_args[0]
    assert call_args[0] == "lora_training"
    assert call_args[2] == lora_id
    assert mock_pool.enqueue_job.await_args.kwargs["_queue_name"] == ARQ_MUSIC_QUEUE_NAME

    with ctx.db() as session:
        job = session.query(Job).filter_by(id=data["training_job_id"]).first()
        assert job is not None
        assert job.type == "lora_training"

        from songmaker_cli.db.models import AuditLog
        audits = session.query(AuditLog).filter_by(
            action="train_lora", resource_id=lora_id,
        ).all()
        assert len(audits) == 1


def test_train_enqueue_failure_marks_job_and_lora_failed(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _seed_trainable_lora(ctx)

    mock_pool = AsyncMock()
    mock_pool.enqueue_job.side_effect = ConnectionError("redis down")
    with patch("songmaker_cli.lora_api.get_arq_pool", return_value=mock_pool):
        resp = client.post(f"/api/loras/{lora_id}/train")

    assert resp.status_code == 503
    with ctx.db() as session:
        lora = session.query(UserLora).filter_by(id=lora_id).first()
        assert lora.status == LoraStatus.FAILED
        job = session.query(Job).filter_by(id=lora.training_job_id).first()
        assert job.status == JobStatus.FAILED


def test_train_enqueue_failure_exception_swallowed(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = _seed_trainable_lora(ctx)

    mock_pool = AsyncMock()
    mock_pool.enqueue_job.side_effect = ConnectionError("redis down")
    with (
        patch("songmaker_cli.lora_api.get_arq_pool", return_value=mock_pool),
        patch(
            "songmaker_cli.lora_api.update_job_status",
            side_effect=RuntimeError("nested"),
        ),
    ):
        resp = client.post(f"/api/loras/{lora_id}/train")

    assert resp.status_code == 503


def test_train_missing_lora_404(client_a: TestClient) -> None:
    resp = client_a.post("/api/loras/missing/train")
    assert resp.status_code == 404

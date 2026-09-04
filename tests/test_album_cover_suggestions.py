"""Album cover suggestion API and filesystem tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import login_and_csrf, make_test_app
from fastapi.testclient import TestClient
from PIL import Image

from songmaker_cli.auth import hash_password
from songmaker_cli.cleanup import run_cleanup_expired
from songmaker_cli.constants import (
    ALBUM_COVER_SUGGESTIONS_DIRNAME,
    ARQ_MUSIC_QUEUE_NAME,
    JSON_REQUEST_BODY_MAX_BYTES,
    JobFunction,
    JobStatus,
    JobType,
)
from songmaker_cli.cover_suggestions import remove_cover_suggestion_files
from songmaker_cli.db.models import Album, AlbumCoverSuggestion, Job, User
from songmaker_cli.db.queries import get_album
from songmaker_cli.settings import get_settings


def _png_bytes() -> bytes:
    from io import BytesIO

    payload = BytesIO()
    Image.new("RGB", (32, 32), (40, 80, 200)).save(payload, format="PNG")
    return payload.getvalue()


def _seed_albums(session) -> None:
    alice = User(username="alice", password_hash=hash_password("alicepass1"), role="user")
    bob = User(username="bob", password_hash=hash_password("bobpass12"), role="user")
    admin = User(username="admin", password_hash=hash_password("adminpass1"), role="admin")
    session.add_all([alice, bob, admin])
    session.flush()
    session.add_all([
        Album(id="alice-album", title="Alice", artist="Alice", created_by=alice.id),
        Album(id="bob-album", title="Bob", artist="Bob", created_by=bob.id),
    ])


@pytest.fixture()
def alice_app(tmp_path: Path) -> tuple[TestClient, object]:
    client, factory = make_test_app(tmp_path, seed_db=_seed_albums)
    login_and_csrf(client, "alice", "alicepass1")
    client.headers["Origin"] = "http://127.0.0.1:8080"
    return client, factory


def _add_cover_job(
    factory,
    *,
    album_id: str = "alice-album",
    status: JobStatus = JobStatus.QUEUED,
    started_at: datetime | None = None,
) -> str:
    with factory() as session:
        album = session.query(Album).filter_by(id=album_id).one()
        job = Job(
            type=JobType.COVER,
            user_id=album.created_by,
            album_id=album.id,
            status=status,
            started_at=started_at or datetime.now(timezone.utc),
        )
        session.add(job)
        session.commit()
        return job.id


def _add_suggestion(factory, audio_dir: Path, *, album_id: str = "alice-album") -> str:
    suggestion_id = "a" * 36
    path = audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME / album_id / f"{suggestion_id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_png_bytes())
    with factory() as session:
        album = session.query(Album).filter_by(id=album_id).one()
        job = Job(type=JobType.COVER, user_id=album.created_by, album_id=album.id)
        session.add(job)
        session.flush()
        session.add(AlbumCoverSuggestion(
            id=suggestion_id,
            album_id=album.id,
            job_id=job.id,
            png_path=(
                f"{ALBUM_COVER_SUGGESTIONS_DIRNAME}/{album.id}/{suggestion_id}.png"
            ),
        ))
        session.commit()
    return suggestion_id


def test_create_cover_suggestions_rejects_a_missing_worker_without_creating_a_job(
    alice_app: tuple[TestClient, object],
) -> None:
    client, factory = alice_app

    response = client.post("/api/albums/alice-album/cover-suggestions")

    assert response.status_code == 503
    assert response.json() == {"detail": "Worker not running"}
    operation = client.app.openapi()["paths"][
        "/api/albums/{album_id}/cover-suggestions"
    ]["post"]
    assert "200" in operation["responses"]
    assert operation["responses"]["503"]["description"] == "Cover suggestions are unavailable"
    with factory() as session:
        assert session.query(Job).filter_by(album_id="alice-album").count() == 0


def test_create_cover_suggestions_enqueues_a_music_worker_job(
    alice_app: tuple[TestClient, object], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory = alice_app
    calls: list[tuple] = []

    class Pool:
        async def enqueue_job(self, *args, **kwargs) -> None:
            calls.append((args, kwargs))

    async def healthy() -> bool:
        return True

    monkeypatch.setattr("songmaker_cli.album_api.is_music_worker_healthy", healthy)
    monkeypatch.setattr("songmaker_cli.album_api.get_arq_pool", lambda: Pool())

    response = client.post("/api/albums/alice-album/cover-suggestions")

    assert response.status_code == 200
    job_id = response.json()["id"]
    assert response.json()["type"] == JobType.COVER
    assert calls == [
        ((JobFunction.COVER, job_id), {"_queue_name": ARQ_MUSIC_QUEUE_NAME}),
    ]
    with factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == JobStatus.QUEUED


def test_create_cover_suggestions_replaces_stale_suggestions(
    alice_app: tuple[TestClient, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory = alice_app
    _add_suggestion(factory, tmp_path / "audio")
    with factory() as session:
        stale_job = session.query(Job).filter_by(album_id="alice-album").one()
        stale_job.status = JobStatus.COMPLETED
        session.commit()

    class Pool:
        async def enqueue_job(self, *_args, **_kwargs) -> None:
            pass

    async def healthy() -> bool:
        return True

    monkeypatch.setattr("songmaker_cli.album_api.is_music_worker_healthy", healthy)
    monkeypatch.setattr("songmaker_cli.album_api.get_arq_pool", lambda: Pool())

    response = client.post("/api/albums/alice-album/cover-suggestions")

    assert response.status_code == 200
    assert client.get("/api/albums/alice-album/cover-suggestions").json()["suggestions"] == []
    assert not (tmp_path / "audio" / ALBUM_COVER_SUGGESTIONS_DIRNAME / "alice-album").exists()


def test_create_cover_suggestions_marks_a_queue_failure_terminal(
    alice_app: tuple[TestClient, object], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory = alice_app

    class Pool:
        async def enqueue_job(self, *_args, **_kwargs) -> None:
            raise ConnectionError("redis down")

    async def healthy() -> bool:
        return True

    monkeypatch.setattr("songmaker_cli.album_api.is_music_worker_healthy", healthy)
    monkeypatch.setattr("songmaker_cli.album_api.get_arq_pool", lambda: Pool())

    response = client.post("/api/albums/alice-album/cover-suggestions")

    assert response.status_code == 503
    assert response.json() == {"detail": "Job queue unavailable"}
    with factory() as session:
        job = session.query(Job).filter_by(album_id="alice-album").one()
        assert job.status == JobStatus.FAILED
        assert job.error_type == "queue_unavailable"


def test_cover_suggestion_list_and_selection_use_the_existing_cover_writer(
    alice_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    client, factory = alice_app
    suggestion_id = _add_suggestion(factory, tmp_path / "audio")
    latest_job_id = _add_cover_job(
        factory,
        status=JobStatus.FAILED,
        started_at=datetime.now(timezone.utc) + timedelta(seconds=1),
    )

    listed = client.get("/api/albums/alice-album/cover-suggestions")

    assert listed.status_code == 200
    body = listed.json()
    assert body["job"] is not None
    assert body["job"]["id"] == latest_job_id
    assert body["job"]["type"] == JobType.COVER
    assert body["job"]["status"] == JobStatus.FAILED
    assert body["job"]["error"] is None
    assert body["used_today"] == 2
    assert body["daily_limit"] == 10
    assert body["suggestions"] == [{
        "id": suggestion_id,
        "url": f"/api/albums/alice-album/cover-suggestions/{suggestion_id}",
    }]
    assert client.get(body["suggestions"][0]["url"]).content == _png_bytes()
    selected = client.put(
        "/api/albums/alice-album/cover", json={"suggestion_id": suggestion_id},
    )
    assert selected.status_code == 200
    assert selected.json()["cover"] is not None


def test_discard_suggestions_keeps_the_selected_cover(
    alice_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    client, factory = alice_app
    suggestion_id = _add_suggestion(factory, tmp_path / "audio")
    assert client.put(
        "/api/albums/alice-album/cover", json={"suggestion_id": suggestion_id},
    ).status_code == 200
    cover_dir = tmp_path / "audio" / "covers" / "alice-album"
    assert cover_dir.is_dir()

    discarded = client.delete("/api/albums/alice-album/cover-suggestions")

    assert discarded.status_code == 200
    assert client.get("/api/albums/alice-album").json()["cover"] is not None
    assert cover_dir.is_dir()
    assert not (
        tmp_path / "audio" / ALBUM_COVER_SUGGESTIONS_DIRNAME / "alice-album"
    ).exists()


def test_delete_selected_cover_keeps_suggestions(
    alice_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    client, factory = alice_app
    suggestion_id = _add_suggestion(factory, tmp_path / "audio")
    assert client.put(
        "/api/albums/alice-album/cover", json={"suggestion_id": suggestion_id},
    ).status_code == 200

    deleted = client.delete("/api/albums/alice-album/cover")

    assert deleted.status_code == 200
    assert (
        tmp_path / "audio" / ALBUM_COVER_SUGGESTIONS_DIRNAME / "alice-album"
        / f"{suggestion_id}.png"
    ).is_file()


def test_put_cover_rejects_an_upload_without_changing_the_cover(
    alice_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    client, factory = alice_app

    response = client.put(
        "/api/albums/alice-album/cover",
        files={"file": ("cover.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 422
    with factory() as session:
        album = session.get(Album, "alice-album")
        assert album is not None
        assert album.cover_key is None
    assert not (tmp_path / "audio" / "covers" / "alice-album").exists()


def test_put_cover_keeps_json_requests_within_the_standard_body_budget(
    alice_app: tuple[TestClient, object],
) -> None:
    client, _ = alice_app
    payload = json.dumps({
        "suggestion_id": "a" * 36,
        "padding": "x" * JSON_REQUEST_BODY_MAX_BYTES,
    })

    response = client.put(
        "/api/albums/alice-album/cover",
        content=payload,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body too large"}


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/api/albums/alice-album/cover-suggestions", {}),
        ("post", "/api/albums/alice-album/cover-suggestions", {}),
        ("get", "/api/albums/alice-album/cover-suggestions/" + "a" * 36, {}),
        ("put", "/api/albums/alice-album/cover", {"json": {"suggestion_id": "a" * 36}}),
        ("delete", "/api/albums/alice-album/cover-suggestions", {}),
    ],
)
def test_foreign_cover_suggestion_routes_are_not_found(
    tmp_path: Path,
    method: str,
    path: str,
    kwargs: dict,
) -> None:
    client, factory = make_test_app(tmp_path, seed_db=_seed_albums)
    _add_suggestion(factory, tmp_path / "audio")
    login_and_csrf(client, "bob", "bobpass12")
    client.headers["Origin"] = "http://127.0.0.1:8080"

    foreign = getattr(client, method)(path, **kwargs)

    assert foreign.status_code == 404
    assert foreign.json() == {"detail": "Not Found"}


def test_cover_suggestions_have_no_public_share_route(
    alice_app: tuple[TestClient, object],
) -> None:
    client, _ = alice_app

    response = client.get("/shared/album-slug/cover-suggestions")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_owner_cannot_distinguish_missing_and_traversal_suggestions(
    alice_app: tuple[TestClient, object],
) -> None:
    client, factory = alice_app

    missing = client.get("/api/albums/alice-album/cover-suggestions/missing")
    traversal = client.get(
        "/api/albums/alice-album/cover-suggestions/%2E%2E%2Foutside.png",
    )

    assert missing.status_code == traversal.status_code == 404
    assert missing.json() == traversal.json() == {"detail": "Not Found"}
    with factory() as session:
        assert session.query(AlbumCoverSuggestion).count() == 0


def test_admin_can_list_and_read_another_users_suggestion(tmp_path: Path) -> None:
    client, factory = make_test_app(tmp_path, seed_db=_seed_albums)
    suggestion_id = _add_suggestion(factory, tmp_path / "audio")
    login_and_csrf(client, "admin", "adminpass1")
    client.headers["Origin"] = "http://127.0.0.1:8080"

    listed = client.get("/api/albums/alice-album/cover-suggestions")
    fetched = client.get(
        f"/api/albums/alice-album/cover-suggestions/{suggestion_id}",
    )

    assert listed.status_code == 200
    assert listed.json()["suggestions"][0]["id"] == suggestion_id
    assert fetched.status_code == 200
    assert fetched.content == _png_bytes()


def test_active_cover_job_blocks_a_new_request_before_unavailable_response(
    alice_app: tuple[TestClient, object],
) -> None:
    client, factory = alice_app
    _add_cover_job(factory)

    response = client.post("/api/albums/alice-album/cover-suggestions")

    assert response.status_code == 409
    assert response.json() == {"detail": "Cover suggestions are already being generated"}
    with factory() as session:
        assert session.query(Job).filter_by(album_id="alice-album").count() == 1


def test_failed_cover_jobs_since_utc_midnight_count_toward_the_daily_limit(
    alice_app: tuple[TestClient, object], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory = alice_app
    monkeypatch.setenv("COVER_SUGGESTIONS_DAILY_LIMIT", "1")
    get_settings.cache_clear()
    utc_midnight = datetime(2026, 9, 4, tzinfo=timezone.utc)

    class FixedUtcDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz == timezone.utc
            return utc_midnight + timedelta(microseconds=1)

    monkeypatch.setattr("songmaker_cli.album_api.datetime", FixedUtcDateTime)
    _add_cover_job(
        factory,
        status=JobStatus.FAILED,
        started_at=utc_midnight - timedelta(microseconds=1),
    )
    _add_cover_job(
        factory,
        status=JobStatus.FAILED,
        started_at=utc_midnight,
    )

    listed = client.get("/api/albums/alice-album/cover-suggestions")
    limited = client.post("/api/albums/alice-album/cover-suggestions")

    assert listed.status_code == 200
    assert listed.json()["used_today"] == 1
    assert limited.status_code == 429


def test_hard_delete_cleanup_removes_suggestions_from_expired_albums(
    alice_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    client, factory = alice_app
    _add_suggestion(factory, tmp_path / "audio")
    suggestion_dir = tmp_path / "audio" / ALBUM_COVER_SUGGESTIONS_DIRNAME / "alice-album"

    assert client.delete("/api/albums/alice-album").status_code == 200
    with factory() as session:
        album = get_album(session, "alice-album", include_deleted_rows=True)
        assert album is not None
        album.deleted_at = datetime.now(timezone.utc) - timedelta(days=366)
        session.commit()

    album_count, song_count = run_cleanup_expired(factory, tmp_path / "audio")

    assert (album_count, song_count) == (1, 0)
    assert not suggestion_dir.exists()


def test_user_hard_delete_removes_album_suggestions_after_the_commit(tmp_path: Path) -> None:
    client, factory = make_test_app(tmp_path, seed_db=_seed_albums)
    _add_suggestion(factory, tmp_path / "audio")
    suggestion_dir = tmp_path / "audio" / ALBUM_COVER_SUGGESTIONS_DIRNAME / "alice-album"
    with factory() as session:
        alice = session.query(User).filter_by(username="alice").one()
        alice_id = alice.id
    login_and_csrf(client, "admin", "adminpass1")
    client.headers["Origin"] = "http://127.0.0.1:8080"

    response = client.delete(f"/api/admin/users/{alice_id}/permanent")

    assert response.status_code == 200
    assert not suggestion_dir.exists()


def test_suggestion_cleanup_refuses_paths_outside_its_private_tree(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    marker = tmp_path / "marker.png"
    marker.write_bytes(_png_bytes())

    remove_cover_suggestion_files(audio_dir, ["../marker.png", "covers/album/original.png"])

    assert marker.exists()

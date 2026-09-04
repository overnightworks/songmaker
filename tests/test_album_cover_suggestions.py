"""Album cover suggestion API and filesystem tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import login_and_csrf, make_test_app
from fastapi.testclient import TestClient
from PIL import Image

from songmaker_cli.auth import hash_password
from songmaker_cli.constants import ALBUM_COVER_SUGGESTIONS_DIRNAME, JobStatus, JobType
from songmaker_cli.cover_suggestions import remove_cover_suggestion_files
from songmaker_cli.db.models import Album, AlbumCoverSuggestion, Job, User
from songmaker_cli.settings import get_settings


def _png_bytes() -> bytes:
    from io import BytesIO

    payload = BytesIO()
    Image.new("RGB", (32, 32), (40, 80, 200)).save(payload, format="PNG")
    return payload.getvalue()


def _seed_albums(session) -> None:
    alice = User(username="alice", password_hash=hash_password("alicepass1"), role="user")
    bob = User(username="bob", password_hash=hash_password("bobpass12"), role="user")
    session.add_all([alice, bob])
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


def test_create_cover_suggestions_creates_an_album_scoped_cover_job(
    alice_app: tuple[TestClient, object],
) -> None:
    client, factory = alice_app

    response = client.post("/api/albums/alice-album/cover-suggestions")

    assert response.status_code == 200
    assert response.json()["type"] == JobType.COVER
    with factory() as session:
        job = session.query(Job).filter_by(id=response.json()["id"]).one()
        assert job.album_id == "alice-album"
        assert job.status == JobStatus.QUEUED


def test_cover_suggestion_list_and_selection_use_the_existing_cover_writer(
    alice_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    client, factory = alice_app
    suggestion_id = _add_suggestion(factory, tmp_path / "audio")

    listed = client.get("/api/albums/alice-album/cover-suggestions")

    assert listed.status_code == 200
    body = listed.json()
    assert body["used_today"] == 1
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

    discarded = client.delete("/api/albums/alice-album/cover-suggestions")

    assert discarded.status_code == 200
    assert client.get("/api/albums/alice-album").json()["cover"] is not None
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


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/api/albums/alice-album/cover-suggestions", {}),
        ("post", "/api/albums/alice-album/cover-suggestions", {}),
        ("get", "/api/albums/alice-album/cover-suggestions/missing", {}),
        ("put", "/api/albums/alice-album/cover", {"json": {"suggestion_id": "missing"}}),
        ("delete", "/api/albums/alice-album/cover-suggestions", {}),
    ],
)
def test_foreign_cover_suggestion_routes_are_not_found(
    tmp_path: Path,
    method: str,
    path: str,
    kwargs: dict,
) -> None:
    client, _ = make_test_app(tmp_path, seed_db=_seed_albums)
    login_and_csrf(client, "bob", "bobpass12")
    client.headers["Origin"] = "http://127.0.0.1:8080"

    foreign = getattr(client, method)(path, **kwargs)

    assert foreign.status_code == 404
    assert foreign.json() == {"detail": "Not Found"}


def test_active_cover_job_is_not_counted_against_the_daily_limit(
    alice_app: tuple[TestClient, object], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory = alice_app
    monkeypatch.setenv("COVER_SUGGESTIONS_DAILY_LIMIT", "1")
    get_settings.cache_clear()
    first = client.post("/api/albums/alice-album/cover-suggestions")
    assert first.status_code == 200

    second = client.post("/api/albums/alice-album/cover-suggestions")

    assert second.status_code == 409
    with factory() as session:
        job = session.query(Job).filter_by(id=first.json()["id"]).one()
        job.status = JobStatus.COMPLETED
        session.commit()
    limited = client.post("/api/albums/alice-album/cover-suggestions")
    assert limited.status_code == 429


def test_suggestion_cleanup_refuses_paths_outside_its_private_tree(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    marker = tmp_path / "marker.png"
    marker.write_bytes(_png_bytes())

    remove_cover_suggestion_files(audio_dir, ["../marker.png", "covers/album/original.png"])

    assert marker.exists()

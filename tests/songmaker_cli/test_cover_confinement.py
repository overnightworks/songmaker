"""Covers and cover suggestions confine every file they serve, store and delete."""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from support.web_app import make_test_app, seed_session, seed_user

from songmaker_cli.constants import (
    ALBUM_COVER_SUGGESTIONS_DIRNAME,
    COVER_DIRNAME,
)
from songmaker_cli.cover_suggestions import (
    remove_album_cover_suggestion_files,
    remove_cover_suggestion_files,
)
from songmaker_cli.db.models import Album

ALBUM_ID = "alice-album"
COVER_URL = f"/api/albums/{ALBUM_ID}/cover"
ORIGINAL_URL = f"{COVER_URL}?variant=original"
TRAVERSAL_LOG = "Path traversal blocked in cover delete"
SUGGESTION_RELATIVE = f"{ALBUM_COVER_SUGGESTIONS_DIRNAME}/{ALBUM_ID}/s1.png"


def _tiny_png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 24), (40, 80, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def _seed_alice_album(session) -> None:
    alice = seed_user(session, "alice", role="user")
    session.add(Album(id=ALBUM_ID, title="Alice Album", artist="Alice", created_by=alice.id))


def _post_cover(client: TestClient):
    return client.post(COVER_URL, files={"file": ("cover.png", _tiny_png(), "image/png")})


@pytest.fixture
def alice_client(tmp_path: Path) -> TestClient:
    client, _ = make_test_app(tmp_path, seed_db=_seed_alice_album)
    seed_session(client, "alice")
    return client


@pytest.fixture
def audio_dir(tmp_path: Path) -> Path:
    return tmp_path / "audio"


@pytest.fixture
def elsewhere(tmp_path: Path) -> Path:
    """A folder beside the audio folder, holding a file nothing may touch."""
    folder = tmp_path / "elsewhere"
    folder.mkdir()
    (folder / "original.png").write_bytes(_tiny_png())
    (folder / "keep.txt").write_text("keep")
    return folder


def _link_covers_folder(audio_dir: Path, target: Path) -> Path:
    target.mkdir(exist_ok=True)
    (audio_dir / COVER_DIRNAME).symlink_to(target, target_is_directory=True)
    return target


def _link_entity_folder(audio_dir: Path, target: Path) -> None:
    (audio_dir / COVER_DIRNAME).mkdir(parents=True, exist_ok=True)
    (audio_dir / COVER_DIRNAME / ALBUM_ID).symlink_to(target, target_is_directory=True)


def test_a_cover_file_below_its_album_folder_is_served(alice_client: TestClient) -> None:
    assert _post_cover(alice_client).status_code == 200
    assert alice_client.get(ORIGINAL_URL).status_code == 200


def test_an_original_that_links_to_the_covers_folder_is_not_found(
    alice_client: TestClient,
    audio_dir: Path,
) -> None:
    assert _post_cover(alice_client).status_code == 200
    original = audio_dir / COVER_DIRNAME / ALBUM_ID / "original.png"
    original.unlink()
    original.symlink_to(audio_dir / COVER_DIRNAME, target_is_directory=True)
    response = alice_client.get(ORIGINAL_URL)
    assert response.status_code == 404


def test_an_album_folder_linking_outside_the_covers_folder_is_not_served(
    alice_client: TestClient,
    audio_dir: Path,
    elsewhere: Path,
) -> None:
    assert _post_cover(alice_client).status_code == 200
    (audio_dir / COVER_DIRNAME / ALBUM_ID).rename(audio_dir / "moved")
    _link_entity_folder(audio_dir, elsewhere)
    assert alice_client.get(ORIGINAL_URL).status_code == 404


def test_an_album_folder_linking_to_another_folder_inside_is_served(
    alice_client: TestClient,
    audio_dir: Path,
) -> None:
    assert _post_cover(alice_client).status_code == 200
    real = audio_dir / COVER_DIRNAME / ALBUM_ID
    inside = audio_dir / COVER_DIRNAME / "shared-store"
    real.rename(inside)
    real.symlink_to(inside, target_is_directory=True)
    assert alice_client.get(ORIGINAL_URL).status_code == 200


def test_a_covers_folder_that_is_a_link_still_serves_its_covers(
    alice_client: TestClient,
    audio_dir: Path,
    tmp_path: Path,
) -> None:
    assert _post_cover(alice_client).status_code == 200
    stored = audio_dir / COVER_DIRNAME
    mount = tmp_path / "mount"
    stored.rename(mount)
    stored.symlink_to(mount, target_is_directory=True)
    assert alice_client.get(ORIGINAL_URL).status_code == 200


def test_a_covers_folder_that_is_a_link_loop_is_not_found(
    alice_client: TestClient,
    audio_dir: Path,
) -> None:
    assert _post_cover(alice_client).status_code == 200
    stored = audio_dir / COVER_DIRNAME
    stored.rename(audio_dir / "moved")
    stored.symlink_to(stored, target_is_directory=True)
    assert alice_client.get(ORIGINAL_URL).status_code == 404


def test_an_album_folder_linking_outside_rejects_a_new_cover_and_writes_nothing_outside(
    alice_client: TestClient,
    audio_dir: Path,
    elsewhere: Path,
) -> None:
    _link_entity_folder(audio_dir, elsewhere)
    before = sorted(path.name for path in elsewhere.iterdir())
    assert _post_cover(alice_client).status_code == 422
    assert sorted(path.name for path in elsewhere.iterdir()) == before


def test_a_new_cover_is_stored(alice_client: TestClient, audio_dir: Path) -> None:
    assert _post_cover(alice_client).status_code == 200
    assert (audio_dir / COVER_DIRNAME / ALBUM_ID / "original.png").is_file()


def test_a_covers_folder_that_is_a_link_still_stores_covers(
    alice_client: TestClient,
    audio_dir: Path,
    tmp_path: Path,
) -> None:
    mount = _link_covers_folder(audio_dir, tmp_path / "mount")
    assert _post_cover(alice_client).status_code == 200
    assert (mount / ALBUM_ID / "original.png").is_file()


def test_deleting_an_album_cover_removes_its_folder(
    alice_client: TestClient,
    audio_dir: Path,
) -> None:
    assert _post_cover(alice_client).status_code == 200
    assert alice_client.delete(COVER_URL).status_code == 200
    assert not (audio_dir / COVER_DIRNAME / ALBUM_ID).exists()


def test_deleting_a_cover_skips_an_album_folder_linking_outside(
    alice_client: TestClient,
    audio_dir: Path,
    elsewhere: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert _post_cover(alice_client).status_code == 200
    (audio_dir / COVER_DIRNAME / ALBUM_ID).rename(audio_dir / "moved")
    _link_entity_folder(audio_dir, elsewhere)
    with caplog.at_level(logging.WARNING):
        alice_client.delete(COVER_URL)
    assert TRAVERSAL_LOG in caplog.text
    assert (elsewhere / "keep.txt").read_text() == "keep"
    assert (elsewhere / "original.png").is_file()


def test_a_covers_folder_that_is_a_link_still_deletes_covers(
    alice_client: TestClient,
    audio_dir: Path,
    tmp_path: Path,
) -> None:
    assert _post_cover(alice_client).status_code == 200
    stored = audio_dir / COVER_DIRNAME
    mount = tmp_path / "mount"
    stored.rename(mount)
    stored.symlink_to(mount, target_is_directory=True)
    assert alice_client.delete(COVER_URL).status_code == 200
    assert not (mount / ALBUM_ID).exists()


def _suggestion(audio_dir: Path, relative: str = SUGGESTION_RELATIVE) -> Path:
    path = audio_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_tiny_png())
    return path


def test_a_suggestion_png_is_removed(audio_dir: Path) -> None:
    path = _suggestion(audio_dir)
    remove_cover_suggestion_files(audio_dir, [SUGGESTION_RELATIVE])
    assert not path.exists()


def test_a_png_outside_the_suggestions_folder_is_skipped_with_a_warning(
    audio_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    other = _suggestion(audio_dir, "elsewhere-in-audio/x.png")
    with caplog.at_level(logging.WARNING):
        remove_cover_suggestion_files(audio_dir, ["elsewhere-in-audio/x.png"])
    assert "outside suggestion root" in caplog.text
    assert other.is_file()


def test_an_albums_suggestion_folder_is_removed(audio_dir: Path) -> None:
    path = _suggestion(audio_dir)
    remove_album_cover_suggestion_files(audio_dir, ALBUM_ID)
    assert not path.parent.exists()


def test_an_albums_suggestion_folder_linking_out_is_not_removed(
    audio_dir: Path,
    elsewhere: Path,
) -> None:
    (audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME).mkdir(parents=True)
    (audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME / ALBUM_ID).symlink_to(
        elsewhere,
        target_is_directory=True,
    )
    remove_album_cover_suggestion_files(audio_dir, ALBUM_ID)
    assert (elsewhere / "keep.txt").read_text() == "keep"


def test_an_albums_suggestion_folder_linking_into_the_audio_folder_is_not_removed(
    audio_dir: Path,
) -> None:
    sibling = audio_dir / "other-takes"
    sibling.mkdir(parents=True)
    (sibling / "keep.txt").write_text("keep")
    (audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME).mkdir()
    (audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME / ALBUM_ID).symlink_to(
        sibling,
        target_is_directory=True,
    )
    remove_album_cover_suggestion_files(audio_dir, ALBUM_ID)
    assert (sibling / "keep.txt").read_text() == "keep"

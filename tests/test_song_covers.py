"""Song cover upload, serving, sharing, cleanup, and confinement."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest
from conftest import login_and_csrf, make_test_app
from fastapi.testclient import TestClient
from PIL import Image

from songmaker_cli.auth import hash_password
from songmaker_cli.cleanup import run_cleanup_expired
from songmaker_cli.constants import (
    AUDIO_UPLOAD_BODY_MAX_BYTES,
    COVER_INVALID_SONG_ID,
    COVER_JPEG_EXTENSION,
    COVER_KEY_PNG,
    COVER_MAX_BYTES,
    COVER_OLD_DIRNAME_SUFFIX,
    COVER_PNG_EXTENSION,
    COVER_STAGING_DIRNAME_SUFFIX,
    COVER_TOO_MANY_PIXELS,
    COVER_UNSUPPORTED_TYPE,
    COVER_UPLOAD_BODY_MAX_BYTES,
    COVER_VARIANT_CARD,
    COVER_VARIANT_DETAIL,
    COVER_VARIANT_ORIGINAL,
    COVER_VARIANT_UNKNOWN,
    REIMPORT_BODY_MAX_BYTES,
    SONG_COVER_DIRNAME,
)
from songmaker_cli.covers import (
    CoverRejectedError,
    remove_song_cover_files,
    resolve_song_cover_file,
    write_album_cover,
    write_song_cover,
)
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, Song, User
from songmaker_cli.db.queries import (
    create_user,
    get_song,
    soft_delete_album,
    soft_delete_song,
)
from songmaker_cli.middleware.body_size import body_limit_for_path, is_large_upload_path
from songmaker_cli.settings import get_settings

ALICE_PASSWORD = "alicepass1"
BOB_PASSWORD = "bobpass12"

UNSAFE_COVER_SONG_IDS = ("", ".", "..", "/tmp", "a/b")


def _cover_escape_layout(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    marker = audio_dir / "marker.txt"
    marker.write_text("keep")
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    sibling_marker = sibling / "marker.txt"
    sibling_marker.write_text("keep")
    legit = audio_dir / SONG_COVER_DIRNAME / "alice-song"
    legit.mkdir(parents=True)
    (legit / "keep.txt").write_text("keep")
    return audio_dir, marker, sibling_marker, legit


def _jpeg_bytes(
    size: tuple[int, int] = (32, 24),
    color: tuple[int, int, int] = (200, 40, 40),
) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _png_bytes(
    size: tuple[int, int] = (32, 24),
    color: tuple[int, int, int] = (40, 80, 200),
) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _png_header(width: int, height: int) -> bytes:
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


def _seed_owners(session) -> None:
    alice = create_user(session, "alice", hash_password(ALICE_PASSWORD), role="user")
    bob = create_user(session, "bob", hash_password(BOB_PASSWORD), role="user")
    session.add(Album(id="alice-album", title="Alice Album", artist="Alice", created_by=alice.id))
    session.add(Album(id="bob-album", title="Bob Album", artist="Bob", created_by=bob.id))
    session.add(Song(id="alice-song", title="Alice Song", album_id="alice-album", track_number=1))
    session.add(Song(id="bob-song", title="Bob Song", album_id="bob-album", track_number=1))


def _authed_app(tmp_path: Path, username: str, password: str) -> tuple[TestClient, object]:
    client, factory = make_test_app(tmp_path, seed_db=_seed_owners)
    login_and_csrf(client, username, password)
    client.headers["Origin"] = "http://127.0.0.1:8080"
    return client, factory


@pytest.fixture()
def alice_app(tmp_path: Path) -> tuple[TestClient, object]:
    return _authed_app(tmp_path, "alice", ALICE_PASSWORD)


def test_song_cover_upload_path_is_cover_sized_and_reimport_unchanged() -> None:
    assert is_large_upload_path("/api/songs/alice-song/cover")
    assert not is_large_upload_path("/api/songs/alice-song/cover/extra")
    assert not is_large_upload_path("/api/songs//cover")
    assert body_limit_for_path("/api/songs/alice-song/cover") == COVER_UPLOAD_BODY_MAX_BYTES
    assert is_large_upload_path("/api/songs/alice-song/reimport")
    assert body_limit_for_path("/api/songs/alice-song/reimport") == REIMPORT_BODY_MAX_BYTES
    assert COVER_UPLOAD_BODY_MAX_BYTES != REIMPORT_BODY_MAX_BYTES
    assert COVER_UPLOAD_BODY_MAX_BYTES > COVER_MAX_BYTES
    assert is_large_upload_path("/api/audio/upload")
    assert body_limit_for_path("/api/audio/upload") == AUDIO_UPLOAD_BODY_MAX_BYTES
    assert AUDIO_UPLOAD_BODY_MAX_BYTES != COVER_UPLOAD_BODY_MAX_BYTES


def test_write_song_cover_creates_original_and_derivatives(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    cover_key = write_song_cover(audio_dir, "alice-song", _png_bytes())
    assert cover_key.endswith(f".{COVER_KEY_PNG}")
    song_dir = audio_dir / SONG_COVER_DIRNAME / "alice-song"
    assert (song_dir / f"{COVER_VARIANT_ORIGINAL}{COVER_PNG_EXTENSION}").is_file()
    assert (song_dir / f"{COVER_VARIANT_CARD}{COVER_JPEG_EXTENSION}").is_file()
    assert (song_dir / f"{COVER_VARIANT_DETAIL}{COVER_JPEG_EXTENSION}").is_file()
    assert not (audio_dir / "covers" / "alice-song").exists()


def test_upload_jpeg_and_png_song_cover_and_get_variants(
    alice_app: tuple[TestClient, object],
) -> None:
    client, _ = alice_app
    jpeg = client.post(
        "/api/songs/alice-song/cover",
        files={"file": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert jpeg.status_code == 200, jpeg.text
    data = jpeg.json()
    assert data["cover"]["card"].startswith("/api/songs/alice-song/cover?variant=card")
    assert data["cover"]["detail"].startswith("/api/songs/alice-song/cover?variant=detail")
    assert "/api/albums/" not in data["cover"]["card"]
    card = client.get(data["cover"]["card"])
    detail = client.get(data["cover"]["detail"])
    original = client.get("/api/songs/alice-song/cover?variant=original")
    assert card.status_code == 200
    assert card.headers["content-type"].startswith("image/jpeg")
    assert detail.status_code == 200
    assert original.status_code == 200
    png = client.post(
        "/api/songs/alice-song/cover",
        files={"file": ("cover.png", _png_bytes(), "image/png")},
    )
    assert png.status_code == 200, png.text
    original = client.get("/api/songs/alice-song/cover?variant=original")
    assert original.status_code == 200
    assert original.headers["content-type"].startswith("image/png")


def test_upload_rejects_svg_and_webp(alice_app: tuple[TestClient, object]) -> None:
    client, _ = alice_app
    svg = client.post(
        "/api/songs/alice-song/cover",
        files={
            "file": (
                "cover.svg",
                b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
                "image/svg+xml",
            ),
        },
    )
    assert svg.status_code == 422
    assert svg.json()["detail"] == COVER_UNSUPPORTED_TYPE
    webp = client.post(
        "/api/songs/alice-song/cover",
        files={"file": ("cover.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp")},
    )
    assert webp.status_code == 422
    assert webp.json()["detail"] == COVER_UNSUPPORTED_TYPE


def test_upload_rejects_too_many_pixels(alice_app: tuple[TestClient, object]) -> None:
    client, _ = alice_app
    from songmaker_cli.constants import COVER_MAX_PIXELS

    resp = client.post(
        "/api/songs/alice-song/cover",
        files={"file": ("bomb.png", _png_header(COVER_MAX_PIXELS + 1, 1), "image/png")},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == COVER_TOO_MANY_PIXELS


def test_foreign_song_cover_is_404(tmp_path: Path) -> None:
    client, _ = _authed_app(tmp_path, "bob", BOB_PASSWORD)
    jpeg = _jpeg_bytes()
    for method, path in (
        ("GET", "/api/songs/alice-song/cover"),
        ("POST", "/api/songs/alice-song/cover"),
        ("DELETE", "/api/songs/alice-song/cover"),
    ):
        if method == "POST":
            resp = client.post(path, files={"file": ("cover.jpg", jpeg, "image/jpeg")})
        elif method == "DELETE":
            resp = client.delete(path)
        else:
            resp = client.get(path)
        assert resp.status_code == 404, (method, resp.text)


def test_song_cover_json_is_own_urls_or_null_never_album(
    alice_app: tuple[TestClient, object],
) -> None:
    client, _ = alice_app
    album = client.post(
        "/api/albums/alice-album/cover",
        files={"file": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert album.status_code == 200, album.text
    assert album.json()["cover"] is not None
    song = client.get("/api/songs/alice-song")
    assert song.status_code == 200
    assert song.json()["cover"] is None
    listed = client.get("/api/songs?album_id=alice-album")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert items[0]["cover"] is None
    assert client.get("/api/songs/alice-song/cover").status_code == 404
    uploaded = client.post(
        "/api/songs/alice-song/cover",
        files={"file": ("cover.png", _png_bytes(), "image/png")},
    )
    assert uploaded.status_code == 200
    cover = uploaded.json()["cover"]
    assert cover["card"].startswith("/api/songs/alice-song/cover")
    assert cover["detail"].startswith("/api/songs/alice-song/cover")
    assert "/api/albums/" not in cover["card"]
    assert "/api/albums/" not in cover["detail"]


def test_public_song_cover_404s_when_song_has_no_own_file(
    alice_app: tuple[TestClient, object],
) -> None:
    client, _ = alice_app
    album = client.post(
        "/api/albums/alice-album/cover",
        files={"file": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert album.status_code == 200
    shared = client.post("/api/songs/alice-song/share")
    assert shared.status_code == 200, shared.text
    slug = shared.json()["share_slug"]
    public = TestClient(client.app, cookies={})
    body = public.get(f"/shared/song/{slug}")
    assert body.status_code == 200
    assert body.json()["cover"] is None
    assert public.get(f"/shared/song/{slug}/cover").status_code == 404
    uploaded = client.post(
        "/api/songs/alice-song/cover",
        files={"file": ("cover.png", _png_bytes(), "image/png")},
    )
    assert uploaded.status_code == 200
    owned_key = uploaded.json()["cover"]["card"].rsplit("v=", 1)[-1]
    public_json = public.get(f"/shared/song/{slug}")
    assert public_json.status_code == 200
    cover = public_json.json()["cover"]
    assert cover is not None
    assert cover["detail"].startswith(f"/shared/song/{slug}/cover")
    served = public.get(cover["detail"])
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/jpeg")
    stale = public.get(f"/shared/song/{slug}/cover?variant=detail&v={owned_key}xxxx")
    assert stale.status_code == 404


def test_replace_404s_old_public_version(
    alice_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    client, _ = alice_app
    first = client.post(
        "/api/songs/alice-song/cover",
        files={"file": ("cover.png", _png_bytes(), "image/png")},
    )
    assert first.status_code == 200, first.text
    old_key = first.json()["cover"]["card"].rsplit("v=", 1)[-1]
    shared = client.post("/api/songs/alice-song/share")
    slug = shared.json()["share_slug"]
    public = TestClient(client.app, cookies={})
    old_public = f"/shared/song/{slug}/cover?variant={COVER_VARIANT_CARD}&v={old_key}"
    assert public.get(old_public).status_code == 200
    song_dir = tmp_path / "audio" / SONG_COVER_DIRNAME / "alice-song"
    png_path = song_dir / f"{COVER_VARIANT_ORIGINAL}{COVER_PNG_EXTENSION}"
    assert png_path.is_file()
    second = client.post(
        "/api/songs/alice-song/cover",
        files={"file": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert second.status_code == 200, second.text
    new_key = second.json()["cover"]["card"].rsplit("v=", 1)[-1]
    assert new_key != old_key
    assert not png_path.exists()
    assert public.get(old_public).status_code == 404
    assert client.get(
        f"/api/songs/alice-song/cover?variant={COVER_VARIANT_CARD}&v={old_key}",
    ).status_code == 404
    fresh = client.get(second.json()["cover"]["card"])
    assert fresh.status_code == 200


def test_delete_song_cover_does_not_remove_album_cover(
    alice_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    client, _ = alice_app
    album = client.post(
        "/api/albums/alice-album/cover",
        files={"file": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert album.status_code == 200
    uploaded = client.post(
        "/api/songs/alice-song/cover",
        files={"file": ("cover.png", _png_bytes(), "image/png")},
    )
    assert uploaded.status_code == 200
    deleted = client.delete("/api/songs/alice-song/cover")
    assert deleted.status_code == 200
    assert deleted.json()["cover"] is None
    assert not (tmp_path / "audio" / SONG_COVER_DIRNAME / "alice-song").exists()
    assert client.get("/api/albums/alice-album/cover?variant=detail").status_code == 200


def test_unknown_variant_is_422(alice_app: tuple[TestClient, object]) -> None:
    client, _ = alice_app
    client.post(
        "/api/songs/alice-song/cover",
        files={"file": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    resp = client.get("/api/songs/alice-song/cover?variant=huge")
    assert resp.status_code == 422
    assert resp.json()["detail"] == COVER_VARIANT_UNKNOWN


def test_moving_song_does_not_move_cover_files(
    alice_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    client, factory = alice_app
    uploaded = client.post(
        "/api/songs/alice-song/cover",
        files={"file": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert uploaded.status_code == 200
    with factory() as session:
        other = Album(
            id="alice-other", title="Other", artist="Alice",
            created_by=session.query(User).filter_by(username="alice").one().id,
        )
        session.add(other)
        session.commit()
    moved = client.put("/api/songs/alice-song/album", json={"album_id": "alice-other"})
    assert moved.status_code == 200, moved.text
    song_dir = tmp_path / "audio" / SONG_COVER_DIRNAME / "alice-song"
    assert song_dir.is_dir()
    assert client.get("/api/songs/alice-song/cover?variant=detail").status_code == 200


def test_song_cleanup_of_unpicked_takes_does_not_touch_covers(
    alice_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    client, _ = alice_app
    uploaded = client.post(
        "/api/songs/alice-song/cover",
        files={"file": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert uploaded.status_code == 200
    cleaned = client.post("/api/songs/alice-song/cleanup")
    assert cleaned.status_code == 200
    song_dir = tmp_path / "audio" / SONG_COVER_DIRNAME / "alice-song"
    assert song_dir.is_dir()
    assert client.get("/api/songs/alice-song/cover?variant=detail").status_code == 200


def test_soft_delete_song_keeps_cover_files(
    alice_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    client, _ = alice_app
    uploaded = client.post(
        "/api/songs/alice-song/cover",
        files={"file": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert uploaded.status_code == 200
    song_dir = tmp_path / "audio" / SONG_COVER_DIRNAME / "alice-song"
    assert song_dir.is_dir()
    deleted = client.delete("/api/songs/alice-song")
    assert deleted.status_code == 200
    assert song_dir.is_dir()
    restored = client.post("/api/songs/alice-song/restore")
    assert restored.status_code == 200
    assert client.get("/api/songs/alice-song/cover?variant=detail").status_code == 200


def test_cleanup_expired_unlinks_orphan_and_album_song_covers(tmp_path: Path) -> None:
    factory = init_db(tmp_path / "covers.db")
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    with factory() as session:
        owner = create_user(session, "alice", hash_password(ALICE_PASSWORD))
        session.add(Album(id="expired-album", title="Expired", artist="A", created_by=owner.id))
        session.add(Album(id="live-album", title="Live", artist="A", created_by=owner.id))
        session.add(
            Song(id="expired-song", title="Expired", album_id="expired-album", track_number=1),
        )
        session.add(Song(id="orphan-song", title="Orphan", album_id="live-album", track_number=1))
        session.add(Song(id="live-song", title="Live", album_id="live-album", track_number=2))
        session.commit()

    write_album_cover(audio_dir, "expired-album", _jpeg_bytes())
    write_album_cover(audio_dir, "live-album", _png_bytes())
    write_song_cover(audio_dir, "expired-song", _jpeg_bytes())
    write_song_cover(audio_dir, "orphan-song", _png_bytes())
    write_song_cover(audio_dir, "live-song", _jpeg_bytes())
    expired_album_dir = audio_dir / "covers" / "expired-album"
    live_album_dir = audio_dir / "covers" / "live-album"
    expired_song_dir = audio_dir / SONG_COVER_DIRNAME / "expired-song"
    orphan_dir = audio_dir / SONG_COVER_DIRNAME / "orphan-song"
    live_song_dir = audio_dir / SONG_COVER_DIRNAME / "live-song"

    past = datetime.now(timezone.utc) - timedelta(
        days=get_settings().soft_delete_retention_days + 1,
    )
    with factory() as session:
        soft_delete_album(session, "expired-album")
        album = session.query(Album).execution_options(include_deleted=True).filter_by(
            id="expired-album",
        ).one()
        album.deleted_at = past
        soft_delete_song(session, "orphan-song")
        orphan = get_song(session, "orphan-song", include_deleted_rows=True)
        assert orphan is not None
        orphan.deleted_at = past
        session.commit()

    album_count, song_count = run_cleanup_expired(factory, audio_dir)
    assert album_count == 1
    assert song_count == 1
    assert not expired_album_dir.exists()
    assert not expired_song_dir.exists()
    assert not orphan_dir.exists()
    assert live_album_dir.is_dir()
    assert live_song_dir.is_dir()


def test_hard_delete_user_unlinks_song_covers_including_soft_deleted(tmp_path: Path) -> None:
    def seed(session) -> None:
        create_user(session, "admin", hash_password("admin12345"), role="admin")
        victim = create_user(session, "victim", hash_password("victimpass1"), role="user")
        session.add(Album(id="live-album", title="Live", artist="V", created_by=victim.id))
        session.add(Song(id="live-song", title="Live", album_id="live-album", track_number=1))
        session.add(Song(id="gone-song", title="Gone", album_id="live-album", track_number=2))

    client, factory = make_test_app(tmp_path, seed_db=seed)
    audio_dir = tmp_path / "audio"
    write_song_cover(audio_dir, "live-song", _jpeg_bytes())
    write_song_cover(audio_dir, "gone-song", _png_bytes())
    live_dir = audio_dir / SONG_COVER_DIRNAME / "live-song"
    gone_dir = audio_dir / SONG_COVER_DIRNAME / "gone-song"
    assert live_dir.is_dir()
    assert gone_dir.is_dir()

    with factory() as session:
        victim = session.query(User).filter_by(username="victim").one()
        victim_id = victim.id
        soft_delete_song(session, "gone-song")
        session.commit()

    login_and_csrf(client, "admin", "admin12345")
    resp = client.delete(f"/api/admin/users/{victim_id}/permanent")
    assert resp.status_code == 200, resp.text
    assert not live_dir.exists()
    assert not gone_dir.exists()


def _assert_escape_markers_survive(
    audio_dir: Path, marker: Path, sibling_marker: Path, legit: Path,
) -> None:
    assert marker.read_text() == "keep"
    assert sibling_marker.read_text() == "keep"
    assert (legit / "keep.txt").read_text() == "keep"
    assert audio_dir.is_dir()


@pytest.mark.parametrize("song_id", UNSAFE_COVER_SONG_IDS)
def test_write_song_cover_rejects_unsafe_song_ids(tmp_path: Path, song_id: str) -> None:
    audio_dir, marker, sibling_marker, legit = _cover_escape_layout(tmp_path)
    with pytest.raises(CoverRejectedError, match=COVER_INVALID_SONG_ID):
        write_song_cover(audio_dir, song_id, _png_bytes())
    _assert_escape_markers_survive(audio_dir, marker, sibling_marker, legit)


@pytest.mark.parametrize("song_id", UNSAFE_COVER_SONG_IDS)
def test_remove_song_cover_files_rejects_unsafe_song_ids(
    tmp_path: Path, song_id: str,
) -> None:
    audio_dir, marker, sibling_marker, legit = _cover_escape_layout(tmp_path)
    remove_song_cover_files(audio_dir, song_id)
    _assert_escape_markers_survive(audio_dir, marker, sibling_marker, legit)


def test_remove_song_cover_files_does_not_rmtree_audio_dir(tmp_path: Path) -> None:
    audio_dir, marker, sibling_marker, legit = _cover_escape_layout(tmp_path)
    nested = audio_dir / "other"
    nested.mkdir()
    (nested / "file.txt").write_text("keep")
    remove_song_cover_files(audio_dir, "..")
    _assert_escape_markers_survive(audio_dir, marker, sibling_marker, legit)
    assert (nested / "file.txt").read_text() == "keep"


@pytest.mark.parametrize("song_id", UNSAFE_COVER_SONG_IDS)
def test_resolve_song_cover_file_rejects_unsafe_song_ids(
    tmp_path: Path, song_id: str,
) -> None:
    audio_dir, marker, sibling_marker, legit = _cover_escape_layout(tmp_path)
    with pytest.raises(FileNotFoundError):
        resolve_song_cover_file(
            audio_dir, song_id, "deadbeef.png", COVER_VARIANT_ORIGINAL,
        )
    _assert_escape_markers_survive(audio_dir, marker, sibling_marker, legit)


def test_write_song_cover_restores_live_dir_if_publish_rename_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_dir = tmp_path / "audio"
    first_key = write_song_cover(audio_dir, "alice-song", _png_bytes())
    song_dir = audio_dir / SONG_COVER_DIRNAME / "alice-song"
    original = (song_dir / f"{COVER_VARIANT_ORIGINAL}{COVER_PNG_EXTENSION}").read_bytes()
    real_rename = Path.rename

    def rename_fails_staging_publish(self: Path, target: Path | str) -> Path:
        target_path = Path(target)
        if self.name.endswith(COVER_STAGING_DIRNAME_SUFFIX) and target_path.name == "alice-song":
            raise OSError("simulated publish failure")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", rename_fails_staging_publish)
    with pytest.raises(OSError, match="simulated publish failure"):
        write_song_cover(audio_dir, "alice-song", _jpeg_bytes())
    assert song_dir.is_dir()
    assert (song_dir / f"{COVER_VARIANT_ORIGINAL}{COVER_PNG_EXTENSION}").read_bytes() == original
    served = resolve_song_cover_file(
        audio_dir, "alice-song", first_key, COVER_VARIANT_ORIGINAL,
    )
    assert served.is_file()


def test_write_song_cover_replaces_when_leftover_old_exists(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    write_song_cover(audio_dir, "alice-song", _png_bytes())
    covers = audio_dir / SONG_COVER_DIRNAME
    final = covers / "alice-song"
    old = covers / f".alice-song{COVER_OLD_DIRNAME_SUFFIX}"
    old.mkdir()
    (old / "stale.txt").write_text("stale")
    assert final.is_dir()
    assert old.is_dir()
    cover_key = write_song_cover(audio_dir, "alice-song", _jpeg_bytes())
    assert not old.exists()
    served = resolve_song_cover_file(
        audio_dir, "alice-song", cover_key, COVER_VARIANT_ORIGINAL,
    )
    assert served.is_file()
    assert served.name == f"{COVER_VARIANT_ORIGINAL}{COVER_JPEG_EXTENSION}"


def test_write_song_cover_restores_orphaned_old_before_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_dir = tmp_path / "audio"
    write_song_cover(audio_dir, "alice-song", _png_bytes())
    covers = audio_dir / SONG_COVER_DIRNAME
    final = covers / "alice-song"
    old = covers / f".alice-song{COVER_OLD_DIRNAME_SUFFIX}"
    original = (final / f"{COVER_VARIANT_ORIGINAL}{COVER_PNG_EXTENSION}").read_bytes()
    final.rename(old)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated save failure")

    monkeypatch.setattr("songmaker_cli.covers._save_variants", boom)
    with pytest.raises(OSError, match="simulated save failure"):
        write_song_cover(audio_dir, "alice-song", _jpeg_bytes())
    assert final.is_dir()
    assert (final / f"{COVER_VARIANT_ORIGINAL}{COVER_PNG_EXTENSION}").read_bytes() == original

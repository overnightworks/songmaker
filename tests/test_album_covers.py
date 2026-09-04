"""Album cover upload, serving, sharing, and validation."""

from __future__ import annotations

import struct
import zlib
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
    COVER_DIRNAME,
    COVER_INVALID_ALBUM_ID,
    COVER_JPEG_EXTENSION,
    COVER_JPEG_MAGIC,
    COVER_KEY_PNG,
    COVER_MAX_BYTES,
    COVER_MAX_PIXELS,
    COVER_OLD_DIRNAME_SUFFIX,
    COVER_PNG_EXTENSION,
    COVER_STAGING_DIRNAME_SUFFIX,
    COVER_TOO_LARGE,
    COVER_TOO_MANY_PIXELS,
    COVER_UNSUPPORTED_TYPE,
    COVER_UPLOAD_BODY_MAX_BYTES,
    COVER_VARIANT_CARD,
    COVER_VARIANT_DETAIL,
    COVER_VARIANT_ORIGINAL,
    COVER_VARIANT_UNKNOWN,
    JSON_REQUEST_BODY_MAX_BYTES,
)
from songmaker_cli.covers import (
    CoverRejectedError,
    decode_cover_image,
    remove_album_cover_files,
    resolve_cover_file,
    write_album_cover,
)
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, User
from songmaker_cli.db.queries import create_user, get_album, soft_delete_album
from songmaker_cli.middleware.body_size import body_limit_for_path, is_large_upload_path
from songmaker_cli.settings import get_settings

ALICE_PASSWORD = "alicepass1"

UNSAFE_COVER_ALBUM_IDS = ("", ".", "..", "/tmp", "a/b")


def _cover_escape_layout(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    marker = audio_dir / "marker.txt"
    marker.write_text("keep")
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    sibling_marker = sibling / "marker.txt"
    sibling_marker.write_text("keep")
    legit = audio_dir / COVER_DIRNAME / "alice-album"
    legit.mkdir(parents=True)
    (legit / "keep.txt").write_text("keep")
    return audio_dir, marker, sibling_marker, legit


BOB_PASSWORD = "bobpass12"


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
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


def _jpeg_with_orientation(orientation: int) -> bytes:
    img = Image.new("RGB", (20, 10), (255, 0, 0))
    img.putpixel((0, 0), (0, 0, 255))
    exif = img.getexif()
    exif[274] = orientation
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _seed_owners(session) -> None:
    alice = create_user(session, "alice", hash_password(ALICE_PASSWORD), role="user")
    bob = create_user(session, "bob", hash_password(BOB_PASSWORD), role="user")
    session.add(Album(id="alice-album", title="Alice Album", artist="Alice", created_by=alice.id))
    session.add(Album(id="bob-album", title="Bob Album", artist="Bob", created_by=bob.id))


def _authed_app(tmp_path: Path, username: str, password: str) -> tuple[TestClient, object]:
    client, factory = make_test_app(tmp_path, seed_db=_seed_owners)
    login_and_csrf(client, username, password)
    client.headers["Origin"] = "http://127.0.0.1:8080"
    return client, factory


@pytest.fixture()
def alice_app(tmp_path: Path) -> tuple[TestClient, object]:
    return _authed_app(tmp_path, "alice", ALICE_PASSWORD)


def test_cover_upload_path_is_large_and_sized_to_cover_budget() -> None:
    assert is_large_upload_path("/api/albums/alice-album/cover")
    assert not is_large_upload_path("/api/albums/alice-album/cover", "PUT")
    assert not is_large_upload_path("/api/albums/alice-album/cover/extra")
    assert not is_large_upload_path("/api/albums//cover")
    assert body_limit_for_path("/api/albums/alice-album/cover") == COVER_UPLOAD_BODY_MAX_BYTES
    assert (
        body_limit_for_path("/api/albums/alice-album/cover", "PUT")
        == JSON_REQUEST_BODY_MAX_BYTES
    )
    assert COVER_UPLOAD_BODY_MAX_BYTES > JSON_REQUEST_BODY_MAX_BYTES
    assert COVER_UPLOAD_BODY_MAX_BYTES > COVER_MAX_BYTES


def test_decode_rejects_svg_and_webp() -> None:
    with pytest.raises(CoverRejectedError, match=COVER_UNSUPPORTED_TYPE):
        decode_cover_image(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>')
    with pytest.raises(CoverRejectedError, match=COVER_UNSUPPORTED_TYPE):
        decode_cover_image(b"RIFF\x00\x00\x00\x00WEBPVP8 ")


def test_decode_rejects_oversize_bytes() -> None:
    payload = COVER_JPEG_MAGIC + b"\x00" * COVER_MAX_BYTES
    with pytest.raises(CoverRejectedError, match=COVER_TOO_LARGE) as exc:
        decode_cover_image(payload)
    assert exc.value.status_code == 413


def test_decode_rejects_image_bomb() -> None:
    width = COVER_MAX_PIXELS + 1
    payload = _png_header(width, 1)
    with pytest.raises(CoverRejectedError, match=COVER_TOO_MANY_PIXELS):
        decode_cover_image(payload)


def test_decode_applies_exif_orientation_and_strips_it() -> None:
    image, fmt = decode_cover_image(_jpeg_with_orientation(6))
    assert fmt == "jpeg"
    assert image.size == (10, 20)
    assert image.getexif().get(274) in (None, 1)


def test_write_album_cover_creates_original_and_derivatives(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    cover_key = write_album_cover(audio_dir, "alice-album", _png_bytes())
    assert cover_key.endswith(f".{COVER_KEY_PNG}")
    album_dir = audio_dir / COVER_DIRNAME / "alice-album"
    assert (album_dir / f"{COVER_VARIANT_ORIGINAL}{COVER_PNG_EXTENSION}").is_file()
    assert (album_dir / f"{COVER_VARIANT_CARD}{COVER_JPEG_EXTENSION}").is_file()
    assert (album_dir / f"{COVER_VARIANT_DETAIL}{COVER_JPEG_EXTENSION}").is_file()


def test_upload_jpeg_cover_and_get_variants(alice_app: tuple[TestClient, object]) -> None:
    client, _ = alice_app
    resp = client.post(
        "/api/albums/alice-album/cover",
        files={"file": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["cover"]["card"].startswith("/api/albums/alice-album/cover?variant=card")
    assert data["cover"]["detail"].startswith("/api/albums/alice-album/cover?variant=detail")
    card = client.get(data["cover"]["card"])
    detail = client.get(data["cover"]["detail"])
    original = client.get("/api/albums/alice-album/cover?variant=original")
    assert card.status_code == 200
    assert card.headers["content-type"].startswith("image/jpeg")
    assert detail.status_code == 200
    assert original.status_code == 200
    assert original.headers["content-type"].startswith("image/jpeg")


def test_upload_rejects_svg(alice_app: tuple[TestClient, object]) -> None:
    client, _ = alice_app
    resp = client.post(
        "/api/albums/alice-album/cover",
        files={
            "file": (
                "cover.svg",
                b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
                "image/svg+xml",
            ),
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == COVER_UNSUPPORTED_TYPE


def test_upload_rejects_too_many_pixels(alice_app: tuple[TestClient, object]) -> None:
    client, _ = alice_app
    resp = client.post(
        "/api/albums/alice-album/cover",
        files={"file": ("bomb.png", _png_header(COVER_MAX_PIXELS + 1, 1), "image/png")},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == COVER_TOO_MANY_PIXELS


def test_upload_rejects_oversize_file(alice_app: tuple[TestClient, object]) -> None:
    client, _ = alice_app
    payload = COVER_JPEG_MAGIC + b"\x00" * COVER_MAX_BYTES
    resp = client.post(
        "/api/albums/alice-album/cover",
        files={"file": ("huge.jpg", payload, "image/jpeg")},
    )
    assert resp.status_code in {413, 422}


def test_foreign_album_cover_is_404(tmp_path: Path) -> None:
    client, _ = _authed_app(tmp_path, "bob", BOB_PASSWORD)
    jpeg = _jpeg_bytes()
    for method, path in (
        ("GET", "/api/albums/alice-album/cover"),
        ("POST", "/api/albums/alice-album/cover"),
        ("DELETE", "/api/albums/alice-album/cover"),
    ):
        if method == "POST":
            resp = client.post(path, files={"file": ("cover.jpg", jpeg, "image/jpeg")})
        elif method == "DELETE":
            resp = client.delete(path)
        else:
            resp = client.get(path)
        assert resp.status_code == 404, (method, resp.text)


def test_replace_unlinks_previous_original(
    alice_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    client, _ = alice_app
    first = client.post(
        "/api/albums/alice-album/cover",
        files={"file": ("cover.png", _png_bytes(), "image/png")},
    )
    assert first.status_code == 200, first.text
    old_key = first.json()["cover"]["card"].rsplit("v=", 1)[-1]
    album_dir = tmp_path / "audio" / COVER_DIRNAME / "alice-album"
    png_path = album_dir / f"{COVER_VARIANT_ORIGINAL}{COVER_PNG_EXTENSION}"
    assert png_path.is_file()
    second = client.post(
        "/api/albums/alice-album/cover",
        files={"file": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert second.status_code == 200, second.text
    new_key = second.json()["cover"]["card"].rsplit("v=", 1)[-1]
    assert new_key != old_key
    assert not png_path.exists()
    jpg_path = album_dir / f"{COVER_VARIANT_ORIGINAL}{COVER_JPEG_EXTENSION}"
    assert jpg_path.is_file()
    stale = client.get(f"/api/albums/alice-album/cover?variant={COVER_VARIANT_CARD}&v={old_key}")
    assert stale.status_code == 404
    fresh = client.get(second.json()["cover"]["card"])
    assert fresh.status_code == 200


def test_delete_cover_unlinks_files(alice_app: tuple[TestClient, object], tmp_path: Path) -> None:
    client, _ = alice_app
    uploaded = client.post(
        "/api/albums/alice-album/cover",
        files={"file": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert uploaded.status_code == 200
    cover_url = uploaded.json()["cover"]["detail"]
    deleted = client.delete("/api/albums/alice-album/cover")
    assert deleted.status_code == 200
    assert deleted.json()["cover"] is None
    album_dir = tmp_path / "audio" / COVER_DIRNAME / "alice-album"
    assert not album_dir.exists()
    assert client.get(cover_url).status_code == 404


def test_unknown_variant_is_422(alice_app: tuple[TestClient, object]) -> None:
    client, _ = alice_app
    client.post(
        "/api/albums/alice-album/cover",
        files={"file": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    resp = client.get("/api/albums/alice-album/cover?variant=huge")
    assert resp.status_code == 422
    assert resp.json()["detail"] == COVER_VARIANT_UNKNOWN


def test_missing_cover_file_get_is_404_and_public_json_omits_cover(
    alice_app: tuple[TestClient, object],
) -> None:
    client, factory = alice_app
    uploaded = client.post(
        "/api/albums/alice-album/cover",
        files={"file": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert uploaded.status_code == 200
    with factory() as session:
        album = session.query(Album).filter_by(id="alice-album").one()
        album_dir = Path(client.app.state.ctx.audio_dir) / COVER_DIRNAME / "alice-album"
        for child in album_dir.iterdir():
            child.unlink()
        album_dir.rmdir()
        cover_key = album.cover_key
    owned = client.get("/api/albums/alice-album")
    assert owned.status_code == 200
    assert owned.json()["cover"] is not None
    assert client.get(owned.json()["cover"]["detail"]).status_code == 404
    shared = client.post("/api/albums/alice-album/share")
    slug = shared.json()["share_slug"]
    public = TestClient(client.app, cookies={})
    public_json = public.get(f"/shared/{slug}")
    assert public_json.status_code == 200
    assert public_json.json()["cover"] is None
    assert public.get(f"/shared/{slug}/cover?v={cover_key}").status_code == 404


def test_public_cover_follows_share_gate(alice_app: tuple[TestClient, object]) -> None:
    client, _ = alice_app
    uploaded = client.post(
        "/api/albums/alice-album/cover",
        files={"file": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert uploaded.status_code == 200
    shared = client.post("/api/albums/alice-album/share")
    slug = shared.json()["share_slug"]
    public = TestClient(client.app, cookies={})
    body = public.get(f"/shared/{slug}")
    assert body.status_code == 200
    cover = body.json()["cover"]
    assert cover["detail"].startswith(f"/shared/{slug}/cover")
    served = public.get(cover["detail"])
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/jpeg")
    client.delete("/api/albums/alice-album/share")
    assert public.get(f"/shared/{slug}").status_code == 404
    assert public.get(cover["detail"]).status_code == 404


def test_soft_delete_album_keeps_cover_files(
    alice_app: tuple[TestClient, object], tmp_path: Path,
) -> None:
    client, _ = alice_app
    uploaded = client.post(
        "/api/albums/alice-album/cover",
        files={"file": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert uploaded.status_code == 200
    album_dir = tmp_path / "audio" / COVER_DIRNAME / "alice-album"
    assert album_dir.is_dir()
    deleted = client.delete("/api/albums/alice-album")
    assert deleted.status_code == 200
    assert album_dir.is_dir()
    restored = client.post("/api/albums/alice-album/restore")
    assert restored.status_code == 200
    assert client.get("/api/albums/alice-album/cover?variant=detail").status_code == 200


def test_cleanup_expired_removes_album_cover_files(tmp_path: Path) -> None:
    factory = init_db(tmp_path / "covers.db")
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    with factory() as session:
        owner = create_user(session, "alice", hash_password(ALICE_PASSWORD))
        session.add(Album(id="expired-album", title="Expired", artist="A", created_by=owner.id))
        session.add(Album(id="live-album", title="Live", artist="A", created_by=owner.id))
        session.commit()

    write_album_cover(audio_dir, "expired-album", _jpeg_bytes())
    write_album_cover(audio_dir, "live-album", _png_bytes())
    expired_dir = audio_dir / COVER_DIRNAME / "expired-album"
    live_dir = audio_dir / COVER_DIRNAME / "live-album"
    assert expired_dir.is_dir()
    assert live_dir.is_dir()

    with factory() as session:
        soft_delete_album(session, "expired-album")
        album = get_album(session, "expired-album", include_deleted_rows=True)
        assert album is not None
        album.deleted_at = datetime.now(timezone.utc) - timedelta(
            days=get_settings().soft_delete_retention_days + 1,
        )
        session.commit()

    album_count, song_count = run_cleanup_expired(factory, audio_dir)
    assert album_count == 1
    assert song_count == 0
    assert not expired_dir.exists()
    assert live_dir.is_dir()


def test_hard_delete_user_removes_album_cover_files(tmp_path: Path) -> None:
    def seed(session) -> None:
        create_user(session, "admin", hash_password("admin12345"), role="admin")
        victim = create_user(session, "victim", hash_password("victimpass1"), role="user")
        session.add(Album(id="live-album", title="Live", artist="V", created_by=victim.id))
        session.add(Album(id="gone-album", title="Gone", artist="V", created_by=victim.id))

    client, factory = make_test_app(tmp_path, seed_db=seed)
    audio_dir = tmp_path / "audio"
    write_album_cover(audio_dir, "live-album", _jpeg_bytes())
    write_album_cover(audio_dir, "gone-album", _png_bytes())
    live_dir = audio_dir / COVER_DIRNAME / "live-album"
    gone_dir = audio_dir / COVER_DIRNAME / "gone-album"
    assert live_dir.is_dir()
    assert gone_dir.is_dir()

    with factory() as session:
        victim = session.query(User).filter_by(username="victim").one()
        victim_id = victim.id
        soft_delete_album(session, "gone-album")
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


@pytest.mark.parametrize("album_id", UNSAFE_COVER_ALBUM_IDS)
def test_write_album_cover_rejects_unsafe_album_ids(
    tmp_path: Path, album_id: str,
) -> None:
    audio_dir, marker, sibling_marker, legit = _cover_escape_layout(tmp_path)
    with pytest.raises(CoverRejectedError, match=COVER_INVALID_ALBUM_ID):
        write_album_cover(audio_dir, album_id, _png_bytes())
    _assert_escape_markers_survive(audio_dir, marker, sibling_marker, legit)


@pytest.mark.parametrize("album_id", UNSAFE_COVER_ALBUM_IDS)
def test_remove_album_cover_files_rejects_unsafe_album_ids(
    tmp_path: Path, album_id: str,
) -> None:
    audio_dir, marker, sibling_marker, legit = _cover_escape_layout(tmp_path)
    remove_album_cover_files(audio_dir, album_id)
    _assert_escape_markers_survive(audio_dir, marker, sibling_marker, legit)


def test_remove_album_cover_files_does_not_rmtree_audio_dir(tmp_path: Path) -> None:
    audio_dir, marker, sibling_marker, legit = _cover_escape_layout(tmp_path)
    nested = audio_dir / "other"
    nested.mkdir()
    (nested / "file.txt").write_text("keep")
    remove_album_cover_files(audio_dir, "..")
    _assert_escape_markers_survive(audio_dir, marker, sibling_marker, legit)
    assert (nested / "file.txt").read_text() == "keep"


@pytest.mark.parametrize("album_id", UNSAFE_COVER_ALBUM_IDS)
def test_resolve_cover_file_rejects_unsafe_album_ids(
    tmp_path: Path, album_id: str,
) -> None:
    audio_dir, marker, sibling_marker, legit = _cover_escape_layout(tmp_path)
    with pytest.raises(FileNotFoundError):
        resolve_cover_file(
            audio_dir, album_id, "deadbeef.png", COVER_VARIANT_ORIGINAL,
        )
    _assert_escape_markers_survive(audio_dir, marker, sibling_marker, legit)


def test_write_album_cover_restores_live_dir_if_publish_rename_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_dir = tmp_path / "audio"
    first_key = write_album_cover(audio_dir, "alice-album", _png_bytes())
    album_dir = audio_dir / COVER_DIRNAME / "alice-album"
    original = (album_dir / f"{COVER_VARIANT_ORIGINAL}{COVER_PNG_EXTENSION}").read_bytes()
    real_rename = Path.rename

    def rename_fails_staging_publish(self: Path, target: Path | str) -> Path:
        target_path = Path(target)
        if self.name.endswith(COVER_STAGING_DIRNAME_SUFFIX) and target_path.name == "alice-album":
            raise OSError("simulated publish failure")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", rename_fails_staging_publish)
    with pytest.raises(OSError, match="simulated publish failure"):
        write_album_cover(audio_dir, "alice-album", _jpeg_bytes())
    assert album_dir.is_dir()
    assert (album_dir / f"{COVER_VARIANT_ORIGINAL}{COVER_PNG_EXTENSION}").read_bytes() == original
    served = resolve_cover_file(
        audio_dir, "alice-album", first_key, COVER_VARIANT_ORIGINAL,
    )
    assert served.is_file()


def test_write_album_cover_restores_orphaned_old_before_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_dir = tmp_path / "audio"
    write_album_cover(audio_dir, "alice-album", _png_bytes())
    covers = audio_dir / COVER_DIRNAME
    final = covers / "alice-album"
    old = covers / f".alice-album{COVER_OLD_DIRNAME_SUFFIX}"
    original = (final / f"{COVER_VARIANT_ORIGINAL}{COVER_PNG_EXTENSION}").read_bytes()
    final.rename(old)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated save failure")

    monkeypatch.setattr("songmaker_cli.covers._save_variants", boom)
    with pytest.raises(OSError, match="simulated save failure"):
        write_album_cover(audio_dir, "alice-album", _jpeg_bytes())
    assert final.is_dir()
    assert (final / f"{COVER_VARIANT_ORIGINAL}{COVER_PNG_EXTENSION}").read_bytes() == original


def test_write_album_cover_replaces_when_leftover_old_exists(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    write_album_cover(audio_dir, "alice-album", _png_bytes())
    covers = audio_dir / COVER_DIRNAME
    final = covers / "alice-album"
    old = covers / f".alice-album{COVER_OLD_DIRNAME_SUFFIX}"
    old.mkdir()
    (old / "stale.txt").write_text("stale")
    assert final.is_dir()
    assert old.is_dir()
    cover_key = write_album_cover(audio_dir, "alice-album", _jpeg_bytes())
    assert not old.exists()
    served = resolve_cover_file(
        audio_dir, "alice-album", cover_key, COVER_VARIANT_ORIGINAL,
    )
    assert served.is_file()
    assert served.name == f"{COVER_VARIANT_ORIGINAL}{COVER_JPEG_EXTENSION}"


def test_write_album_cover_leaves_foreign_staging_dir(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    covers = audio_dir / COVER_DIRNAME
    foreign_uuid = covers / f".alice-album.deadbeef{COVER_STAGING_DIRNAME_SUFFIX}"
    foreign_plain = covers / f".alice-album{COVER_STAGING_DIRNAME_SUFFIX}"
    foreign_uuid.mkdir(parents=True)
    foreign_plain.mkdir(parents=True)
    (foreign_uuid / "keep.txt").write_text("keep")
    (foreign_plain / "keep.txt").write_text("keep")
    write_album_cover(audio_dir, "alice-album", _png_bytes())
    assert (foreign_uuid / "keep.txt").read_text() == "keep"
    assert (foreign_plain / "keep.txt").read_text() == "keep"
    assert (covers / "alice-album").is_dir()


def test_remove_album_cover_files_removes_live_old_and_staging(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    write_album_cover(audio_dir, "alice-album", _png_bytes())
    write_album_cover(audio_dir, "live-album", _jpeg_bytes())
    covers = audio_dir / COVER_DIRNAME
    old = covers / f".alice-album{COVER_OLD_DIRNAME_SUFFIX}"
    leftover_uuid = covers / f".alice-album.deadbeef{COVER_STAGING_DIRNAME_SUFFIX}"
    leftover_plain = covers / f".alice-album{COVER_STAGING_DIRNAME_SUFFIX}"
    old.mkdir()
    leftover_uuid.mkdir()
    leftover_plain.mkdir()
    (old / "x").write_text("x")
    remove_album_cover_files(audio_dir, "alice-album")
    assert not (covers / "alice-album").exists()
    assert not old.exists()
    assert not leftover_uuid.exists()
    assert not leftover_plain.exists()
    assert (covers / "live-album").is_dir()

"""Cover validation, derivatives, and on-disk layout."""

from __future__ import annotations

import logging
import shutil
import uuid
from enum import StrEnum
from io import BytesIO
from pathlib import Path
from typing import Final

from PIL import Image, ImageOps
from PIL.PngImagePlugin import PngInfo

from audio_engine.constants import IPTC_TRAINED_ALGORITHMIC_MEDIA
from songmaker_cli.audio_paths import confined_under
from songmaker_cli.constants import (
    COVER_MAX_BYTES,
    COVER_VARIANT_CARD,
    COVER_VARIANT_DETAIL,
)

# The iTXt keyword under which PNG carries an XMP packet (XMP spec, part 3).
XMP_PNG_KEYWORD: Final = "XML:com.adobe.xmp"
AI_MARK_XMP_PACKET: Final = (
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description rdf:about="" '
    'xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/" '
    f'Iptc4xmpExt:DigitalSourceType="{IPTC_TRAINED_ALGORITHMIC_MEDIA}"/>'
    "</rdf:RDF></x:xmpmeta>"
)


def ai_mark_png_info() -> PngInfo:
    metadata = PngInfo()
    metadata.add_itxt(XMP_PNG_KEYWORD, AI_MARK_XMP_PACKET)
    return metadata

log = logging.getLogger(__name__)

COVER_DIRNAME: Final[str] = "covers"
SONG_COVER_DIRNAME: Final[str] = "song-covers"
PLAYLIST_COVER_DIRNAME: Final[str] = "playlist-covers"
COVER_MAX_PIXELS: Final[int] = 20_000_000
COVER_CARD_MAX_EDGE: Final[int] = 512
COVER_DETAIL_MAX_EDGE: Final[int] = 1024
COVER_JPEG_QUALITY: Final[int] = 85
COVER_VARIANT_ORIGINAL: Final[str] = "original"
COVER_VARIANTS: Final[frozenset[str]] = frozenset({
    COVER_VARIANT_ORIGINAL,
    COVER_VARIANT_CARD,
    COVER_VARIANT_DETAIL,
})
COVER_KEY_JPEG: Final[str] = "jpg"
COVER_KEY_PNG: Final[str] = "png"
COVER_JPEG_EXTENSION: Final[str] = ".jpg"
COVER_PNG_EXTENSION: Final[str] = ".png"
COVER_JPEG_MAGIC: Final[bytes] = b"\xff\xd8\xff"
COVER_PNG_MAGIC: Final[bytes] = b"\x89PNG\r\n\x1a\n"
COVER_FORMAT_JPEG: Final[str] = "jpeg"
COVER_FORMAT_PNG: Final[str] = "png"
COVER_MEDIA_TYPE_JPEG: Final[str] = "image/jpeg"
COVER_MEDIA_TYPE_PNG: Final[str] = "image/png"
COVER_CACHE_CONTROL: Final[str] = "no-store"
COVER_OLD_DIRNAME_SUFFIX: Final[str] = ".old"
COVER_STAGING_DIRNAME_SUFFIX: Final[str] = ".staging"

COVER_RESPONSE_HEADERS: dict[str, str] = {"Cache-Control": COVER_CACHE_CONTROL}
_COVER_REJECTED_IDS: Final[frozenset[str]] = frozenset({".", ".."})
_COVER_PATH_TRAVERSAL_LOG = "Path traversal blocked in cover delete for category: %s"


class CoverRejection(StrEnum):
    """Why a cover is refused; the route owns the sentence and the status."""

    TOO_LARGE = "tooLarge"
    UNREADABLE = "unreadable"
    UNSUPPORTED_TYPE = "unsupportedType"
    TOO_MANY_PIXELS = "tooManyPixels"
    VARIANT_UNKNOWN = "variantUnknown"
    INVALID_ALBUM_ID = "invalidAlbumId"
    INVALID_SONG_ID = "invalidSongId"
    INVALID_PLAYLIST_ID = "invalidPlaylistId"


class CoverRejectedError(Exception):
    def __init__(self, reason: CoverRejection) -> None:
        super().__init__(reason.value)
        self.reason = reason


def sniff_cover_format(payload: bytes) -> str | None:
    if payload.startswith(COVER_JPEG_MAGIC):
        return COVER_FORMAT_JPEG
    if payload.startswith(COVER_PNG_MAGIC):
        return COVER_FORMAT_PNG
    return None


def cover_key_extension(cover_key: str | None) -> str | None:
    if cover_key is None or "." not in cover_key:
        return None
    return cover_key.rsplit(".", 1)[-1]


def new_cover_key(fmt: str) -> str:
    ext = COVER_KEY_JPEG if fmt == COVER_FORMAT_JPEG else COVER_KEY_PNG
    return f"{uuid.uuid4().hex}.{ext}"


def cover_media_type(variant: str, cover_key: str) -> str:
    if variant == COVER_VARIANT_ORIGINAL and cover_key_extension(cover_key) == COVER_KEY_PNG:
        return COVER_MEDIA_TYPE_PNG
    return COVER_MEDIA_TYPE_JPEG


def album_cover_file_exists(audio_dir: Path, album_id: str, cover_key: str | None) -> bool:
    return _cover_file_exists(
        audio_dir, COVER_DIRNAME, album_id, cover_key, CoverRejection.INVALID_ALBUM_ID,
    )


def song_cover_file_exists(audio_dir: Path, song_id: str, cover_key: str | None) -> bool:
    return _cover_file_exists(
        audio_dir, SONG_COVER_DIRNAME, song_id, cover_key, CoverRejection.INVALID_SONG_ID,
    )


def playlist_cover_file_exists(
    audio_dir: Path, playlist_id: str, cover_key: str | None,
) -> bool:
    return _cover_file_exists(
        audio_dir, PLAYLIST_COVER_DIRNAME, playlist_id, cover_key,
        CoverRejection.INVALID_PLAYLIST_ID,
    )


def resolve_cover_file(
    audio_dir: Path, album_id: str, cover_key: str | None, variant: str,
) -> Path:
    return _resolve_cover_file(
        audio_dir, COVER_DIRNAME, album_id, cover_key, variant, CoverRejection.INVALID_ALBUM_ID,
    )


def resolve_song_cover_file(
    audio_dir: Path, song_id: str, cover_key: str | None, variant: str,
) -> Path:
    return _resolve_cover_file(
        audio_dir, SONG_COVER_DIRNAME, song_id, cover_key, variant, CoverRejection.INVALID_SONG_ID,
    )


def resolve_playlist_cover_file(
    audio_dir: Path, playlist_id: str, cover_key: str | None, variant: str,
) -> Path:
    return _resolve_cover_file(
        audio_dir, PLAYLIST_COVER_DIRNAME, playlist_id, cover_key, variant,
        CoverRejection.INVALID_PLAYLIST_ID,
    )


def decode_cover_image(payload: bytes) -> tuple[Image.Image, str]:
    if len(payload) > COVER_MAX_BYTES:
        raise CoverRejectedError(CoverRejection.TOO_LARGE)
    if not payload:
        raise CoverRejectedError(CoverRejection.UNREADABLE)
    fmt = sniff_cover_format(payload)
    if fmt is None:
        raise CoverRejectedError(CoverRejection.UNSUPPORTED_TYPE)
    try:
        with Image.open(BytesIO(payload)) as raw:
            if raw.width * raw.height > COVER_MAX_PIXELS:
                raise CoverRejectedError(CoverRejection.TOO_MANY_PIXELS)
            raw.load()
            oriented = ImageOps.exif_transpose(raw)
            normalized = _normalized_original(oriented, fmt)
            return normalized.copy(), fmt
    except CoverRejectedError:
        raise
    except Image.DecompressionBombError as exc:
        raise CoverRejectedError(CoverRejection.TOO_MANY_PIXELS) from exc
    except (OSError, ValueError, SyntaxError, IndexError) as exc:
        raise CoverRejectedError(CoverRejection.UNREADABLE) from exc


def write_album_cover(
    audio_dir: Path, album_id: str, payload: bytes, *, ai_generated: bool = False,
) -> str:
    return write_cover(
        audio_dir, COVER_DIRNAME, album_id, payload,
        invalid_id=CoverRejection.INVALID_ALBUM_ID, ai_generated=ai_generated,
    )


def write_song_cover(audio_dir: Path, song_id: str, payload: bytes) -> str:
    return write_cover(
        audio_dir, SONG_COVER_DIRNAME, song_id, payload,
        invalid_id=CoverRejection.INVALID_SONG_ID,
    )


def write_playlist_cover(audio_dir: Path, playlist_id: str, payload: bytes) -> str:
    return write_cover(
        audio_dir, PLAYLIST_COVER_DIRNAME, playlist_id, payload,
        invalid_id=CoverRejection.INVALID_PLAYLIST_ID,
    )


def write_cover(
    audio_dir: Path,
    dirname: str,
    entity_id: str,
    payload: bytes,
    *,
    invalid_id: CoverRejection,
    ai_generated: bool = False,
) -> str:
    final_raw = _cover_entity_dir(audio_dir, dirname, entity_id, invalid_id)
    image, fmt = decode_cover_image(payload)
    cover_key = new_cover_key(fmt)
    parent = audio_dir / dirname
    parent.mkdir(parents=True, exist_ok=True)
    covers_root = parent.resolve()
    final = _confine_cover_path(final_raw, covers_root, invalid_id)
    old = _confine_cover_path(
        parent / _cover_old_name(entity_id), covers_root, invalid_id,
    )
    staging = _confine_cover_path(
        parent / _cover_staging_name(entity_id), covers_root, invalid_id,
    )
    _restore_cover_if_orphaned(final, old, covers_root, invalid_id)
    staging.mkdir()
    try:
        _save_variants(staging, image, fmt, ai_generated=ai_generated)
        if final.exists():
            _discard_leftover_cover_old(final, old, covers_root)
            _rename_confined(final, old, covers_root, invalid_id)
        _rename_confined(staging, final, covers_root, invalid_id)
    except Exception:
        _rmtree_confined_cover_dir(staging, covers_root, ignore_errors=True)
        try:
            _restore_cover_if_orphaned(final, old, covers_root, invalid_id)
        except OSError as restore_exc:
            log.warning("Failed to restore cover %s: %s", entity_id, restore_exc)
        raise
    _rmtree_confined_cover_dir(old, covers_root, ignore_errors=True)
    log.info("Wrote cover %s/%s (%s)", dirname, entity_id, cover_key)
    return cover_key


def remove_album_cover_files(audio_dir: Path, album_id: str) -> None:
    remove_cover_files(
        audio_dir, COVER_DIRNAME, album_id, invalid_id=CoverRejection.INVALID_ALBUM_ID,
    )


def remove_song_cover_files(audio_dir: Path, song_id: str) -> None:
    remove_cover_files(
        audio_dir, SONG_COVER_DIRNAME, song_id, invalid_id=CoverRejection.INVALID_SONG_ID,
    )


def remove_playlist_cover_files(audio_dir: Path, playlist_id: str) -> None:
    remove_cover_files(
        audio_dir, PLAYLIST_COVER_DIRNAME, playlist_id,
        invalid_id=CoverRejection.INVALID_PLAYLIST_ID,
    )


def remove_cover_files(
    audio_dir: Path, dirname: str, entity_id: str, *, invalid_id: CoverRejection,
) -> None:
    try:
        final = _cover_entity_dir(audio_dir, dirname, entity_id, invalid_id)
    except CoverRejectedError:
        log.warning(_COVER_PATH_TRAVERSAL_LOG, dirname)
        return
    covers_root = _covers_root(audio_dir, dirname)
    parent = final.parent
    to_remove = [final, parent / _cover_old_name(entity_id)]
    if parent.is_dir():
        prefix = _cover_staging_prefix(entity_id)
        for child in parent.iterdir():
            if child.name.startswith(prefix) and child.name.endswith(
                COVER_STAGING_DIRNAME_SUFFIX,
            ):
                to_remove.append(child)
    for path in to_remove:
        _rmtree_confined_cover_dir(path, covers_root)


def _cover_file_exists(
    audio_dir: Path,
    dirname: str,
    entity_id: str,
    cover_key: str | None,
    invalid_id: CoverRejection,
) -> bool:
    if cover_key_extension(cover_key) is None:
        return False
    try:
        path = _resolve_cover_file(
            audio_dir, dirname, entity_id, cover_key, COVER_VARIANT_ORIGINAL,
            invalid_id,
        )
    except (CoverRejectedError, OSError):
        return False
    return path.is_file()


def _resolve_cover_file(
    audio_dir: Path,
    dirname: str,
    entity_id: str,
    cover_key: str | None,
    variant: str,
    invalid_id: CoverRejection,
) -> Path:
    if variant not in COVER_VARIANTS:
        raise CoverRejectedError(CoverRejection.VARIANT_UNKNOWN)
    if cover_key is None or cover_key_extension(cover_key) is None:
        raise FileNotFoundError
    try:
        candidate = _cover_variant_path(
            audio_dir, dirname, entity_id, cover_key, variant, invalid_id,
        )
    except CoverRejectedError as exc:
        raise FileNotFoundError from exc
    covers_root = _covers_root(audio_dir, dirname)
    try:
        path = confined_under(covers_root, candidate)
    except OSError as exc:
        raise FileNotFoundError from exc
    if path is None or not path.is_file():
        raise FileNotFoundError
    return path


def _cover_entity_dir(
    audio_dir: Path, dirname: str, entity_id: str, invalid_id: CoverRejection,
) -> Path:
    _require_safe_cover_id(entity_id, invalid_id)
    return audio_dir / dirname / entity_id


def _cover_variant_path(
    audio_dir: Path,
    dirname: str,
    entity_id: str,
    cover_key: str,
    variant: str,
    invalid_id: CoverRejection,
) -> Path:
    entity_dir = _cover_entity_dir(audio_dir, dirname, entity_id, invalid_id)
    if variant == COVER_VARIANT_ORIGINAL:
        extension = (
            COVER_JPEG_EXTENSION
            if cover_key_extension(cover_key) == COVER_KEY_JPEG
            else COVER_PNG_EXTENSION
        )
        return entity_dir / f"{COVER_VARIANT_ORIGINAL}{extension}"
    return entity_dir / f"{variant}{COVER_JPEG_EXTENSION}"


def _normalized_original(image: Image.Image, fmt: str) -> Image.Image:
    if fmt == COVER_FORMAT_JPEG:
        return image.convert("RGB")
    if image.mode in {"RGB", "RGBA", "L"}:
        return image
    if "A" in image.mode:
        return image.convert("RGBA")
    return image.convert("RGB")


def _square_derivative(image: Image.Image, edge: int) -> Image.Image:
    rgb = image.convert("RGB")
    size = min(edge, max(rgb.size))
    return ImageOps.fit(rgb, (size, size), method=Image.Resampling.LANCZOS)


def _save_variants(dest: Path, image: Image.Image, fmt: str, *, ai_generated: bool) -> None:
    original_name = (
        f"{COVER_VARIANT_ORIGINAL}{COVER_JPEG_EXTENSION}"
        if fmt == COVER_FORMAT_JPEG
        else f"{COVER_VARIANT_ORIGINAL}{COVER_PNG_EXTENSION}"
    )
    jpeg_options: dict[str, object] = {
        "format": "JPEG", "quality": COVER_JPEG_QUALITY, "optimize": True,
    }
    if ai_generated:
        jpeg_options["xmp"] = AI_MARK_XMP_PACKET.encode()
    original_path = dest / original_name
    if fmt == COVER_FORMAT_JPEG:
        image.save(original_path, **jpeg_options)
    elif ai_generated:
        image.save(original_path, format="PNG", optimize=True, pnginfo=ai_mark_png_info())
    else:
        image.save(original_path, format="PNG", optimize=True)
    card = _square_derivative(image, COVER_CARD_MAX_EDGE)
    detail = _square_derivative(image, COVER_DETAIL_MAX_EDGE)
    card.save(dest / f"{COVER_VARIANT_CARD}{COVER_JPEG_EXTENSION}", **jpeg_options)
    detail.save(dest / f"{COVER_VARIANT_DETAIL}{COVER_JPEG_EXTENSION}", **jpeg_options)


def _require_safe_cover_id(entity_id: str, invalid_id: CoverRejection) -> None:
    if _is_unsafe_cover_id(entity_id):
        raise CoverRejectedError(invalid_id)


def _is_unsafe_cover_id(entity_id: str) -> bool:
    if not entity_id or "\x00" in entity_id or entity_id in _COVER_REJECTED_IDS:
        return True
    if "/" in entity_id or "\\" in entity_id:
        return True
    return Path(entity_id).is_absolute()


def _covers_root(audio_dir: Path, dirname: str) -> Path:
    return (audio_dir / dirname).resolve()


def _cover_old_name(entity_id: str) -> str:
    return f".{entity_id}{COVER_OLD_DIRNAME_SUFFIX}"


def _cover_staging_prefix(entity_id: str) -> str:
    return f".{entity_id}."


def _cover_staging_name(entity_id: str) -> str:
    return f"{_cover_staging_prefix(entity_id)}{uuid.uuid4().hex}{COVER_STAGING_DIRNAME_SUFFIX}"


def _confine_cover_path(path: Path, covers_root: Path, invalid_id: CoverRejection) -> Path:
    resolved = confined_under(covers_root, path)
    if resolved is None:
        raise CoverRejectedError(invalid_id)
    return resolved


def _rename_confined(
    source: Path, dest: Path, covers_root: Path, invalid_id: CoverRejection,
) -> None:
    confined_source = _confine_cover_path(source, covers_root, invalid_id)
    confined_dest = _confine_cover_path(dest, covers_root, invalid_id)
    confined_source.rename(confined_dest)


def _restore_cover_if_orphaned(
    final: Path, old: Path, covers_root: Path, invalid_id: CoverRejection,
) -> None:
    if not final.exists() and old.exists():
        _rename_confined(old, final, covers_root, invalid_id)


def _discard_leftover_cover_old(final: Path, old: Path, covers_root: Path) -> None:
    if final.exists() and old.exists():
        _rmtree_confined_cover_dir(old, covers_root)


def _rmtree_confined_cover_dir(
    path: Path, covers_root: Path, *, ignore_errors: bool = False,
) -> None:
    try:
        resolved = confined_under(covers_root, path)
    except OSError as exc:
        if ignore_errors:
            return
        log.warning("Cover path resolve failed for %s: %s", path, exc)
        return
    if resolved is None:
        log.warning(_COVER_PATH_TRAVERSAL_LOG, path)
        return
    if not resolved.is_dir():
        return
    shutil.rmtree(resolved, ignore_errors=ignore_errors)

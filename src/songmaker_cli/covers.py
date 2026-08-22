"""Cover validation, derivatives, and on-disk layout."""

from __future__ import annotations

import logging
import shutil
import uuid
import warnings
from io import BytesIO
from pathlib import Path
from typing import Final

from PIL import Image, ImageOps, UnidentifiedImageError

from songmaker_cli.constants import (
    COVER_CACHE_CONTROL,
    COVER_CARD_MAX_EDGE,
    COVER_DETAIL_MAX_EDGE,
    COVER_DIRNAME,
    COVER_FORMAT_JPEG,
    COVER_FORMAT_PNG,
    COVER_INVALID_ALBUM_ID,
    COVER_INVALID_SONG_ID,
    COVER_JPEG_EXTENSION,
    COVER_JPEG_MAGIC,
    COVER_JPEG_QUALITY,
    COVER_KEY_JPEG,
    COVER_KEY_PNG,
    COVER_KEYS,
    COVER_MAX_BYTES,
    COVER_MAX_PIXELS,
    COVER_MEDIA_TYPE_JPEG,
    COVER_MEDIA_TYPE_PNG,
    COVER_OLD_DIRNAME_SUFFIX,
    COVER_PNG_EXTENSION,
    COVER_PNG_MAGIC,
    COVER_STAGING_DIRNAME_SUFFIX,
    COVER_TOO_LARGE,
    COVER_TOO_MANY_PIXELS,
    COVER_UNREADABLE,
    COVER_UNSUPPORTED_TYPE,
    COVER_VARIANT_CARD,
    COVER_VARIANT_DETAIL,
    COVER_VARIANT_ORIGINAL,
    COVER_VARIANT_UNKNOWN,
    COVER_VARIANTS,
    SONG_COVER_DIRNAME,
)

log = logging.getLogger(__name__)

COVER_RESPONSE_HEADERS: dict[str, str] = {"Cache-Control": COVER_CACHE_CONTROL}
_COVER_REJECTED_IDS: Final[frozenset[str]] = frozenset({".", ".."})
_COVER_PATH_TRAVERSAL_LOG = "Path traversal blocked in cover delete: %s"


class CoverRejectedError(Exception):
    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def sniff_cover_format(payload: bytes) -> str | None:
    if payload.startswith(COVER_JPEG_MAGIC):
        return COVER_FORMAT_JPEG
    if payload.startswith(COVER_PNG_MAGIC):
        return COVER_FORMAT_PNG
    return None


def cover_key_extension(cover_key: str | None) -> str | None:
    if cover_key is None or "." not in cover_key:
        return None
    ext = cover_key.rsplit(".", 1)[-1]
    if ext not in COVER_KEYS:
        return None
    return ext


def new_cover_key(fmt: str) -> str:
    ext = COVER_KEY_JPEG if fmt == COVER_FORMAT_JPEG else COVER_KEY_PNG
    return f"{uuid.uuid4().hex}.{ext}"


def cover_album_dir(audio_dir: Path, album_id: str) -> Path:
    return _cover_entity_dir(
        audio_dir, COVER_DIRNAME, album_id, COVER_INVALID_ALBUM_ID,
    )


def cover_song_dir(audio_dir: Path, song_id: str) -> Path:
    return _cover_entity_dir(
        audio_dir, SONG_COVER_DIRNAME, song_id, COVER_INVALID_SONG_ID,
    )


def cover_variant_path(
    audio_dir: Path, album_id: str, cover_key: str, variant: str,
) -> Path:
    return _cover_variant_path(
        audio_dir, COVER_DIRNAME, album_id, cover_key, variant, COVER_INVALID_ALBUM_ID,
    )


def cover_media_type(variant: str, cover_key: str) -> str:
    if variant == COVER_VARIANT_ORIGINAL and cover_key_extension(cover_key) == COVER_KEY_PNG:
        return COVER_MEDIA_TYPE_PNG
    return COVER_MEDIA_TYPE_JPEG


def album_cover_file_exists(audio_dir: Path, album_id: str, cover_key: str | None) -> bool:
    return _cover_file_exists(
        audio_dir, COVER_DIRNAME, album_id, cover_key, COVER_INVALID_ALBUM_ID,
    )


def song_cover_file_exists(audio_dir: Path, song_id: str, cover_key: str | None) -> bool:
    return _cover_file_exists(
        audio_dir, SONG_COVER_DIRNAME, song_id, cover_key, COVER_INVALID_SONG_ID,
    )


def resolve_cover_file(
    audio_dir: Path, album_id: str, cover_key: str | None, variant: str,
) -> Path:
    return _resolve_cover_file(
        audio_dir, COVER_DIRNAME, album_id, cover_key, variant, COVER_INVALID_ALBUM_ID,
    )


def resolve_song_cover_file(
    audio_dir: Path, song_id: str, cover_key: str | None, variant: str,
) -> Path:
    return _resolve_cover_file(
        audio_dir, SONG_COVER_DIRNAME, song_id, cover_key, variant, COVER_INVALID_SONG_ID,
    )


def decode_cover_image(payload: bytes) -> tuple[Image.Image, str]:
    if len(payload) > COVER_MAX_BYTES:
        raise CoverRejectedError(COVER_TOO_LARGE, status_code=413)
    if not payload:
        raise CoverRejectedError(COVER_UNREADABLE)
    fmt = sniff_cover_format(payload)
    if fmt is None:
        raise CoverRejectedError(COVER_UNSUPPORTED_TYPE)
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = COVER_MAX_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(payload)) as raw:
                if raw.width < 1 or raw.height < 1:
                    raise CoverRejectedError(COVER_UNREADABLE)
                if raw.width * raw.height > COVER_MAX_PIXELS:
                    raise CoverRejectedError(COVER_TOO_MANY_PIXELS)
                raw.load()
                oriented = ImageOps.exif_transpose(raw)
                normalized = _normalized_original(oriented, fmt)
                return normalized.copy(), fmt
    except CoverRejectedError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise CoverRejectedError(COVER_TOO_MANY_PIXELS) from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, IndexError) as exc:
        raise CoverRejectedError(COVER_UNREADABLE) from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit


def write_album_cover(audio_dir: Path, album_id: str, payload: bytes) -> str:
    return write_cover(
        audio_dir, COVER_DIRNAME, album_id, payload,
        invalid_id_message=COVER_INVALID_ALBUM_ID,
    )


def write_song_cover(audio_dir: Path, song_id: str, payload: bytes) -> str:
    return write_cover(
        audio_dir, SONG_COVER_DIRNAME, song_id, payload,
        invalid_id_message=COVER_INVALID_SONG_ID,
    )


def write_cover(
    audio_dir: Path,
    dirname: str,
    entity_id: str,
    payload: bytes,
    *,
    invalid_id_message: str,
) -> str:
    final_raw = _cover_entity_dir(audio_dir, dirname, entity_id, invalid_id_message)
    image, fmt = decode_cover_image(payload)
    cover_key = new_cover_key(fmt)
    parent = audio_dir / dirname
    parent.mkdir(parents=True, exist_ok=True)
    covers_root = parent.resolve()
    final = _confine_cover_path(final_raw, covers_root, invalid_id_message)
    old = _confine_cover_path(
        parent / _cover_old_name(entity_id), covers_root, invalid_id_message,
    )
    staging = _confine_cover_path(
        parent / _cover_staging_name(entity_id), covers_root, invalid_id_message,
    )
    _restore_cover_if_orphaned(final, old, covers_root, invalid_id_message)
    staging.mkdir()
    try:
        _save_variants(staging, image, fmt)
        if final.exists():
            _discard_leftover_cover_old(final, old, covers_root)
            _rename_confined(final, old, covers_root, invalid_id_message)
        _rename_confined(staging, final, covers_root, invalid_id_message)
    except Exception:
        _rmtree_confined_cover_dir(staging, covers_root, ignore_errors=True)
        try:
            _restore_cover_if_orphaned(final, old, covers_root, invalid_id_message)
        except OSError as restore_exc:
            log.warning("Failed to restore cover %s: %s", entity_id, restore_exc)
        raise
    _rmtree_confined_cover_dir(old, covers_root, ignore_errors=True)
    log.info("Wrote cover %s/%s (%s)", dirname, entity_id, cover_key)
    return cover_key


def remove_album_cover_files(audio_dir: Path, album_id: str) -> None:
    remove_cover_files(
        audio_dir, COVER_DIRNAME, album_id, invalid_id_message=COVER_INVALID_ALBUM_ID,
    )


def remove_song_cover_files(audio_dir: Path, song_id: str) -> None:
    remove_cover_files(
        audio_dir, SONG_COVER_DIRNAME, song_id, invalid_id_message=COVER_INVALID_SONG_ID,
    )


def remove_cover_files(
    audio_dir: Path, dirname: str, entity_id: str, *, invalid_id_message: str,
) -> None:
    try:
        final = _cover_entity_dir(audio_dir, dirname, entity_id, invalid_id_message)
    except CoverRejectedError:
        log.warning(_COVER_PATH_TRAVERSAL_LOG, entity_id)
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
    invalid_id_message: str,
) -> bool:
    if cover_key_extension(cover_key) is None:
        return False
    try:
        path = _resolve_cover_file(
            audio_dir, dirname, entity_id, cover_key, COVER_VARIANT_ORIGINAL,
            invalid_id_message,
        )
    except (CoverRejectedError, FileNotFoundError, OSError):
        return False
    return path.is_file()


def _resolve_cover_file(
    audio_dir: Path,
    dirname: str,
    entity_id: str,
    cover_key: str | None,
    variant: str,
    invalid_id_message: str,
) -> Path:
    if variant not in COVER_VARIANTS:
        raise CoverRejectedError(COVER_VARIANT_UNKNOWN)
    if cover_key is None or cover_key_extension(cover_key) is None:
        raise FileNotFoundError
    try:
        path = _cover_variant_path(
            audio_dir, dirname, entity_id, cover_key, variant, invalid_id_message,
        ).resolve()
    except CoverRejectedError as exc:
        raise FileNotFoundError from exc
    except OSError as exc:
        raise FileNotFoundError from exc
    covers_root = _covers_root(audio_dir, dirname)
    if not path.is_relative_to(covers_root):
        raise FileNotFoundError
    if not path.is_file():
        raise FileNotFoundError
    return path


def _cover_entity_dir(
    audio_dir: Path, dirname: str, entity_id: str, invalid_id_message: str,
) -> Path:
    _require_safe_cover_id(entity_id, invalid_id_message)
    return audio_dir / dirname / entity_id


def _cover_variant_path(
    audio_dir: Path,
    dirname: str,
    entity_id: str,
    cover_key: str,
    variant: str,
    invalid_id_message: str,
) -> Path:
    entity_dir = _cover_entity_dir(audio_dir, dirname, entity_id, invalid_id_message)
    if variant == COVER_VARIANT_ORIGINAL:
        ext = cover_key_extension(cover_key)
        if ext == COVER_KEY_JPEG:
            return entity_dir / f"{COVER_VARIANT_ORIGINAL}{COVER_JPEG_EXTENSION}"
        if ext == COVER_KEY_PNG:
            return entity_dir / f"{COVER_VARIANT_ORIGINAL}{COVER_PNG_EXTENSION}"
        raise FileNotFoundError
    if variant == COVER_VARIANT_CARD:
        return entity_dir / f"{COVER_VARIANT_CARD}{COVER_JPEG_EXTENSION}"
    if variant == COVER_VARIANT_DETAIL:
        return entity_dir / f"{COVER_VARIANT_DETAIL}{COVER_JPEG_EXTENSION}"
    raise CoverRejectedError(COVER_VARIANT_UNKNOWN)


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


def _save_variants(dest: Path, image: Image.Image, fmt: str) -> None:
    original_name = (
        f"{COVER_VARIANT_ORIGINAL}{COVER_JPEG_EXTENSION}"
        if fmt == COVER_FORMAT_JPEG
        else f"{COVER_VARIANT_ORIGINAL}{COVER_PNG_EXTENSION}"
    )
    original_path = dest / original_name
    if fmt == COVER_FORMAT_JPEG:
        image.save(
            original_path, format="JPEG", quality=COVER_JPEG_QUALITY, optimize=True,
        )
    else:
        image.save(original_path, format="PNG", optimize=True)
    card = _square_derivative(image, COVER_CARD_MAX_EDGE)
    detail = _square_derivative(image, COVER_DETAIL_MAX_EDGE)
    card.save(
        dest / f"{COVER_VARIANT_CARD}{COVER_JPEG_EXTENSION}",
        format="JPEG", quality=COVER_JPEG_QUALITY, optimize=True,
    )
    detail.save(
        dest / f"{COVER_VARIANT_DETAIL}{COVER_JPEG_EXTENSION}",
        format="JPEG", quality=COVER_JPEG_QUALITY, optimize=True,
    )


def _require_safe_cover_id(entity_id: str, invalid_id_message: str) -> None:
    if _is_unsafe_cover_id(entity_id):
        raise CoverRejectedError(invalid_id_message)


def _is_unsafe_cover_id(entity_id: str) -> bool:
    if not entity_id or "\x00" in entity_id or entity_id in _COVER_REJECTED_IDS:
        return True
    if "/" in entity_id or "\\" in entity_id:
        return True
    try:
        return Path(entity_id).is_absolute()
    except (ValueError, OSError):
        return True


def _covers_root(audio_dir: Path, dirname: str) -> Path:
    return (audio_dir / dirname).resolve()


def _cover_old_name(entity_id: str) -> str:
    return f".{entity_id}{COVER_OLD_DIRNAME_SUFFIX}"


def _cover_staging_prefix(entity_id: str) -> str:
    return f".{entity_id}."


def _cover_staging_name(entity_id: str) -> str:
    return f"{_cover_staging_prefix(entity_id)}{uuid.uuid4().hex}{COVER_STAGING_DIRNAME_SUFFIX}"


def _confine_cover_path(path: Path, covers_root: Path, invalid_id_message: str) -> Path:
    resolved = path.resolve()
    if resolved == covers_root or not resolved.is_relative_to(covers_root):
        raise CoverRejectedError(invalid_id_message)
    return resolved


def _rename_confined(
    source: Path, dest: Path, covers_root: Path, invalid_id_message: str,
) -> None:
    confined_source = _confine_cover_path(source, covers_root, invalid_id_message)
    confined_dest = _confine_cover_path(dest, covers_root, invalid_id_message)
    confined_source.rename(confined_dest)


def _restore_cover_if_orphaned(
    final: Path, old: Path, covers_root: Path, invalid_id_message: str,
) -> None:
    if not final.exists() and old.exists():
        _rename_confined(old, final, covers_root, invalid_id_message)


def _discard_leftover_cover_old(final: Path, old: Path, covers_root: Path) -> None:
    if final.exists() and old.exists():
        _rmtree_confined_cover_dir(old, covers_root)


def _rmtree_confined_cover_dir(
    path: Path, covers_root: Path, *, ignore_errors: bool = False,
) -> None:
    try:
        resolved = path.resolve()
    except OSError as exc:
        if ignore_errors:
            return
        log.warning("Cover path resolve failed for %s: %s", path, exc)
        return
    if resolved == covers_root or not resolved.is_relative_to(covers_root):
        log.warning(_COVER_PATH_TRAVERSAL_LOG, path)
        return
    if not resolved.is_dir():
        return
    shutil.rmtree(resolved, ignore_errors=ignore_errors)

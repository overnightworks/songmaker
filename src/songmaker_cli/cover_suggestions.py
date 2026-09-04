"""Filesystem ownership for generated album cover suggestions."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path, PurePosixPath

from fastapi import HTTPException

from songmaker_cli.audio_paths import canonical_audio_path
from songmaker_cli.constants import ALBUM_COVER_SUGGESTIONS_DIRNAME

log = logging.getLogger(__name__)


def suggestion_png_path(audio_dir: Path, album_id: str, suggestion_id: str) -> Path:
    relative_path = _expected_relative_path(album_id, suggestion_id)
    return canonical_audio_path(audio_dir, relative_path)


def resolve_suggestion_png(
    audio_dir: Path, album_id: str, suggestion_id: str, stored_path: str,
) -> Path:
    expected_path = _expected_relative_path(album_id, suggestion_id)
    if stored_path != expected_path:
        raise FileNotFoundError(stored_path)
    path = canonical_audio_path(audio_dir, stored_path)
    if not path.is_file():
        raise FileNotFoundError(stored_path)
    return path


def remove_cover_suggestion_files(audio_dir: Path, paths: list[str]) -> None:
    root = (audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME).resolve()
    for stored_path in paths:
        try:
            path = canonical_audio_path(audio_dir, stored_path)
        except HTTPException:
            log.warning("Cover suggestion path traversal denied: %r", stored_path)
            continue
        if not path.is_relative_to(root) or path.suffix != ".png":
            log.warning("Cover suggestion path outside suggestion root: %r", stored_path)
            continue
        if path.is_file():
            path.unlink()
        _remove_empty_parents(path.parent, root)


def remove_album_cover_suggestion_files(audio_dir: Path, album_id: str) -> None:
    try:
        path = suggestion_png_path(audio_dir, album_id, "placeholder").parent
    except HTTPException:
        log.warning("Cover suggestion album traversal denied: %r", album_id)
        return
    root = (audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME).resolve()
    if path.is_relative_to(root) and path.is_dir():
        shutil.rmtree(path)


def _expected_relative_path(album_id: str, suggestion_id: str) -> str:
    relative_path = PurePosixPath(
        ALBUM_COVER_SUGGESTIONS_DIRNAME, album_id, f"{suggestion_id}.png",
    )
    if (
        len(relative_path.parts) != 3
        or relative_path.parts[0] != ALBUM_COVER_SUGGESTIONS_DIRNAME
        or ".." in relative_path.parts
        or relative_path.as_posix().startswith("/")
    ):
        raise HTTPException(404, "Not Found")
    return relative_path.as_posix()


def _remove_empty_parents(path: Path, root: Path) -> None:
    while path != root and path.is_relative_to(root):
        try:
            path.rmdir()
        except OSError:
            return
        path = path.parent

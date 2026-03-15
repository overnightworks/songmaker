"""Filesystem scanning and version deduplication for album output directories."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from songmaker_cli.parser import AlbumMeta


def extract_version_number(stem: str) -> int:
    """Extract numeric version from a stem like '01_song_v3' -> 3. Returns 0 if none."""
    match = re.search(r"_v(\d+)$", stem)
    return int(match.group(1)) if match else 0


def deduplicate_versions(mp3s: list[Path]) -> list[Path]:
    """Keep only the latest version of each track (e.g., v2 over v1)."""
    from songmaker_cli.parser import strip_version_suffix

    by_base: dict[str, tuple[int, Path]] = {}
    for mp3 in mp3s:
        base = strip_version_suffix(mp3.stem)
        if base.endswith("_raw"):
            continue
        version = extract_version_number(mp3.stem)
        if base not in by_base or version > by_base[base][0]:
            by_base[base] = (version, mp3)
    return sorted(p for _, p in by_base.values())


@dataclass
class AlbumScan:
    """Result of scanning one album directory for MP3s."""

    album_name: str
    mp3_base: str
    mp3s: list[Path]
    lyrics_dir: Path
    meta: AlbumMeta


def _load_album_meta(album_dir: Path) -> AlbumMeta:
    """Load album metadata — delegates to parser module."""
    from songmaker_cli.parser import load_album_meta

    return load_album_meta(album_dir)


def iter_album_scans(
    output_dir: Path, project_root: Path,
) -> list[AlbumScan]:
    """Scan all album directories for MP3 files with metadata.

    Returns all versions (no deduplication). Raw intermediate files
    (stems ending in '_raw') are excluded.
    """
    results: list[AlbumScan] = []
    for album_dir in sorted(output_dir.iterdir()):
        if not album_dir.is_dir():
            continue

        album_name = album_dir.name
        final_dir = album_dir / "final"
        if final_dir.exists():
            mp3s = sorted(final_dir.glob("*.mp3"))
            mp3_base = f"{album_name}/final"
        else:
            mp3s = [m for m in sorted(album_dir.glob("*.mp3")) if not m.stem.endswith("_raw")]
            mp3_base = album_name

        if not mp3s:
            continue

        source_album_dir = project_root / "albums" / album_name
        meta = _load_album_meta(source_album_dir)
        lyrics_dir = project_root / "albums" / album_name / "lyrics"

        results.append(AlbumScan(
            album_name=album_name,
            mp3_base=mp3_base,
            mp3s=mp3s,
            lyrics_dir=lyrics_dir,
            meta=meta,
        ))
    return results

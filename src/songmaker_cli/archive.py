"""Archive bad versions — move to _archive/ instead of deleting."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)


def archive_file(mp3_path: Path, archive_dir: Path, album: str = "") -> None:
    """Move a single MP3 + snapshot to the archive."""
    if not album:
        album = mp3_path.parent.name
    dest_dir = archive_dir / album
    dest_dir.mkdir(parents=True, exist_ok=True)

    for suffix in [".mp3", ".md"]:
        src = mp3_path.with_suffix(suffix)
        if src.exists():
            dest = dest_dir / src.name
            src.rename(dest)
            log.info("Archived: %s → %s", src.name, dest)


def archive_below_threshold(
    threshold: float,
    output_dir: Path,
    archive_dir: Path,
    read_scores_fn: Callable[[Path], dict[str, object] | None],
) -> int:
    """Archive all versions with dynamics below a threshold.

    Returns the number of archived versions.
    """
    mp3s = sorted(output_dir.rglob("*.mp3"))
    archived = 0
    for mp3 in mp3s:
        snapshot = mp3.with_suffix(".md")
        if not snapshot.exists():
            continue
        scores = read_scores_fn(snapshot)
        if scores is None:
            continue
        dynamics = scores.get("dynamics")
        if dynamics is not None and float(dynamics) < threshold:
            archive_file(mp3, archive_dir)
            archived += 1

    log.info("Archived %d versions with dynamics < %.0f", archived, threshold)
    return archived

"""Query functions for versions — get, create (via update_song), delete."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from songmaker_cli.db.models import Version

log = logging.getLogger(__name__)


def get_version(session: Session, version_id: str, song_id: str) -> Version | None:
    return (
        session.query(Version)
        .filter_by(id=version_id, song_id=song_id)
        .first()
    )


def delete_version(
    session: Session, version_id: str, *,
    delete_generations: bool = False, audio_dir: Path | None = None,
) -> None:
    from songmaker_cli.db.queries.generations import delete_generation_files

    version = session.query(Version).filter_by(id=version_id).first()
    if not version:
        raise ValueError(f"Version not found: {version_id}")

    paths_to_delete: list[str] = []
    if delete_generations:
        for gen in version.generations:
            if audio_dir and gen.mp3_path:
                paths_to_delete.append(gen.mp3_path)
            session.delete(gen)
    else:
        for gen in version.generations:
            gen.version_id = None

    session.delete(version)
    session.flush()

    for mp3_rel in paths_to_delete:
        delete_generation_files(audio_dir, mp3_rel)

    log.info("Deleted version %s (delete_generations=%s)", version_id, delete_generations)

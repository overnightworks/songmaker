"""Query functions for versions — get, create (via update_song), delete."""

from __future__ import annotations

from sqlalchemy.orm import Session

from songmaker_cli.db.models import Version
from songmaker_cli.db.queries.songs import lock_song_row


def get_version(session: Session, version_id: str, song_id: str) -> Version | None:
    return (
        session.query(Version)
        .filter_by(id=version_id, song_id=song_id)
        .first()
    )


def delete_version(
    session: Session, version_id: str, *,
    delete_generations: bool = False,
) -> list[str]:
    """Delete a version and return relative file paths for cleanup.

    Callers must delete files AFTER committing the transaction to avoid
    inconsistency if the commit fails.
    """
    version = session.query(Version).filter_by(id=version_id).first()
    if not version:
        raise ValueError(f"Version not found: {version_id}")
    lock_song_row(session, version.song_id)
    # A delete that committed while this one waited leaves nothing to delete.
    version = session.query(Version).populate_existing().filter_by(id=version_id).first()
    if not version:
        raise ValueError(f"Version not found: {version_id}")

    paths_to_delete: list[str] = []
    if delete_generations:
        for gen in version.generations:
            for p in [gen.mp3_path, gen.wav_path]:
                if p:
                    paths_to_delete.append(p)
            session.delete(gen)
    else:
        for gen in version.generations:
            gen.version_id = None

    session.delete(version)
    session.flush()

    return paths_to_delete

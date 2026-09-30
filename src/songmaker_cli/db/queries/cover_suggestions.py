"""Query functions for durable album cover suggestions."""

from __future__ import annotations

from sqlalchemy.orm import Session

from songmaker_cli.db.models import AlbumCoverSuggestion


def list_album_cover_suggestions(
    session: Session, album_id: str,
) -> list[AlbumCoverSuggestion]:
    return (
        session.query(AlbumCoverSuggestion)
        .filter_by(album_id=album_id)
        .order_by(AlbumCoverSuggestion.created_at, AlbumCoverSuggestion.id)
        .all()
    )


def get_album_cover_suggestion(
    session: Session, album_id: str, suggestion_id: str,
) -> AlbumCoverSuggestion | None:
    return (
        session.query(AlbumCoverSuggestion)
        .filter_by(album_id=album_id, id=suggestion_id)
        .first()
    )


def delete_album_cover_suggestions(
    session: Session, album_id: str,
) -> list[str]:
    return _delete_cover_suggestions(session, list_album_cover_suggestions(session, album_id))


def delete_job_cover_suggestions(
    session: Session, job_ids: list[str],
) -> list[str]:
    suggestions = (
        session.query(AlbumCoverSuggestion)
        .filter(AlbumCoverSuggestion.job_id.in_(job_ids))
        .all()
    )
    return _delete_cover_suggestions(session, suggestions)


def _delete_cover_suggestions(
    session: Session, suggestions: list[AlbumCoverSuggestion],
) -> list[str]:
    paths = [suggestion.png_path for suggestion in suggestions]
    for suggestion in suggestions:
        session.delete(suggestion)
    session.flush()
    return paths

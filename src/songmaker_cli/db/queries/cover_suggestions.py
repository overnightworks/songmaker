"""Query functions for durable album cover suggestions."""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import or_
from sqlalchemy.orm import Session

from songmaker_cli.db.models import AlbumCoverSuggestion, Job
from songmaker_cli.job_types import JobStatus, JobType


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


def list_ended_cover_job_ids(
    session: Session, ended_statuses: Collection[JobStatus], staged_job_ids: Collection[str],
) -> set[str]:
    """Ids of cover jobs in an ended status that are staged or made a suggestion."""
    return {
        job_id for (job_id,) in session.query(Job.id).filter(
            Job.type == JobType.COVER,
            Job.status.in_(ended_statuses),
            or_(
                Job.id.in_(staged_job_ids),
                Job.id.in_(
                    session.query(AlbumCoverSuggestion.job_id).filter(
                        AlbumCoverSuggestion.job_id.isnot(None),
                    ),
                ),
            ),
        )
    }


def delete_named_cover_suggestions(
    session: Session, album_id: str, suggestion_ids: list[str], job_ids: list[str],
) -> list[str]:
    """Delete this album's suggestions that are named or were made by a named run."""
    suggestions = (
        session.query(AlbumCoverSuggestion)
        .filter(
            AlbumCoverSuggestion.album_id == album_id,
            or_(
                AlbumCoverSuggestion.id.in_(suggestion_ids),
                AlbumCoverSuggestion.job_id.in_(job_ids),
            ),
        )
        .all()
    )
    return _delete_cover_suggestions(session, suggestions)


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

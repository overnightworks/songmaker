"""Query functions for UserLora + UserLoraSample — CRUD, soft delete, ordering."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from songmaker_cli.constants import JOB_TERMINAL_STATUSES, LORA_ACTIVE_STATUSES, LoraStatus
from songmaker_cli.db.models import Job, UserLora, UserLoraSample

log = logging.getLogger(__name__)


def create_user_lora(
    session: Session, user_id: str, name: str, slug: str,
) -> UserLora:
    lora = UserLora(
        user_id=user_id, name=name, slug=slug, status=LoraStatus.DRAFT,
    )
    session.add(lora)
    session.flush()
    log.info("Created UserLora %s (user=%s, name=%r)", lora.id, user_id, name)
    return lora


def get_user_lora(
    session: Session, lora_id: str, *, include_deleted_rows: bool = False,
) -> UserLora | None:
    query = session.query(UserLora).options(joinedload(UserLora.samples))
    if not include_deleted_rows:
        query = query.filter(UserLora.deleted_at.is_(None))
    return query.filter(UserLora.id == lora_id).first()


def list_user_loras_for_user(
    session: Session, user_id: str, *, include_deleted: bool = False,
) -> list[UserLora]:
    query = session.query(UserLora).options(joinedload(UserLora.samples)).filter(
        UserLora.user_id == user_id,
    )
    if not include_deleted:
        query = query.filter(UserLora.deleted_at.is_(None))
    return query.order_by(UserLora.created_at.desc()).all()


def update_user_lora(
    session: Session, lora_id: str,
    *,
    status: str | None = None,
    storage_path: str | None = None,
    tensor_path: str | None = None,
    training_job_id: str | None = None,
    error: str | None = None,
    completed_at: datetime | None = None,
    clear_error: bool = False,
) -> UserLora:
    lora = session.query(UserLora).filter_by(id=lora_id).first()
    if not lora:
        raise ValueError(f"UserLora not found: {lora_id}")
    if status is not None:
        lora.status = status
    if storage_path is not None:
        lora.storage_path = storage_path
    if tensor_path is not None:
        lora.tensor_path = tensor_path
    if training_job_id is not None:
        lora.training_job_id = training_job_id
    if error is not None:
        lora.error = error
    elif clear_error:
        lora.error = None
    if completed_at is not None:
        lora.completed_at = completed_at
    session.flush()
    return lora


def soft_delete_user_lora(session: Session, lora_id: str) -> datetime:
    lora = session.query(UserLora).filter_by(id=lora_id).first()
    if not lora:
        raise ValueError(f"UserLora not found: {lora_id}")
    now = datetime.now(timezone.utc)
    lora.deleted_at = now
    session.flush()
    log.info("Soft-deleted UserLora %s", lora_id)
    return now


def restore_user_lora(session: Session, lora_id: str) -> UserLora:
    lora = session.query(UserLora).filter_by(id=lora_id).first()
    if not lora:
        raise ValueError(f"UserLora not found: {lora_id}")
    lora.deleted_at = None
    session.flush()
    return lora


def list_active_user_loras(
    session: Session,
    *,
    reconcilable_only: bool = False,
    excluded_ids: set[str] | None = None,
    limit: int | None = None,
) -> list[UserLora]:
    """Return active LoRAs, optionally locking one eligible crash-recovery row.

    The default returns every active, non-deleted LoRA as before.  Recovery
    callers request ``reconcilable_only`` to select an unlocked LoRA whose
    training job is missing or terminal; PostgreSQL then locks that LoRA row
    with ``SKIP LOCKED`` so one process owns its failure audit.
    """
    query = (
        session.query(UserLora)
        .filter(
            UserLora.status.in_(LORA_ACTIVE_STATUSES),
            UserLora.deleted_at.is_(None),
        )
    )
    if not reconcilable_only:
        return query.all()

    query = query.outerjoin(Job, UserLora.training_job_id == Job.id).filter(
        or_(
            UserLora.training_job_id.is_(None),
            Job.id.is_(None),
            Job.status.in_(JOB_TERMINAL_STATUSES),
        ),
    )
    if excluded_ids:
        query = query.filter(UserLora.id.notin_(excluded_ids))
    query = query.order_by(UserLora.id).with_for_update(
        of=UserLora, skip_locked=True,
    )
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def count_user_lora_samples(session: Session, lora_id: str) -> int:
    return (
        session.query(UserLoraSample)
        .filter(UserLoraSample.user_lora_id == lora_id)
        .count()
    )


def add_user_lora_sample(
    session: Session, lora_id: str, audio_path: str,
    *,
    caption: str = "",
    lyrics: str = "",
    position: int | None = None,
) -> UserLoraSample:
    if position is None:
        position = count_user_lora_samples(session, lora_id)
    sample = UserLoraSample(
        user_lora_id=lora_id, audio_path=audio_path,
        caption=caption, lyrics=lyrics, position=position,
    )
    session.add(sample)
    session.flush()
    return sample


def get_user_lora_sample(
    session: Session, sample_id: str,
) -> UserLoraSample | None:
    return (
        session.query(UserLoraSample)
        .options(joinedload(UserLoraSample.user_lora))
        .filter(UserLoraSample.id == sample_id)
        .first()
    )


def update_user_lora_sample(
    session: Session, sample_id: str,
    *,
    caption: str | None = None,
    lyrics: str | None = None,
    position: int | None = None,
) -> UserLoraSample:
    sample = session.query(UserLoraSample).filter_by(id=sample_id).first()
    if not sample:
        raise ValueError(f"UserLoraSample not found: {sample_id}")
    if caption is not None:
        sample.caption = caption
    if lyrics is not None:
        sample.lyrics = lyrics
    if position is not None:
        _reorder_sample(session, sample, position)
    session.flush()
    return sample


def _reorder_sample(
    session: Session, sample: UserLoraSample, new_position: int,
) -> None:
    siblings = (
        session.query(UserLoraSample)
        .filter(UserLoraSample.user_lora_id == sample.user_lora_id)
        .order_by(UserLoraSample.position)
        .all()
    )
    ordered = [s for s in siblings if s.id != sample.id]
    target = max(0, min(new_position, len(ordered)))
    ordered.insert(target, sample)
    for idx, s in enumerate(ordered):
        s.position = idx


def delete_user_lora_sample(session: Session, sample_id: str) -> str:
    """Remove a sample row. Returns the on-disk audio_path for post-commit cleanup."""
    sample = session.query(UserLoraSample).filter_by(id=sample_id).first()
    if not sample:
        raise ValueError(f"UserLoraSample not found: {sample_id}")
    audio_path = sample.audio_path
    lora_id = sample.user_lora_id
    session.delete(sample)
    session.flush()
    remaining = (
        session.query(UserLoraSample)
        .filter(UserLoraSample.user_lora_id == lora_id)
        .order_by(UserLoraSample.position)
        .all()
    )
    for idx, s in enumerate(remaining):
        s.position = idx
    session.flush()
    return audio_path

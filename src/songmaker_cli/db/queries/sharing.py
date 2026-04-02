"""Generic sharing helpers for models using ShareMixin."""

from __future__ import annotations

import logging
import uuid
from typing import TypeVar

from sqlalchemy.orm import Session

from songmaker_cli.db.models import ShareMixin

log = logging.getLogger(__name__)

T = TypeVar("T", bound=ShareMixin)


def enable_sharing(session: Session, model_class: type[T], entity_id: str) -> T:
    entity = session.query(model_class).filter_by(id=entity_id).first()
    if not entity:
        raise ValueError(f"{model_class.__name__} not found: {entity_id}")
    if not entity.share_slug:
        entity.share_slug = str(uuid.uuid4())
    entity.is_shared = True
    session.flush()
    log.info(
        "Enabled sharing for %s %s (slug=%s)",
        model_class.__name__.lower(), entity_id, entity.share_slug,
    )
    return entity


def disable_sharing(session: Session, model_class: type[T], entity_id: str) -> T:
    entity = session.query(model_class).filter_by(id=entity_id).first()
    if not entity:
        raise ValueError(f"{model_class.__name__} not found: {entity_id}")
    entity.share_slug = None
    entity.is_shared = False
    session.flush()
    log.info("Disabled sharing for %s %s", model_class.__name__.lower(), entity_id)
    return entity

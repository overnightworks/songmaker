"""Query functions for generation presets."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from songmaker_cli.db.models import GenerationPreset


def list_presets(session: Session, user_id: str) -> list[GenerationPreset]:
    return (
        session.query(GenerationPreset)
        .filter(GenerationPreset.created_by == user_id)
        .order_by(GenerationPreset.model_mode, GenerationPreset.name)
        .all()
    )


def get_preset(session: Session, preset_id: str, user_id: str) -> GenerationPreset | None:
    return (
        session.query(GenerationPreset)
        .filter(GenerationPreset.id == preset_id, GenerationPreset.created_by == user_id)
        .first()
    )


def name_exists(session: Session, user_id: str, model_mode: str, name: str) -> bool:
    return (
        session.query(GenerationPreset)
        .filter(
            GenerationPreset.created_by == user_id,
            GenerationPreset.model_mode == model_mode,
            GenerationPreset.name == name,
        )
        .first()
    ) is not None


def create_preset(
    session: Session,
    name: str,
    model_mode: str,
    params: dict,
    user_id: str,
    is_default: bool = False,
) -> GenerationPreset:
    if is_default:
        _clear_default(session, user_id, model_mode)
    preset = GenerationPreset(
        name=name,
        model_mode=model_mode,
        params=params,
        is_default=is_default,
        created_by=user_id,
    )
    session.add(preset)
    session.flush()
    return preset


def update_preset(
    session: Session,
    preset: GenerationPreset,
    name: str | None = None,
    params: dict | None = None,
    is_default: bool | None = None,
) -> GenerationPreset:
    if name is not None:
        preset.name = name
    if params is not None:
        preset.params = params
    if is_default is True:
        _clear_default(session, preset.created_by, preset.model_mode)
        preset.is_default = True
    elif is_default is False:
        preset.is_default = False
    preset.updated_at = datetime.now(timezone.utc)
    session.flush()
    return preset


def delete_preset(session: Session, preset_id: str, user_id: str) -> bool:
    preset = get_preset(session, preset_id, user_id)
    if not preset:
        return False
    session.delete(preset)
    session.flush()
    return True


def get_default_preset(
    session: Session, user_id: str, model_mode: str,
) -> GenerationPreset | None:
    return (
        session.query(GenerationPreset)
        .filter(
            GenerationPreset.created_by == user_id,
            GenerationPreset.model_mode == model_mode,
            GenerationPreset.is_default.is_(True),
        )
        .first()
    )


def set_default_preset(session: Session, preset: GenerationPreset) -> None:
    _clear_default(session, preset.created_by, preset.model_mode)
    preset.is_default = True
    preset.updated_at = datetime.now(timezone.utc)
    session.flush()


def _clear_default(session: Session, user_id: str, model_mode: str) -> None:
    (
        session.query(GenerationPreset)
        .filter(
            GenerationPreset.created_by == user_id,
            GenerationPreset.model_mode == model_mode,
            GenerationPreset.is_default.is_(True),
        )
        .update({"is_default": False})
    )

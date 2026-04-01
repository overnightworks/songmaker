"""Query functions for generation presets and admin settings."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from songmaker_cli.constants import GLOBAL_DEFAULTS_PRESET_NAME
from songmaker_cli.db.models import AvailableModel, GenerationPreset, RateLimitSetting


def list_active_models(session: Session) -> list[AvailableModel]:
    return (
        session.query(AvailableModel)
        .filter(AvailableModel.is_active.is_(True))
        .order_by(AvailableModel.id)
        .all()
    )


def list_all_models(session: Session) -> list[AvailableModel]:
    return session.query(AvailableModel).order_by(AvailableModel.id).all()


def toggle_model(session: Session, model_id: str, is_active: bool) -> AvailableModel | None:
    model = session.query(AvailableModel).filter_by(id=model_id).first()
    if not model:
        return None
    model.is_active = is_active
    session.flush()
    return model


def list_presets(session: Session, user_id: str) -> list[GenerationPreset]:
    return (
        session.query(GenerationPreset)
        .filter(GenerationPreset.created_by == user_id)
        .order_by(GenerationPreset.model_mode, GenerationPreset.name)
        .all()
    )


def list_shared_presets(session: Session) -> list[GenerationPreset]:
    return (
        session.query(GenerationPreset)
        .filter(
            GenerationPreset.created_by.is_(None),
            GenerationPreset.name != GLOBAL_DEFAULTS_PRESET_NAME,
        )
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


def get_global_defaults(session: Session, model_mode: str) -> dict | None:
    preset = (
        session.query(GenerationPreset)
        .filter(
            GenerationPreset.name == GLOBAL_DEFAULTS_PRESET_NAME,
            GenerationPreset.model_mode == model_mode,
            GenerationPreset.created_by.is_(None),
        )
        .first()
    )
    return dict(preset.params) if preset else None


def save_global_defaults(session: Session, model_mode: str, params: dict) -> None:
    preset = (
        session.query(GenerationPreset)
        .filter(
            GenerationPreset.name == GLOBAL_DEFAULTS_PRESET_NAME,
            GenerationPreset.model_mode == model_mode,
            GenerationPreset.created_by.is_(None),
        )
        .first()
    )
    if preset:
        preset.params = params
        preset.updated_at = datetime.now(timezone.utc)
    else:
        preset = GenerationPreset(
            name=GLOBAL_DEFAULTS_PRESET_NAME,
            model_mode=model_mode,
            params=params,
            created_by=None,
        )
        session.add(preset)
    session.flush()


def get_claude_model(session: Session, setting_key: str, env_fallback: str) -> str:
    row = (
        session.query(RateLimitSetting)
        .filter(
            RateLimitSetting.setting_key == setting_key,
            RateLimitSetting.user_id.is_(None),
        )
        .first()
    )
    if row is not None:
        return str(row.value_text) if row.value_text else env_fallback
    return env_fallback


def set_claude_model(session: Session, setting_key: str, value: str) -> None:
    row = (
        session.query(RateLimitSetting)
        .filter(
            RateLimitSetting.setting_key == setting_key,
            RateLimitSetting.user_id.is_(None),
        )
        .first()
    )
    if row:
        row.value_text = value
    else:
        row = RateLimitSetting(setting_key=setting_key, value=0, value_text=value)
        session.add(row)
    session.flush()


def _clear_default(session: Session, user_id: str, model_mode: str) -> None:
    query = session.query(GenerationPreset).filter(
        GenerationPreset.created_by == user_id,
        GenerationPreset.model_mode == model_mode,
        GenerationPreset.is_default.is_(True),
    )
    if session.bind.dialect.name != "sqlite":
        query.with_for_update().all()
    query.update({"is_default": False})

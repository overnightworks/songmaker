"""Query functions for generation presets and admin settings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from songmaker_cli.constants import (
    COWRITER_DEFAULT_PROVIDER,
    COWRITER_DEFAULT_TAIL_TOKEN_BUDGET,
    COWRITER_MAX_TAIL_TOKEN_BUDGET,
    COWRITER_MIN_TAIL_TOKEN_BUDGET,
    COWRITER_PROVIDERS,
    JUDGE_DEFAULT_PROVIDER,
    PRESET_GLOBAL_DEFAULTS_NAME,
    SETTING_CLAUDE_CHAT_MODEL,
    SETTING_CLAUDE_SCORING_MODEL,
    SETTING_COWRITER_MODEL,
    SETTING_COWRITER_PROVIDER,
    SETTING_COWRITER_TAIL_TOKEN_BUDGET,
    SETTING_JUDGE_MODEL,
    SETTING_JUDGE_PROVIDER,
)
from songmaker_cli.db.models import AvailableModel, GenerationPreset, RateLimitSetting
from songmaker_cli.settings import get_settings


@dataclass(frozen=True)
class RawStoredCowriterSettings:
    """The provider and model exactly as stored, without resolving defaults."""

    provider: str | None
    model: str | None


@dataclass(frozen=True)
class RawStoredJudgeSettings:
    """The judge provider and model exactly as stored, without defaults."""

    provider: str | None
    model: str | None


@dataclass(frozen=True)
class ActiveCowriterSettings:
    """A complete, supported co-writer provider and model pair."""

    provider: str
    model: str


@dataclass(frozen=True)
class ActiveJudgeSettings:
    """A complete, supported judge provider and model pair."""

    provider: str
    model: str


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
            GenerationPreset.name != PRESET_GLOBAL_DEFAULTS_NAME,
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
            GenerationPreset.name == PRESET_GLOBAL_DEFAULTS_NAME,
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
            GenerationPreset.name == PRESET_GLOBAL_DEFAULTS_NAME,
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
            name=PRESET_GLOBAL_DEFAULTS_NAME,
            model_mode=model_mode,
            params=params,
            created_by=None,
        )
        session.add(preset)
    session.flush()


def _get_claude_model_row(session: Session, setting_key: str) -> str | None:
    row = (
        session.query(RateLimitSetting)
        .filter(
            RateLimitSetting.setting_key == setting_key,
            RateLimitSetting.user_id.is_(None),
        )
        .first()
    )
    if row is not None and row.value_text:
        return str(row.value_text)
    return None


def get_raw_stored_cowriter_settings(session: Session) -> RawStoredCowriterSettings:
    """Return the co-writer provider and model values without resolving defaults."""
    stored_values = {
        str(setting_key): value_text
        for setting_key, value_text in (
            session.query(RateLimitSetting.setting_key, RateLimitSetting.value_text)
            .filter(
                RateLimitSetting.setting_key.in_(
                    (SETTING_COWRITER_PROVIDER, SETTING_COWRITER_MODEL),
                ),
                RateLimitSetting.user_id.is_(None),
            )
            .all()
        )
    }
    return RawStoredCowriterSettings(
        provider=stored_values.get(SETTING_COWRITER_PROVIDER),
        model=stored_values.get(SETTING_COWRITER_MODEL),
    )


def get_raw_stored_judge_settings(session: Session) -> RawStoredJudgeSettings:
    """Return judge provider and model values without resolving defaults."""
    stored_values = {
        str(setting_key): value_text
        for setting_key, value_text in (
            session.query(RateLimitSetting.setting_key, RateLimitSetting.value_text)
            .filter(
                RateLimitSetting.setting_key.in_(
                    (SETTING_JUDGE_PROVIDER, SETTING_JUDGE_MODEL),
                ),
                RateLimitSetting.user_id.is_(None),
            )
            .all()
        )
    }
    return RawStoredJudgeSettings(
        provider=stored_values.get(SETTING_JUDGE_PROVIDER),
        model=stored_values.get(SETTING_JUDGE_MODEL),
    )


def get_active_cowriter_settings(session: Session) -> ActiveCowriterSettings | None:
    """Resolve the active co-writer pair unless its saved provider was retired."""
    stored = get_raw_stored_cowriter_settings(session)
    if stored.provider not in (None, "") and stored.provider not in COWRITER_PROVIDERS:
        return None
    provider = get_cowriter_provider(session)
    model = get_cowriter_model(session, provider)
    if not model:
        return None
    return ActiveCowriterSettings(provider=provider, model=model)


def get_active_judge_settings(session: Session) -> ActiveJudgeSettings | None:
    """Resolve the active judge pair unless its saved provider was retired."""
    stored = get_raw_stored_judge_settings(session)
    if stored.provider not in (None, "") and stored.provider not in COWRITER_PROVIDERS:
        return None
    provider = get_judge_provider(session)
    model = get_judge_model(session, provider)
    if not model:
        return None
    return ActiveJudgeSettings(provider=provider, model=model)


def get_claude_chat_model(session: Session) -> str:
    """Return the configured chat model: DB row override or Settings default."""
    return (
        _get_claude_model_row(session, SETTING_CLAUDE_CHAT_MODEL)
        or get_settings().claude_chat_model
    )


def get_claude_scoring_model(session: Session) -> str:
    """Return the configured scoring model: DB row override or Settings default."""
    return (
        _get_claude_model_row(session, SETTING_CLAUDE_SCORING_MODEL)
        or get_settings().claude_scoring_model
    )


def get_cowriter_provider(session: Session) -> str:
    stored = _get_claude_model_row(session, SETTING_COWRITER_PROVIDER)
    if stored is None:
        return COWRITER_DEFAULT_PROVIDER
    if stored not in COWRITER_PROVIDERS:
        msg = f"Unknown co-writer provider '{stored}'"
        raise ValueError(msg)
    return stored


def get_cowriter_model(session: Session, provider: str) -> str:
    stored = _get_claude_model_row(session, SETTING_COWRITER_MODEL)
    if stored:
        return stored
    if provider == "claude":
        return get_claude_chat_model(session)
    return ""


def set_cowriter_settings(session: Session, provider: str, model: str) -> None:
    set_claude_model(session, SETTING_COWRITER_PROVIDER, provider)
    set_claude_model(session, SETTING_COWRITER_MODEL, model)


def get_judge_provider(session: Session) -> str:
    stored = _get_claude_model_row(session, SETTING_JUDGE_PROVIDER)
    if stored is None:
        return JUDGE_DEFAULT_PROVIDER
    if stored not in COWRITER_PROVIDERS:
        msg = f"Unknown judge provider '{stored}'"
        raise ValueError(msg)
    return stored


def get_judge_model(session: Session, provider: str) -> str:
    """Return the configured judge model: DB row override, or — on the
    default provider — the pre-existing scoring-model setting, so a musician
    who never touches the new judge settings keeps today's behavior (#315).

    The stored model only counts when it was set for this same ``provider``
    — ``set_judge_settings`` writes both together, but the two are still
    separate rows, so a stored model left over from a different provider (or
    with no provider ever stored) is treated as unset rather than handed to
    a provider it was never configured for.
    """
    stored_provider = _get_claude_model_row(session, SETTING_JUDGE_PROVIDER)
    stored_model = _get_claude_model_row(session, SETTING_JUDGE_MODEL)
    if stored_model and stored_provider == provider:
        return stored_model
    if provider == "claude":
        return get_claude_scoring_model(session)
    return ""


def set_judge_settings(session: Session, provider: str, model: str) -> None:
    set_claude_model(session, SETTING_JUDGE_PROVIDER, provider)
    set_claude_model(session, SETTING_JUDGE_MODEL, model)


def get_cowriter_tail_token_budget(session: Session) -> int:
    row = (
        session.query(RateLimitSetting)
        .filter(
            RateLimitSetting.setting_key == SETTING_COWRITER_TAIL_TOKEN_BUDGET,
            RateLimitSetting.user_id.is_(None),
        )
        .first()
    )
    if row is None:
        return COWRITER_DEFAULT_TAIL_TOKEN_BUDGET
    return row.value


def set_cowriter_tail_token_budget(session: Session, budget: int) -> None:
    if budget < COWRITER_MIN_TAIL_TOKEN_BUDGET or budget > COWRITER_MAX_TAIL_TOKEN_BUDGET:
        msg = (
            f"tail_token_budget must be between "
            f"{COWRITER_MIN_TAIL_TOKEN_BUDGET} and {COWRITER_MAX_TAIL_TOKEN_BUDGET}"
        )
        raise ValueError(msg)
    row = (
        session.query(RateLimitSetting)
        .filter(
            RateLimitSetting.setting_key == SETTING_COWRITER_TAIL_TOKEN_BUDGET,
            RateLimitSetting.user_id.is_(None),
        )
        .first()
    )
    if row:
        row.value = budget
    else:
        row = RateLimitSetting(
            setting_key=SETTING_COWRITER_TAIL_TOKEN_BUDGET, value=budget,
        )
        session.add(row)
    session.flush()


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

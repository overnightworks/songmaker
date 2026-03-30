"""Settings API endpoints — generation presets and builtins."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from songmaker_cli.api_models import (
    GenerationDefaultsRequest,
    PresetCreateRequest,
    PresetResponse,
    PresetUpdateRequest,
    RateLimitItem,
    RateLimitsResponse,
    RateLimitUpdateRequest,
    StatusResponse,
    UserRateLimitsResponse,
)
from songmaker_cli.api_models.settings import DefaultConfigRequest, DefaultConfigResponse
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.config import (
    get_builtin_defaults,
    load_generation_defaults,
    save_generation_defaults,
)
from songmaker_cli.db.queries import (
    delete_all_user_rate_limits,
    get_all_global_rate_limits,
    get_user,
    get_user_rate_limits,
    record_audit,
    resolve_rate_limit,
    upsert_rate_limit_setting,
)
from songmaker_cli.db.queries.settings import (
    create_preset,
    delete_preset,
    get_preset,
    list_presets,
    list_shared_presets,
    name_exists,
    set_default_preset,
    update_preset,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user, require_admin

router = APIRouter()


@router.get("/settings/generation-builtins")
def api_get_builtins(
    _user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, dict[str, object]]:
    return get_builtin_defaults()


@router.get("/settings/generation-defaults")
def api_get_generation_defaults(
    _admin: AuthenticatedUser = Depends(require_admin),
    ctx: AppContext = Depends(get_app_context),
) -> dict[str, dict[str, object]]:
    return load_generation_defaults(ctx.db, ctx.data_dir)


@router.put("/settings/generation-defaults")
def api_set_generation_defaults(
    req: GenerationDefaultsRequest,
    _admin: AuthenticatedUser = Depends(require_admin),
    ctx: AppContext = Depends(get_app_context),
) -> dict[str, dict[str, object]]:
    data = {mode: params.to_dict() for mode, params in req.root.items()}
    save_generation_defaults(ctx.db, data)
    return data


@router.get("/settings/presets")
def api_list_presets(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[PresetResponse]:
    own = list_presets(session, user.id)
    shared = list_shared_presets(session)
    return [PresetResponse.from_orm(p) for p in [*own, *shared]]


@router.post("/settings/presets")
def api_create_preset(
    req: PresetCreateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PresetResponse:
    if name_exists(session, user.id, req.model_mode, req.name):
        raise HTTPException(409, "A preset with that name already exists")
    preset = create_preset(
        session,
        name=req.name,
        model_mode=req.model_mode,
        params=req.params.to_dict(),
        user_id=user.id,
        is_default=req.is_default,
    )
    record_audit(session, user.id, "create", "preset", preset.id, req.name)
    try:
        session.commit()
    except IntegrityError:
        raise HTTPException(409, "A preset with that name already exists")
    return PresetResponse.from_orm(preset)


@router.put("/settings/presets/{preset_id}")
def api_update_preset(
    preset_id: str,
    req: PresetUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PresetResponse:
    preset = get_preset(session, preset_id, user.id)
    if not preset:
        raise HTTPException(404, "Preset not found")
    if req.name is not None and req.name != preset.name:
        if name_exists(session, user.id, preset.model_mode, req.name):
            raise HTTPException(409, "A preset with that name already exists")
    params_dict = req.params.to_dict() if req.params is not None else None
    update_preset(session, preset, name=req.name, params=params_dict, is_default=req.is_default)
    try:
        session.commit()
    except IntegrityError:
        raise HTTPException(409, "A preset with that name already exists")
    return PresetResponse.from_orm(preset)


@router.delete("/settings/presets/{preset_id}")
def api_delete_preset(
    preset_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    if not delete_preset(session, preset_id, user.id):
        raise HTTPException(404, "Preset not found")
    record_audit(session, user.id, "delete", "preset", preset_id)
    session.commit()
    return StatusResponse()


@router.post("/settings/presets/{preset_id}/set-default")
def api_set_default_preset(
    preset_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PresetResponse:
    preset = get_preset(session, preset_id, user.id)
    if not preset:
        raise HTTPException(404, "Preset not found")
    set_default_preset(session, preset)
    session.commit()
    return PresetResponse.from_orm(preset)


# ── Default generation config ──────────────────────────────────────


VALID_BUILTIN_CONFIGS = frozenset({"sft", "turbo"})


@router.get("/settings/default-config")
def api_get_default_config(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> DefaultConfigResponse:
    from songmaker_cli.db.models import User
    db_user = session.query(User).filter_by(id=user.id).first()
    return DefaultConfigResponse(config=db_user.default_generation_config if db_user else None)


@router.put("/settings/default-config")
def api_set_default_config(
    req: DefaultConfigRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> DefaultConfigResponse:
    from songmaker_cli.db.models import User
    if req.config is not None and req.config not in VALID_BUILTIN_CONFIGS:
        preset = get_preset(session, req.config, user.id)
        if not preset:
            from songmaker_cli.db.queries.settings import list_shared_presets as _shared
            shared_ids = {p.id for p in _shared(session)}
            if req.config not in shared_ids:
                raise HTTPException(
                    400, "Invalid config: must be null, 'sft', 'turbo', or a preset ID",
                )
    db_user = session.query(User).filter_by(id=user.id).first()
    if not db_user:
        raise HTTPException(404, "User not found")
    db_user.default_generation_config = req.config
    record_audit(session, user.id, "update", "default_config", detail=req.config or "inherit")
    session.commit()
    return DefaultConfigResponse(config=req.config)


# ── Rate limits ────────────────────────────────────────────────────

_ENV_DEFAULTS = None


def _get_env_defaults() -> dict[str, int]:
    global _ENV_DEFAULTS
    if _ENV_DEFAULTS is None:
        from songmaker_cli.auth import (
            CHAT_RATE_LIMIT_USER,
            GENERATION_RATE_LIMIT_USER,
            MAX_QUEUE_DEPTH,
            MAX_USER_ACTIVE_JOBS,
            SCORING_RATE_LIMIT_USER,
        )
        from songmaker_cli.constants import (
            SETTING_CHAT_RATE_LIMIT,
            SETTING_GENERATION_RATE_LIMIT,
            SETTING_MAX_QUEUE_DEPTH,
            SETTING_MAX_USER_ACTIVE_JOBS,
            SETTING_SCORING_RATE_LIMIT,
        )

        _ENV_DEFAULTS = {
            SETTING_GENERATION_RATE_LIMIT: GENERATION_RATE_LIMIT_USER,
            SETTING_SCORING_RATE_LIMIT: SCORING_RATE_LIMIT_USER,
            SETTING_CHAT_RATE_LIMIT: CHAT_RATE_LIMIT_USER,
            SETTING_MAX_QUEUE_DEPTH: MAX_QUEUE_DEPTH,
            SETTING_MAX_USER_ACTIVE_JOBS: MAX_USER_ACTIVE_JOBS,
        }
    return _ENV_DEFAULTS


@router.get("/settings/rate-limits")
def api_get_rate_limits(
    _admin: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> RateLimitsResponse:
    env_defaults = _get_env_defaults()
    db_globals = {s.setting_key: s for s in get_all_global_rate_limits(session)}
    items = []
    for key, env_val in env_defaults.items():
        if key in db_globals:
            items.append(RateLimitItem.from_orm(db_globals[key]))
        else:
            items.append(RateLimitItem(setting_key=key, value=env_val))
    return RateLimitsResponse(settings=items)


@router.put("/settings/rate-limits")
def api_update_rate_limits(
    req: RateLimitUpdateRequest,
    admin: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> RateLimitsResponse:
    from songmaker_cli.constants import RATE_LIMIT_SETTING_KEYS

    invalid = set(req.settings.keys()) - RATE_LIMIT_SETTING_KEYS
    if invalid:
        raise HTTPException(400, f"Unknown setting keys: {sorted(invalid)}")
    for key, value in req.settings.items():
        if value < 0:
            raise HTTPException(400, f"Value for {key} must be non-negative")
        upsert_rate_limit_setting(session, key, value)
    record_audit(session, admin.id, "update", "rate_limits", detail="global")
    session.commit()
    return api_get_rate_limits(_admin=admin, session=session)


@router.get("/settings/rate-limits/user/{user_id}")
def api_get_user_rate_limits(
    user_id: str,
    _admin: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> UserRateLimitsResponse:
    if not get_user(session, user_id):
        raise HTTPException(404, "User not found")
    env_defaults = _get_env_defaults()
    overrides = get_user_rate_limits(session, user_id)
    override_items = [RateLimitItem.from_orm(o, is_override=True) for o in overrides]
    override_keys = {o.setting_key for o in overrides}
    effective = []
    for key, env_val in env_defaults.items():
        val = resolve_rate_limit(session, user_id, key, env_val)
        effective.append(RateLimitItem(
            setting_key=key, value=val, is_override=key in override_keys,
        ))
    return UserRateLimitsResponse(
        user_id=user_id, overrides=override_items, effective=effective,
    )


@router.put("/settings/rate-limits/user/{user_id}")
def api_update_user_rate_limits(
    user_id: str,
    req: RateLimitUpdateRequest,
    admin: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> UserRateLimitsResponse:
    from songmaker_cli.constants import RATE_LIMIT_SETTING_KEYS

    if not get_user(session, user_id):
        raise HTTPException(404, "User not found")
    invalid = set(req.settings.keys()) - RATE_LIMIT_SETTING_KEYS
    if invalid:
        raise HTTPException(400, f"Unknown setting keys: {sorted(invalid)}")
    for key, value in req.settings.items():
        if value < 0:
            raise HTTPException(400, f"Value for {key} must be non-negative")
        upsert_rate_limit_setting(session, key, value, user_id=user_id)
    record_audit(session, admin.id, "update", "rate_limits", user_id)
    session.commit()
    return api_get_user_rate_limits(user_id, _admin=admin, session=session)


@router.delete("/settings/rate-limits/user/{user_id}")
def api_delete_user_rate_limits(
    user_id: str,
    admin: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    if not get_user(session, user_id):
        raise HTTPException(404, "User not found")
    delete_all_user_rate_limits(session, user_id)
    record_audit(session, admin.id, "delete", "rate_limits", user_id)
    session.commit()
    return StatusResponse()

"""Settings API endpoints — generation presets and builtins."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_providers.claude.provider import is_available as is_claude_cli_available
from agent_providers.constants import COWRITER_PROVIDERS
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from webauth.ports import AuthenticatedUser

from songmaker_cli.api_helpers import gen_params_to_json
from songmaker_cli.api_models import (
    CapabilitiesResponse,
    GenerationDefaultsRequest,
    PresetCreateRequest,
    PresetResponse,
    PresetUpdateRequest,
    RateLimitItem,
    RateLimitsResponse,
    RateLimitUpdateRequest,
    StatusResponse,
)
from songmaker_cli.api_models.release import ReleaseInfo
from songmaker_cli.api_models.settings import (
    AvailableModelResponse,
    CoverSettingsRequest,
    CoverSettingsResponse,
    CowriterSettingsRequest,
    CowriterSettingsResponse,
    DefaultConfigRequest,
    DefaultConfigResponse,
    ProviderRouteReadiness,
    ProviderRouteStatusResponse,
    ProviderStatusResponse,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.auth_dependencies import get_current_user, require_admin
from songmaker_cli.config import (
    get_builtin_defaults,
    load_generation_defaults,
    save_generation_defaults,
)
from songmaker_cli.constants import (
    AuditAction,
    ResourceType,
)
from songmaker_cli.db.queries.auth import record_audit
from songmaker_cli.db.queries.rate_limits import (
    get_all_global_rate_limits,
    upsert_rate_limit_setting,
)
from songmaker_cli.db.queries.settings import (
    create_preset,
    delete_preset,
    get_claude_chat_model,
    get_cover_settings,
    get_cowriter_tail_token_budget,
    get_preset,
    list_active_models,
    list_all_models,
    list_presets,
    list_shared_presets,
    name_exists,
    set_cover_settings,
    set_cowriter_tail_token_budget,
    set_default_preset,
    toggle_model,
    update_preset,
)
from songmaker_cli.settings import get_settings

if TYPE_CHECKING:
    from songmaker_cli.provider_status import ProviderSnapshot

router = APIRouter()

PRESET_NAME_EXISTS_DETAIL = "A preset with that name already exists"
PRESET_NOT_FOUND_DETAIL = "Preset not found"
USER_NOT_FOUND_DETAIL = "User not found"


@router.get("/settings/generation-builtins")
def api_get_builtins(
    _user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, dict[str, object]]:
    return get_builtin_defaults()


@router.get("/settings/generation-defaults")
def api_get_generation_defaults(
    _user: AuthenticatedUser = Depends(get_current_user),
    ctx: AppContext = Depends(get_app_context),
) -> dict[str, dict[str, object]]:
    return load_generation_defaults(ctx.db, ctx.data_dir)


@router.put("/settings/generation-defaults")
def api_set_generation_defaults(
    req: GenerationDefaultsRequest,
    _admin: AuthenticatedUser = Depends(require_admin),
    ctx: AppContext = Depends(get_app_context),
) -> dict[str, dict[str, object]]:
    data = {mode: gen_params_to_json(params) or {} for mode, params in req.root.items()}
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


@router.post(
    "/settings/presets",
    responses={
        400: {"description": "Requested model is not available"},
        409: {"description": PRESET_NAME_EXISTS_DETAIL},
    },
)
def api_create_preset(
    req: PresetCreateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PresetResponse:
    active_ids = {m.id for m in list_active_models(session)}
    if req.model_mode not in active_ids:
        raise HTTPException(400, f"Model '{req.model_mode}' is not available")
    if name_exists(session, user.id, req.model_mode, req.name):
        raise HTTPException(409, PRESET_NAME_EXISTS_DETAIL)
    preset = create_preset(
        session,
        name=req.name,
        model_mode=req.model_mode,
        params=gen_params_to_json(req.params) or {},
        user_id=user.id,
        is_default=req.is_default,
    )
    record_audit(session, user.id, AuditAction.CREATE, ResourceType.PRESET, preset.id, req.name)
    try:
        session.commit()
    except IntegrityError:
        raise HTTPException(409, PRESET_NAME_EXISTS_DETAIL)
    return PresetResponse.from_orm(preset)


@router.put(
    "/settings/presets/{preset_id}",
    responses={
        404: {"description": "Preset does not exist"},
        409: {"description": PRESET_NAME_EXISTS_DETAIL},
    },
)
def api_update_preset(
    preset_id: str,
    req: PresetUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PresetResponse:
    preset = get_preset(session, preset_id, user.id)
    if not preset:
        raise HTTPException(404, PRESET_NOT_FOUND_DETAIL)
    if req.name is not None and req.name != preset.name:
        if name_exists(session, user.id, preset.model_mode, req.name):
            raise HTTPException(409, PRESET_NAME_EXISTS_DETAIL)
    params_dict = gen_params_to_json(req.params) if req.params is not None else None
    update_preset(session, preset, name=req.name, params=params_dict, is_default=req.is_default)
    try:
        session.commit()
    except IntegrityError:
        raise HTTPException(409, PRESET_NAME_EXISTS_DETAIL)
    return PresetResponse.from_orm(preset)


@router.delete(
    "/settings/presets/{preset_id}",
    responses={404: {"description": "Preset does not exist"}},
)
def api_delete_preset(
    preset_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    if not delete_preset(session, preset_id, user.id):
        raise HTTPException(404, PRESET_NOT_FOUND_DETAIL)
    record_audit(session, user.id, AuditAction.DELETE, ResourceType.PRESET, preset_id)
    session.commit()
    return StatusResponse()


@router.post(
    "/settings/presets/{preset_id}/set-default",
    responses={404: {"description": "Preset does not exist"}},
)
def api_set_default_preset(
    preset_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PresetResponse:
    preset = get_preset(session, preset_id, user.id)
    if not preset:
        raise HTTPException(404, PRESET_NOT_FOUND_DETAIL)
    set_default_preset(session, preset)
    session.commit()
    return PresetResponse.from_orm(preset)


# ── Available models ───────────────────────────────────────────────


def _build_model_response(model) -> AvailableModelResponse:
    from songmaker_cli.api_models.settings import ModelCapabilities
    from songmaker_cli.config import get_builtin_defaults, get_model_capabilities

    builtin_defaults = get_builtin_defaults()
    capabilities_table = get_model_capabilities()
    if model.id not in builtin_defaults or model.id not in capabilities_table:
        msg = (
            f"Model '{model.id}' is registered in the database but missing "
            f"from get_builtin_defaults()/get_model_capabilities(). "
            f"Add it to _BUILTIN_DEFAULTS and ACESTEP_PROFILES, or remove the "
            f"row from available_models."
        )
        raise RuntimeError(msg)
    caps = capabilities_table[model.id]
    capabilities = ModelCapabilities(
        defaults=builtin_defaults[model.id],
        max_inference_steps=caps["max_inference_steps"],
        hidden_params=caps["hidden_params"],
    )
    return AvailableModelResponse(
        id=model.id, is_active=model.is_active, capabilities=capabilities,
    )


@router.get("/settings/models")
def api_list_active_models(
    _user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[AvailableModelResponse]:
    models = list_active_models(session)
    return [_build_model_response(m) for m in models]


@router.get("/settings/models/all")
def api_list_all_models(
    _admin: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> list[AvailableModelResponse]:
    models = list_all_models(session)
    return [_build_model_response(m) for m in models]


@router.put(
    "/settings/models/{model_id}",
    responses={404: {"description": "Model does not exist"}},
)
def api_toggle_model(
    model_id: str,
    active: bool,
    admin: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> AvailableModelResponse:
    model = toggle_model(session, model_id, active)
    if not model:
        raise HTTPException(404, "Model not found")
    record_audit(
        session, admin.id, AuditAction.UPDATE, ResourceType.MODEL,
        model_id, f"active={active}",
    )
    session.commit()
    return AvailableModelResponse(id=model.id, is_active=model.is_active)


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


@router.put(
    "/settings/default-config",
    responses={
        400: {"description": "Default configuration is invalid"},
        404: {"description": "User does not exist"},
    },
)
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
        raise HTTPException(404, USER_NOT_FOUND_DETAIL)
    db_user.default_generation_config = req.config
    record_audit(
        session, user.id, AuditAction.UPDATE, ResourceType.DEFAULT_CONFIG,
        detail=req.config or "inherit",
    )
    session.commit()
    return DefaultConfigResponse(config=req.config)


# ── Capabilities ─────────────────────────────────────────────────


@router.get("/capabilities")
def api_capabilities(
    _user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> CapabilitiesResponse:
    api_key = get_settings().anthropic_api_key
    return CapabilitiesResponse(
        claude_api=api_key is not None and bool(api_key.get_secret_value()),
        claude_cli=is_claude_cli_available(api_key=None),
        generation=True,
        scoring=True,
        chat_model=get_claude_chat_model(session),
    )


# ── Release ──────────────────────────────────────────────────────


@router.get("/release")
def api_release(_user: AuthenticatedUser = Depends(get_current_user)) -> ReleaseInfo:
    return ReleaseInfo.from_settings(get_settings())


# ── Provider reachability (shared by Co-Writer and Scoring) ────────


@router.get("/settings/providers")
def api_get_provider_status(
    _admin: AuthenticatedUser = Depends(require_admin),
) -> list[ProviderStatusResponse]:
    from songmaker_cli.provider_status import provider_snapshots

    snapshots = provider_snapshots()

    return [
        ProviderStatusResponse(
            provider=name,
            cowriter_routes=_route_statuses(snapshots.get(name)),
            cover_routes=_cover_route_readiness(name),
        )
        for name in sorted(COWRITER_PROVIDERS)
    ]


def _cover_route_readiness(provider: str) -> dict[str, ProviderRouteReadiness]:
    """Project the one image-capability answer for every route of one provider."""
    from agent_providers.catalog import (
        ProviderRoute,
        ProviderRouteCapability,
        ProviderRouteReadinessState,
        route_setup_label,
    )
    from agent_providers.dispatch import cover_image_capability

    readiness: dict[str, ProviderRouteReadiness] = {}
    for route in ProviderRoute:
        capability = cover_image_capability(provider, route)
        readiness[route.value] = ProviderRouteReadiness(
            state=(
                ProviderRouteReadinessState.READY
                if capability.failure is None
                else ProviderRouteReadinessState.NOT_CONFIGURED
            ).value,
            capability=(
                ProviderRouteCapability.TOOLS_AVAILABLE
                if capability.carries_image_tool
                else ProviderRouteCapability.TEXT_ONLY
            ).value,
            reason=capability.failure,
            setup_label=route_setup_label(route),
        )
    return readiness


def _cowriter_response(session: Session) -> CowriterSettingsResponse:
    return CowriterSettingsResponse(
        tail_token_budget=get_cowriter_tail_token_budget(session),
    )


def _route_statuses(
    snapshot: "ProviderSnapshot | None",
) -> dict[str, ProviderRouteStatusResponse]:
    from agent_providers.catalog import (
        ProviderRoute,
        ProviderRouteReadinessState,
        provider_route_capability,
        route_setup_label,
    )

    if snapshot is None:
        return {
            route.value: ProviderRouteStatusResponse(
                models=[],
                readiness=ProviderRouteReadiness(
                    state=ProviderRouteReadinessState.UNVERIFIED.value,
                    capability=provider_route_capability().value,
                    setup_label=route_setup_label(route),
                ),
            )
            for route in ProviderRoute
        }
    result: dict[str, ProviderRouteStatusResponse] = {}
    for route, route_snapshot in snapshot.routes.items():
        result[route.value] = ProviderRouteStatusResponse(
            models=list(route_snapshot.models),
            catalogue_failure=route_snapshot.catalogue_failure,
            catalog_source=route_snapshot.catalog_source,
            catalog_version=route_snapshot.catalog_version,
            readiness=ProviderRouteReadiness(
                state=route_snapshot.readiness.value,
                capability=route_snapshot.capability.value,
                reason=route_snapshot.reason,
                probed_at=route_snapshot.probed_at.isoformat(),
                setup_label=route_snapshot.setup_label,
            ),
        )
    return result


@router.get("/settings/cowriter")
def api_get_cowriter_settings(
    _user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> CowriterSettingsResponse:
    return _cowriter_response(session)


@router.put(
    "/settings/cowriter",
    responses={422: {"description": "The tail token budget is out of range or a field is unknown"}},
)
def api_set_cowriter_settings(
    req: CowriterSettingsRequest,
    admin: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> CowriterSettingsResponse:
    try:
        set_cowriter_tail_token_budget(session, req.tail_token_budget)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    record_audit(
        session, admin.id, AuditAction.UPDATE, ResourceType.COWRITER,
        detail=f"tail_token_budget={req.tail_token_budget}",
    )
    session.commit()
    return _cowriter_response(session)


# ── Cover provider settings ─────────────────────────────────────────


def _cover_response(session: Session) -> CoverSettingsResponse:
    selection = get_cover_settings(session)
    return CoverSettingsResponse(
        provider=selection.provider,
        route=selection.route,
        model=selection.model,
        allowed_providers=sorted(COWRITER_PROVIDERS),
    )


@router.get("/settings/cover")
def api_get_cover_settings(
    _admin: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> CoverSettingsResponse:
    return _cover_response(session)


@router.put(
    "/settings/cover",
    responses={422: {"description": "Unknown cover provider or route"}},
)
def api_set_cover_settings(
    req: CoverSettingsRequest,
    admin: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> CoverSettingsResponse:
    """Persist the cover selection, including one no route can currently run."""
    from agent_providers.catalog import ProviderRoute

    if req.provider not in COWRITER_PROVIDERS:
        raise HTTPException(422, f"Unknown cover provider '{req.provider}'")
    if req.route not in {route.value for route in ProviderRoute}:
        raise HTTPException(422, f"Unknown cover route '{req.route}'")
    set_cover_settings(session, req.provider, req.route, req.model)
    record_audit(
        session, admin.id, AuditAction.UPDATE, ResourceType.COVER,
        detail=f"provider={req.provider} route={req.route} model={req.model}",
    )
    session.commit()
    return _cover_response(session)


# ── Rate limits ────────────────────────────────────────────────────

def _get_env_defaults() -> dict[str, int]:
    """Snapshot of the per-user rate-limit defaults from Settings."""
    from songmaker_cli.constants import (
        SETTING_CHAT_RATE_LIMIT,
        SETTING_GENERATION_RATE_LIMIT,
        SETTING_MAX_QUEUE_DEPTH,
        SETTING_MAX_USER_ACTIVE_JOBS,
        SETTING_SCORING_RATE_LIMIT,
    )
    settings = get_settings()
    return {
        SETTING_GENERATION_RATE_LIMIT: settings.generation_rate_limit_user,
        SETTING_SCORING_RATE_LIMIT: settings.scoring_rate_limit_user,
        SETTING_CHAT_RATE_LIMIT: settings.chat_rate_limit_user,
        SETTING_MAX_QUEUE_DEPTH: settings.max_queue_depth,
        SETTING_MAX_USER_ACTIVE_JOBS: settings.max_user_active_jobs,
    }


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


@router.put(
    "/settings/rate-limits",
    responses={400: {"description": "Rate-limit setting or value is invalid"}},
)
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
    record_audit(session, admin.id, AuditAction.UPDATE, ResourceType.RATE_LIMITS, detail="global")
    session.commit()
    return api_get_rate_limits(_admin=admin, session=session)

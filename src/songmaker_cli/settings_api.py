"""Settings API endpoints — generation presets and builtins."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_providers.constants import COWRITER_PROVIDERS
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from webauth.dependencies import AuthenticatedUser

from songmaker_cli.api_helpers import gen_params_to_json
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
from songmaker_cli.api_models.settings import (
    AvailableModelResponse,
    ClaudeModelsRequest,
    ClaudeModelsResponse,
    CoverSettingsRequest,
    CoverSettingsResponse,
    CowriterSettingsRequest,
    CowriterSettingsResponse,
    DefaultConfigRequest,
    DefaultConfigResponse,
    JudgeSettingsRequest,
    JudgeSettingsResponse,
    ProviderRouteReadiness,
    ProviderRouteStatusResponse,
    ProviderStatusResponse,
    ProviderSurfaceState,
    ProviderSurfaceStatus,
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
from songmaker_cli.db.queries import (
    delete_all_user_rate_limits,
    get_all_global_rate_limits,
    get_raw_stored_cowriter_settings,
    get_raw_stored_judge_settings,
    get_user,
    get_user_rate_limits,
    record_audit,
    resolve_rate_limit,
    upsert_rate_limit_setting,
)
from songmaker_cli.db.queries.settings import (
    create_preset,
    delete_preset,
    get_claude_chat_model,
    get_claude_scoring_model,
    get_cover_settings,
    get_cowriter_model,
    get_cowriter_models_by_provider,
    get_cowriter_provider,
    get_cowriter_tail_token_budget,
    get_effective_provider_routes,
    get_judge_model,
    get_judge_provider,
    get_judge_route,
    get_preset,
    list_active_models,
    list_all_models,
    list_presets,
    list_shared_presets,
    name_exists,
    set_claude_model,
    set_cover_settings,
    set_cowriter_settings,
    set_cowriter_tail_token_budget,
    set_default_preset,
    set_judge_settings,
    stored_provider_is_retired,
    toggle_model,
    update_preset,
)

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


# ── Claude model settings ─────────────────────────────────────────


@router.get("/settings/claude-models")
def api_get_claude_models(
    _admin: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ClaudeModelsResponse:
    from songmaker_cli.constants import MODEL_ALLOWED_CLAUDE

    return ClaudeModelsResponse(
        chat_model=get_claude_chat_model(session),
        scoring_model=get_claude_scoring_model(session),
        allowed_models=sorted(MODEL_ALLOWED_CLAUDE),
    )


@router.put(
    "/settings/claude-models",
    responses={400: {"description": "Selected Claude model is not allowed"}},
)
def api_set_claude_models(
    req: ClaudeModelsRequest,
    admin: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ClaudeModelsResponse:
    from songmaker_cli.constants import (
        MODEL_ALLOWED_CLAUDE,
        SETTING_CLAUDE_CHAT_MODEL,
        SETTING_CLAUDE_SCORING_MODEL,
    )

    if req.chat_model not in MODEL_ALLOWED_CLAUDE:
        raise HTTPException(400, f"Invalid chat model. Allowed: {sorted(MODEL_ALLOWED_CLAUDE)}")
    if req.scoring_model not in MODEL_ALLOWED_CLAUDE:
        raise HTTPException(400, f"Invalid scoring model. Allowed: {sorted(MODEL_ALLOWED_CLAUDE)}")

    set_claude_model(session, SETTING_CLAUDE_CHAT_MODEL, req.chat_model)
    set_claude_model(session, SETTING_CLAUDE_SCORING_MODEL, req.scoring_model)
    record_audit(session, admin.id, AuditAction.UPDATE, ResourceType.CLAUDE_MODELS,
                 detail=f"chat={req.chat_model} scoring={req.scoring_model}")
    session.commit()

    return ClaudeModelsResponse(
        chat_model=get_claude_chat_model(session),
        scoring_model=get_claude_scoring_model(session),
        allowed_models=sorted(MODEL_ALLOWED_CLAUDE),
    )


# ── Provider reachability (shared by Co-Writer and Scoring) ────────


@router.get(
    "/settings/providers",
    responses={422: {"description": "Stored judge route is invalid"}},
)
def api_get_provider_status(
    _admin: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> list[ProviderStatusResponse]:
    from songmaker_cli.provider_status import provider_snapshots

    snapshots = provider_snapshots()
    routes = get_effective_provider_routes(session)
    try:
        judge_route = get_judge_route(session)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    return [
        ProviderStatusResponse(
            provider=name,
            cowriter=_surface_status_from_snapshot(
                name, snapshots.get(name), routes[name],
            ),
            judge=_surface_status_from_snapshot(
                name, snapshots.get(name), judge_route,
            ),
            cowriter_routes=_route_statuses(snapshots.get(name), None),
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


def _surface_status_from_snapshot(
    provider: str,
    snapshot: "ProviderSnapshot | None",
    selected_route: str,
) -> ProviderSurfaceStatus:
    if snapshot is None:
        return ProviderSurfaceStatus(state=ProviderSurfaceState.UNVERIFIED)
    route_status = _route_statuses(snapshot, None)[selected_route]
    if route_status.readiness.state == "ready":
        return ProviderSurfaceStatus(
            state=ProviderSurfaceState.CONFIGURED,
            setup_method="api_key" if selected_route == "api" else f"{provider}_cli",
            probed_at=route_status.readiness.probed_at,
        )
    if route_status.readiness.state == "not_configured":
        return ProviderSurfaceStatus(
            state=ProviderSurfaceState.UNCONFIGURED,
            needs="api_key" if selected_route == "api" else "cli_login",
            probed_at=route_status.readiness.probed_at,
        )
    return ProviderSurfaceStatus(
        state=ProviderSurfaceState.MISSING_DEPENDENCY,
        probed_at=route_status.readiness.probed_at,
    )


def _live_catalogue(provider: str, route: str) -> list[str]:
    """The models this provider lists on that route right now.

    Empty when the catalogue is unavailable — an unverified provider, a failed
    listing, or a route the provider is not set up for all list nothing.
    """
    from songmaker_cli.provider_status import provider_snapshot

    models, _unavailable = _models_from_route_snapshot(
        None, provider_snapshot(provider), route,
    )
    return models


def _models_from_route_snapshot(
    active_model: str | None,
    snapshot: "ProviderSnapshot | None",
    route: str,
) -> tuple[list[str], str | None]:
    from agent_providers.catalog import models_with_active_model

    if snapshot is None:
        return [], "Provider model catalog is unverified"
    route_snapshot = next(item for key, item in snapshot.routes.items() if key.value == route)
    models = models_with_active_model(list(route_snapshot.models), active_model)
    error = route_snapshot.catalogue_failure
    return models, error.message if error else None


def _provider_probe_times(
    snapshots: dict[str, "ProviderSnapshot"],
) -> dict[str, str | None]:
    return {
        provider: snapshots[provider].probed_at.isoformat()
        if provider in snapshots
        else None
        for provider in sorted(COWRITER_PROVIDERS)
    }


def _cowriter_response(session) -> CowriterSettingsResponse:
    from songmaker_cli.provider_status import provider_snapshots

    provider = get_cowriter_provider(session)
    model = get_cowriter_model(session, provider)
    saved_models = get_cowriter_models_by_provider(session)
    routes = get_effective_provider_routes(session)
    snapshots = provider_snapshots()
    models_by_provider: dict[str, list[str]] = {}
    errors: dict[str, str] = {}
    sources: dict[str, str] = {}
    current_models_not_in_catalog: dict[str, str] = {}
    selected_models_by_provider: dict[str, str] = {}
    route_statuses_by_provider: dict[str, dict[str, ProviderRouteStatusResponse]] = {}
    for name in sorted(COWRITER_PROVIDERS):
        snapshot = snapshots.get(name)
        route_statuses = _route_statuses(snapshot, saved_models[name] or None)
        route_statuses_by_provider[name] = route_statuses
        selected = route_statuses[routes[name]]
        catalog_models = selected.models
        models = catalog_models
        error = selected.catalogue_failure.message if selected.catalogue_failure else None
        models_by_provider[name] = models
        if error:
            errors[name] = error
        if selected.catalog_source is not None:
            sources[name] = selected.catalog_source
        selected_models_by_provider[name] = saved_models[name]
        if selected.retained_model_id is not None:
            current_models_not_in_catalog[name] = saved_models[name]
    return CowriterSettingsResponse(
        provider=provider,
        model=model,
        allowed_providers=sorted(COWRITER_PROVIDERS),
        allowed_models=models_by_provider[provider],
        models_by_provider=models_by_provider,
        selected_models_by_provider=selected_models_by_provider,
        models_errors=errors,
        models_sources=sources,
        current_models_not_in_catalog=current_models_not_in_catalog,
        probed_at=_provider_probe_times(snapshots),
        tail_token_budget=get_cowriter_tail_token_budget(session),
        provider_routes=routes,
        provider_routes_status=route_statuses_by_provider,
    )


def _route_statuses(
    snapshot: "ProviderSnapshot | None",
    active_model: str | None,
) -> dict[str, ProviderRouteStatusResponse]:
    from agent_providers.catalog import (
        ProviderRoute,
        ProviderRouteReadinessState,
        models_with_active_model,
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
        models = models_with_active_model(list(route_snapshot.models), active_model)
        retained = (
            active_model
            if active_model and active_model not in route_snapshot.models
            else None
        )
        result[route.value] = ProviderRouteStatusResponse(
            models=models,
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
            retained_model_id=retained,
        )
    return result


@router.get(
    "/settings/cowriter",
    responses={422: {"description": "Stored co-writer configuration is invalid"}},
)
def api_get_cowriter_settings(
    _user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> CowriterSettingsResponse:
    try:
        return _cowriter_response(session)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _require_selectable_model(
    provider: str,
    model: str,
    catalogue: list[str],
    row_model: str,
) -> None:
    """Accept a model the provider lists, the one this row already carries, or
    no model at all while the catalogue lists nothing.

    An empty model is a deliberate saved value there: the row shows "No models"
    with its reason, and the next turn or job fails with that named reason.
    """
    if model in catalogue or (model != "" and model == row_model):
        return
    if model == "" and not catalogue:
        return
    raise HTTPException(422, f"Unknown {provider} model '{model}'")


def _model_the_provider_row_shows(session: Session, provider: str) -> str:
    """The model this provider's row carries today, saved or defaulted.

    A saved provider that no longer exists leaves the rows nothing to keep.
    """
    if stored_provider_is_retired(get_raw_stored_cowriter_settings(session).provider):
        return ""
    return get_cowriter_models_by_provider(session)[provider]


@router.put(
    "/settings/cowriter",
    responses={422: {"description": "Co-writer provider, route, or model is unknown"}},
)
def api_set_cowriter_settings(
    req: CowriterSettingsRequest,
    admin: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> CowriterSettingsResponse:
    """Save the choice on its form alone; whether it runs is the row's status."""
    if req.provider not in COWRITER_PROVIDERS:
        raise HTTPException(
            422, f"Unknown co-writer provider '{req.provider}'",
        )
    routes = _cowriter_routes(session, req)
    _require_selectable_model(
        req.provider,
        req.model,
        _live_catalogue(req.provider, routes[req.provider]),
        _model_the_provider_row_shows(session, req.provider),
    )
    set_cowriter_settings(session, req.provider, req.model, routes)
    if req.tail_token_budget is not None:
        try:
            set_cowriter_tail_token_budget(session, req.tail_token_budget)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    record_audit(
        session, admin.id, AuditAction.UPDATE, ResourceType.COWRITER,
        detail=(
            f"provider={req.provider} model={req.model} "
            f"routes={','.join(f'{name}={routes[name]}' for name in sorted(routes))}"
        ),
    )
    session.commit()
    return _cowriter_response(session)


def _cowriter_routes(session: Session, req: CowriterSettingsRequest) -> dict[str, str]:
    try:
        stored_routes = get_effective_provider_routes(session)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return req.provider_routes or stored_routes


# ── Judge (lyrical-coherence) provider settings ─────────────────────


def _model_the_judge_row_shows(session: Session, provider: str) -> str:
    stored = get_raw_stored_judge_settings(session)
    if stored.provider == provider and stored.model is not None:
        return stored.model
    return get_judge_model(session, provider)


def _judge_response(session: Session) -> JudgeSettingsResponse:
    from songmaker_cli.provider_status import provider_snapshots

    provider = get_judge_provider(session)
    route = get_judge_route(session)
    model = _model_the_judge_row_shows(session, provider)
    snapshots = provider_snapshots()
    models_by_provider: dict[str, list[str]] = {}
    errors: dict[str, str] = {}
    route_statuses_by_provider: dict[str, dict[str, ProviderRouteStatusResponse]] = {}
    for name in sorted(COWRITER_PROVIDERS):
        route_statuses = _route_statuses(
            snapshots.get(name), model if name == provider else None,
        )
        route_statuses_by_provider[name] = route_statuses
        selected = route_statuses[route]
        models_by_provider[name] = selected.models
        if selected.catalogue_failure:
            errors[name] = selected.catalogue_failure.message
        elif snapshots.get(name) is None:
            errors[name] = "Provider model catalog is unverified"
    return JudgeSettingsResponse(
        provider=provider,
        route=route,
        model=model,
        allowed_providers=sorted(COWRITER_PROVIDERS),
        allowed_models=models_by_provider[provider],
        models_by_provider=models_by_provider,
        models_errors=errors,
        probed_at=_provider_probe_times(snapshots),
        provider_routes_status=route_statuses_by_provider,
    )


@router.get(
    "/settings/judge",
    responses={422: {"description": "Stored judge configuration is invalid"}},
)
def api_get_judge_settings(
    _admin: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> JudgeSettingsResponse:
    try:
        return _judge_response(session)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.put(
    "/settings/judge",
    responses={422: {"description": "Judge provider, route, or model is unknown"}},
)
def api_set_judge_settings(
    req: JudgeSettingsRequest,
    admin: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> JudgeSettingsResponse:
    """Save the choice on its form alone; whether it runs is the row's status."""
    if req.provider not in COWRITER_PROVIDERS:
        raise HTTPException(
            422, f"Unknown judge provider '{req.provider}'",
        )
    try:
        route = req.route if req.route is not None else get_judge_route(session)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _require_selectable_model(
        req.provider,
        req.model,
        _live_catalogue(req.provider, route),
        _model_the_judge_row_shows(session, req.provider),
    )
    set_judge_settings(session, req.provider, route, req.model)
    record_audit(
        session, admin.id, AuditAction.UPDATE, ResourceType.JUDGE,
        detail=f"provider={req.provider} route={route} model={req.model}",
    )
    session.commit()
    return _judge_response(session)


# ── Cover provider settings ─────────────────────────────────────────


def _cover_response(session: Session) -> CoverSettingsResponse:
    selection = get_cover_settings(session)
    return CoverSettingsResponse(
        provider=selection.provider,
        route=selection.route,
        model=selection.model,
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
    from songmaker_cli.settings import get_settings

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


@router.get(
    "/settings/rate-limits/user/{user_id}",
    responses={404: {"description": "User does not exist"}},
)
def api_get_user_rate_limits(
    user_id: str,
    _admin: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> UserRateLimitsResponse:
    if not get_user(session, user_id):
        raise HTTPException(404, USER_NOT_FOUND_DETAIL)
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


@router.put(
    "/settings/rate-limits/user/{user_id}",
    responses={
        400: {"description": "Rate-limit setting or value is invalid"},
        404: {"description": "User does not exist"},
    },
)
def api_update_user_rate_limits(
    user_id: str,
    req: RateLimitUpdateRequest,
    admin: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> UserRateLimitsResponse:
    from songmaker_cli.constants import RATE_LIMIT_SETTING_KEYS

    if not get_user(session, user_id):
        raise HTTPException(404, USER_NOT_FOUND_DETAIL)
    invalid = set(req.settings.keys()) - RATE_LIMIT_SETTING_KEYS
    if invalid:
        raise HTTPException(400, f"Unknown setting keys: {sorted(invalid)}")
    for key, value in req.settings.items():
        if value < 0:
            raise HTTPException(400, f"Value for {key} must be non-negative")
        upsert_rate_limit_setting(session, key, value, user_id=user_id)
    record_audit(session, admin.id, AuditAction.UPDATE, ResourceType.RATE_LIMITS, user_id)
    session.commit()
    return api_get_user_rate_limits(user_id, _admin=admin, session=session)


@router.delete(
    "/settings/rate-limits/user/{user_id}",
    responses={404: {"description": "User does not exist"}},
)
def api_delete_user_rate_limits(
    user_id: str,
    admin: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    if not get_user(session, user_id):
        raise HTTPException(404, USER_NOT_FOUND_DETAIL)
    delete_all_user_rate_limits(session, user_id)
    record_audit(session, admin.id, AuditAction.DELETE, ResourceType.RATE_LIMITS, user_id)
    session.commit()
    return StatusResponse()

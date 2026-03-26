"""Settings API endpoints — generation presets and builtins."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from songmaker_cli.api_models import (
    GenerationDefaultsRequest,
    PresetCreateRequest,
    PresetResponse,
    PresetUpdateRequest,
    StatusResponse,
)
from songmaker_cli.config import (
    get_builtin_defaults,
    load_generation_defaults,
    save_generation_defaults,
)
from songmaker_cli.db.engine import get_db_session
from songmaker_cli.db.queries import record_audit
from songmaker_cli.db.queries.settings import (
    create_preset,
    delete_preset,
    get_preset,
    list_presets,
    name_exists,
    set_default_preset,
    update_preset,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user, require_admin

router = APIRouter()

_get_session = get_db_session


@router.get("/settings/generation-builtins")
def api_get_builtins(
    _user: AuthenticatedUser = Depends(get_current_user),
) -> dict:
    return get_builtin_defaults()


@router.get("/settings/generation-defaults")
def api_get_generation_defaults(
    _admin: AuthenticatedUser = Depends(require_admin),
) -> dict:
    return load_generation_defaults()


@router.put("/settings/generation-defaults")
def api_set_generation_defaults(
    req: GenerationDefaultsRequest,
    _admin: AuthenticatedUser = Depends(require_admin),
) -> dict:
    data: dict = {}
    if req.turbo is not None:
        data["turbo"] = req.turbo.to_dict()
    if req.sft is not None:
        data["sft"] = req.sft.to_dict()
    save_generation_defaults(data)
    return data


@router.get("/settings/presets")
def api_list_presets(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(_get_session),
) -> list[PresetResponse]:
    presets = list_presets(session, user.id)
    return [PresetResponse.from_orm(p) for p in presets]


@router.post("/settings/presets")
def api_create_preset(
    req: PresetCreateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(_get_session),
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
    session.commit()
    return PresetResponse.from_orm(preset)


@router.put("/settings/presets/{preset_id}")
def api_update_preset(
    preset_id: str,
    req: PresetUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(_get_session),
) -> PresetResponse:
    preset = get_preset(session, preset_id, user.id)
    if not preset:
        raise HTTPException(404, "Preset not found")
    if req.name is not None and req.name != preset.name:
        if name_exists(session, user.id, preset.model_mode, req.name):
            raise HTTPException(409, "A preset with that name already exists")
    params_dict = req.params.to_dict() if req.params is not None else None
    update_preset(session, preset, name=req.name, params=params_dict, is_default=req.is_default)
    session.commit()
    return PresetResponse.from_orm(preset)


@router.delete("/settings/presets/{preset_id}")
def api_delete_preset(
    preset_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(_get_session),
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
    session: Session = Depends(_get_session),
) -> PresetResponse:
    preset = get_preset(session, preset_id, user.id)
    if not preset:
        raise HTTPException(404, "Preset not found")
    set_default_preset(session, preset)
    session.commit()
    return PresetResponse.from_orm(preset)

"""A take's judged state: rating, pick, keep and unarchive API endpoints."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from webauth.ports import AuthenticatedUser

from songmaker_cli.agent.mcp import ToolEffect, agent_tool
from songmaker_cli.api_helpers import GENERATION_NOT_FOUND_DETAIL, check_generation_access
from songmaker_cli.api_models import RateRequest, RateResponse, StatusResponse
from songmaker_cli.app_context import get_db_session
from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.db.queries.generations import (
    ARCHIVED_TAKE_DETAIL,
    ArchivedTakeError,
    keep_generation,
    pick_generation,
    save_rating,
    unarchive_generation,
    unkeep_generation,
    unpick_generation,
)

router = APIRouter()


_RATE_TAKE_DESCRIPTION = (
    "Save the person's rating and notes on one of their own takes. "
    "The notes sent replace the saved ones, so a rating without notes clears them."
)


@router.post(
    "/generations/{gen_id}/rate",
    description=_RATE_TAKE_DESCRIPTION,
    openapi_extra=agent_tool(name="rate_take", effect=ToolEffect.SIDE_EFFECTING),
)
def api_rate_generation(
    gen_id: str, req: RateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> RateResponse:
    check_generation_access(session, gen_id, user)
    save_rating(session, gen_id, req.rating, req.notes)
    session.commit()
    return RateResponse(generation_id=gen_id, rating=req.rating)



# ── Pick ─────────────────────────────────────────────────────────────


def _toggle_generation(
    gen_id: str, user: AuthenticatedUser, session: Session,
    action: Callable[[Session, str], None],
) -> StatusResponse:
    check_generation_access(session, gen_id, user)
    try:
        action(session, gen_id)
    except ValueError:
        raise HTTPException(404, GENERATION_NOT_FOUND_DETAIL)
    session.commit()
    return StatusResponse()


def _mark_generation(
    gen_id: str, user: AuthenticatedUser, session: Session,
    action: Callable[[Session, str], None],
) -> StatusResponse:
    """Toggle a mark that an archived take refuses with 409."""
    try:
        return _toggle_generation(gen_id, user, session, action)
    except ArchivedTakeError:
        raise HTTPException(409, ARCHIVED_TAKE_DETAIL)


_PICK_TAKE_DESCRIPTION = (
    "Pick one of the person's own takes as its song's chosen take. "
    "The song's previous pick loses its protection from cleanup."
)


@router.post(
    "/generations/{gen_id}/pick",
    description=_PICK_TAKE_DESCRIPTION,
    openapi_extra=agent_tool(name="pick_take", effect=ToolEffect.SIDE_EFFECTING),
    responses={
        404: {"description": "Generation does not exist"},
        409: {"description": ARCHIVED_TAKE_DETAIL},
    },
)
def api_pick_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    return _mark_generation(gen_id, user, session, pick_generation)


_UNPICK_TAKE_DESCRIPTION = (
    "Remove the pick from one of the person's own takes. "
    "An unpicked take can be archived by cleanup and deleted later."
)


@router.post(
    "/generations/{gen_id}/unpick",
    description=_UNPICK_TAKE_DESCRIPTION,
    openapi_extra=agent_tool(name="unpick_take", effect=ToolEffect.SIDE_EFFECTING),
    responses={404: {"description": "Generation does not exist"}},
)
def api_unpick_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    return _toggle_generation(gen_id, user, session, unpick_generation)


_KEEP_TAKE_DESCRIPTION = "Protect one of the person's own takes from cleanup."


@router.post(
    "/generations/{gen_id}/keep",
    description=_KEEP_TAKE_DESCRIPTION,
    openapi_extra=agent_tool(name="keep_take", effect=ToolEffect.SIDE_EFFECTING),
    responses={
        404: {"description": "Generation does not exist"},
        409: {"description": ARCHIVED_TAKE_DETAIL},
    },
)
def api_keep_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    return _mark_generation(gen_id, user, session, keep_generation)


_UNKEEP_TAKE_DESCRIPTION = (
    "Stop protecting one of the person's own takes from cleanup. "
    "An unkept take can be archived by cleanup and deleted later."
)


@router.post(
    "/generations/{gen_id}/unkeep",
    description=_UNKEEP_TAKE_DESCRIPTION,
    openapi_extra=agent_tool(name="unkeep_take", effect=ToolEffect.SIDE_EFFECTING),
    responses={404: {"description": "Generation does not exist"}},
)
def api_unkeep_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    return _toggle_generation(gen_id, user, session, unkeep_generation)


_UNARCHIVE_TAKE_DESCRIPTION = "Take one of the person's own archived takes out of the archive."


@router.post(
    "/generations/{gen_id}/unarchive",
    description=_UNARCHIVE_TAKE_DESCRIPTION,
    openapi_extra=agent_tool(name="unarchive_take", effect=ToolEffect.SIDE_EFFECTING),
    responses={404: {"description": "Generation does not exist"}},
)
def api_unarchive_generation(
    gen_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    return _toggle_generation(gen_id, user, session, unarchive_generation)

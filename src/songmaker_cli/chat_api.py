"""Chat, capabilities, and generation defaults API endpoints."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import check_rate_limit
from songmaker_cli.api_models import (
    CapabilitiesResponse,
    ChatRequest,
    ChatResponse,
    GenerationDefaultsRequest,
)
from songmaker_cli.claude.provider import (
    UnavailableError,
    call_claude,
    is_available,
)
from songmaker_cli.config import load_generation_defaults, save_generation_defaults
from songmaker_cli.db.engine import get_db_session
from songmaker_cli.db.queries import create_job
from songmaker_cli.middleware import AuthenticatedUser, get_current_user, require_admin

log = logging.getLogger(__name__)

router = APIRouter()

_get_session = get_db_session


# ── Generation Defaults ──────────────────────────────────────────────


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


# ── Capabilities ─────────────────────────────────────────────────────


@router.get("/capabilities")
def api_capabilities(
    _user: AuthenticatedUser = Depends(get_current_user),
) -> CapabilitiesResponse:
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    return CapabilitiesResponse(
        claude_api=bool(env_key),
        claude_cli=is_available(api_key=None),
        generation=True,
        scoring=True,
    )


# ── Claude chat ──────────────────────────────────────────────────────

_CHAT_SYSTEM_PROMPT = (
    "You are a songwriting assistant. Help write, improve, and refine song lyrics. "
    "Be creative but respect the style and theme.\n\n"
    "When suggesting lyrics or song parameters, include a ```songmaker block "
    "at the end of your response with the applicable fields as JSON:\n"
    '```songmaker\n{"lyrics": "[verse]\\n...", "prompt": "style...",'
    ' "bpm": 120, "key": "Am"}\n```\n\n'
    "Only include fields you are suggesting changes for. The lyrics field should use "
    "section tags like [verse], [chorus], [bridge]. Use \\n for newlines in lyrics.\n"
    "If the user just asks a question without needing changes, skip the songmaker block."
)


@router.post("/chat")
def api_chat(
    req: ChatRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(_get_session),
) -> ChatResponse:
    check_rate_limit(session, user, "chat")
    create_job(session, "chat", user_id=user.id)
    session.commit()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    prompt = req.message
    if req.context:
        prompt = f"Song context:\n{req.context}\n\n{req.message}"

    try:
        response = call_claude(prompt, api_key=api_key, system=_CHAT_SYSTEM_PROMPT)
    except UnavailableError as e:
        log.warning("Claude chat unavailable: %s", e)
        raise HTTPException(503, "Claude is currently unavailable")

    return ChatResponse(response=response.text)

"""Chat and capabilities API endpoints."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import create_job_with_rate_limit
from songmaker_cli.api_models import (
    CapabilitiesResponse,
    ChatRequest,
    ChatResponse,
)
from songmaker_cli.app_context import get_db_session
from songmaker_cli.claude.provider import (
    CHAT_MODEL,
    UnavailableError,
    call_claude,
    is_available,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

log = logging.getLogger(__name__)

router = APIRouter()


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
        chat_model=CHAT_MODEL,
    )


# ── Claude chat ──────────────────────────────────────────────────────

DEFAULT_CHAT_STYLE = (
    "You are a songwriting assistant. Help write, improve, and refine song lyrics. "
    "Be creative but respect the style and theme."
)

# SYNC: duplicated in frontend/src/lib/api/client.ts for direct Anthropic API calls
STRUCTURAL_PROMPT = (
    "When suggesting lyrics or song parameters, include a ```songmaker block "
    "at the end of your response with the applicable fields as JSON:\n"
    '```songmaker\n{"lyrics": "[verse]\\n...", "prompt": "style...",'
    ' "bpm": 120, "key": "Am"}\n```\n\n'
    "Only include fields you are suggesting changes for. The lyrics field should use "
    "section tags like [verse], [chorus], [bridge]. Use \\n for newlines in lyrics.\n"
    "If you are suggesting changes for a song OTHER than the current song, "
    'add a "song" field with the exact song title: '
    '```songmaker\n{"song": "Song Title", "lyrics": "..."}\n```\n'
    "If the user just asks a question without needing changes, skip the songmaker block."
)


def build_system_prompt(style: str = "") -> str:
    effective_style = style.strip() or DEFAULT_CHAT_STYLE
    return f"{effective_style}\n\n{STRUCTURAL_PROMPT}"


@router.post("/chat")
def api_chat(
    req: ChatRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ChatResponse:
    create_job_with_rate_limit(session, user, "chat")
    session.commit()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    prompt = req.message
    if req.context:
        prompt = f"Song context:\n{req.context}\n\n{req.message}"

    system = build_system_prompt(req.style)

    try:
        response = call_claude(prompt, api_key=api_key, system=system)
    except UnavailableError as e:
        log.warning("Claude chat unavailable: %s", e)
        raise HTTPException(503, "Claude is currently unavailable")

    return ChatResponse(response=response.text)

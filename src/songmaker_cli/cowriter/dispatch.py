"""Route a co-writer turn to the selected provider. No silent fallback."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.orm import Session

from songmaker_cli.claude.provider import StreamEvent
from songmaker_cli.constants import (
    COWRITER_GROK_CHAT_URL,
    COWRITER_OPENAI_CHAT_URL,
    COWRITER_PROVIDERS,
)
from songmaker_cli.cowriter.claude_adapter import stream_claude_turn
from songmaker_cli.cowriter.errors import ProviderUnavailableError
from songmaker_cli.cowriter.openai_adapter import stream_openai_compatible_turn
from songmaker_cli.middleware import AuthenticatedUser
from songmaker_cli.settings import get_settings


async def stream_cowriter_turn(
    *,
    provider: str,
    model: str,
    user_id: str,
    system: str,
    messages: list[dict[str, str]],
    session: Session,
    user: AuthenticatedUser,
) -> AsyncIterator[StreamEvent]:
    if provider not in COWRITER_PROVIDERS:
        raise ProviderUnavailableError(
            provider, f"Unknown co-writer provider '{provider}'",
        )
    if not model:
        raise ProviderUnavailableError(
            provider, f"No co-writer model configured for {provider}",
        )
    if provider == "claude":
        async for event in stream_claude_turn(
            user_id=user_id, system=system, model=model, messages=messages,
        ):
            yield event
        return
    if provider == "grok":
        api_key = _require_secret("grok", get_settings().xai_api_key)
        api_url = COWRITER_GROK_CHAT_URL
    else:
        api_key = _require_secret("codex", get_settings().openai_api_key)
        api_url = COWRITER_OPENAI_CHAT_URL
    async for event in stream_openai_compatible_turn(
        provider=provider,
        api_url=api_url,
        api_key=api_key,
        model=model,
        system=system,
        messages=messages,
        session=session,
        user=user,
    ):
        yield event


def _require_secret(provider: str, secret) -> str:
    value = secret.get_secret_value() if secret is not None else ""
    if not value:
        raise ProviderUnavailableError(
            provider, f"{provider} is not configured",
        )
    return value

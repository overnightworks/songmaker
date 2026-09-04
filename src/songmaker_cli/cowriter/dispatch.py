"""Route a co-writer turn to the selected provider. No silent fallback."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.orm import Session

from songmaker_cli.agent_cli import (
    AgentCliUnavailableError,
    codex_cli_access_token_is_present,
    grok_cli_token_is_present,
)
from songmaker_cli.claude.provider import StreamEvent
from songmaker_cli.constants import (
    COWRITER_GROK_CHAT_URL,
    COWRITER_OPENAI_CHAT_URL,
    COWRITER_PROVIDERS,
)
from songmaker_cli.cowriter.catalog import (
    OPENAI_API_KEY_ENVIRONMENT,
    XAI_API_KEY_ENVIRONMENT,
    ProviderSetupMethod,
)
from songmaker_cli.cowriter.claude_adapter import call_claude_once, stream_claude_turn
from songmaker_cli.cowriter.codex_cli_adapter import stream_codex_cli_turn
from songmaker_cli.cowriter.errors import ProviderUnavailableError
from songmaker_cli.cowriter.grok_cli_adapter import stream_grok_cli_turn
from songmaker_cli.cowriter.openai_adapter import (
    call_openai_compatible_once,
    stream_openai_compatible_turn,
)
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
        stream = stream_claude_turn(
            user_id=user_id, system=system, model=model, messages=messages,
        )
        try:
            async for event in stream:
                yield event
        finally:
            await stream.aclose()
        return
    if provider == "grok":
        if _grok_cli_token_is_present():
            stream = stream_grok_cli_turn(
                system=system,
                model=model,
                messages=messages,
            )
            try:
                async for event in stream:
                    yield event
            finally:
                await stream.aclose()
            return
        api_key = _require_secret(
            "grok", get_settings().xai_api_key, XAI_API_KEY_ENVIRONMENT,
        )
        api_url = COWRITER_GROK_CHAT_URL
    if provider == "codex" and _codex_cli_access_token_is_present():
        stream = stream_codex_cli_turn(
            system=system,
            model=model,
            messages=messages,
        )
        try:
            async for event in stream:
                yield event
        finally:
            await stream.aclose()
        return
    if provider == "codex":
        api_key = _require_secret(
            "codex", get_settings().openai_api_key, OPENAI_API_KEY_ENVIRONMENT,
        )
        api_url = COWRITER_OPENAI_CHAT_URL
    stream = stream_openai_compatible_turn(
        provider=provider,
        api_url=api_url,
        api_key=api_key,
        model=model,
        system=system,
        messages=messages,
        session=session,
        user=user,
    )
    try:
        async for event in stream:
            yield event
    finally:
        await stream.aclose()


def call_provider_once(
    *, provider: str, model: str, prompt: str, timeout: int, system: str | None = None,
) -> str:
    """One-shot completion from the selected provider — no tools, no session,
    no chat history.

    Used by the lyrical-coherence judge (#315), which needs a single verdict
    rather than the co-writer's multi-turn tool-using chat that
    ``stream_cowriter_turn`` gives, and runs under its own (much shorter)
    time budget rather than the co-writer's session timeout.
    """
    if provider not in COWRITER_PROVIDERS:
        raise ProviderUnavailableError(
            provider, f"Unknown provider '{provider}'",
        )
    if not model:
        raise ProviderUnavailableError(
            provider, f"No model configured for {provider}",
        )
    if provider == "claude":
        return call_claude_once(
            model=model,
            prompt=prompt,
            timeout=timeout,
            system=system,
        )
    if provider == "grok":
        api_key = _require_secret(
            "grok", get_settings().xai_api_key, XAI_API_KEY_ENVIRONMENT,
        )
        api_url = COWRITER_GROK_CHAT_URL
    else:
        api_key = _require_secret(
            "codex", get_settings().openai_api_key, OPENAI_API_KEY_ENVIRONMENT,
        )
        api_url = COWRITER_OPENAI_CHAT_URL
    return call_openai_compatible_once(
        provider=provider, api_url=api_url, api_key=api_key, model=model,
        prompt=prompt, timeout=timeout, system=system,
    )


def _require_secret(provider: str, secret, environment_key: str) -> str:
    value = secret.get_secret_value() if secret is not None else ""
    if not value:
        raise ProviderUnavailableError(
            provider, f"{provider} turns go over the {provider} API and need {environment_key}",
        )
    return value


def _grok_cli_token_is_present() -> bool:
    try:
        return grok_cli_token_is_present()
    except AgentCliUnavailableError as exc:
        raise ProviderUnavailableError("grok", "grok_cli_error") from exc


def _codex_cli_access_token_is_present() -> bool:
    try:
        return codex_cli_access_token_is_present()
    except AgentCliUnavailableError as exc:
        raise ProviderUnavailableError("codex", "codex_cli_error") from exc


def cover_image_provider_method() -> ProviderSetupMethod | None:
    """Choose the one configured route for a generated cover image.

    Cover generation intentionally has no HTTP/API fallback.  The image
    adapter receives only this selected method and never reads credentials.
    """
    if _codex_cli_access_token_is_present():
        return ProviderSetupMethod.CODEX_CLI
    return None

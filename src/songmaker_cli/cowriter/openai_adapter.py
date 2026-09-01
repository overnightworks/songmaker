"""OpenAI-compatible HTTP adapter used by Grok and Codex."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx
from sqlalchemy.orm import Session

from songmaker_cli.claude.provider import (
    AssistantTextEvent,
    FinalEvent,
    StreamEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from songmaker_cli.constants import COWRITER_CLI_TIMEOUT_SECONDS, COWRITER_MAX_TOOL_ROUNDS
from songmaker_cli.cowriter.errors import ProviderUnavailableError
from songmaker_cli.middleware import AuthenticatedUser


async def stream_openai_compatible_turn(
    *,
    provider: str,
    api_url: str,
    api_key: str,
    model: str,
    system: str,
    messages: list[dict[str, str]],
    session: Session,
    user: AuthenticatedUser,
) -> AsyncIterator[StreamEvent]:
    # Imported lazily: the songmaker tool catalog pulls in the MCP server
    # package, which only the tool-using co-writer chat needs. The judge's
    # tool-free ``call_openai_compatible_once`` below must stay importable
    # without the ``mcp`` extra installed (#315).
    from songmaker_cli.cowriter.tools import execute_cowriter_tool, openai_tool_schemas

    oai_messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    oai_messages.extend(messages)
    text_chunks: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=COWRITER_CLI_TIMEOUT_SECONDS) as client:
            for round_index in range(COWRITER_MAX_TOOL_ROUNDS + 1):
                payload = await _post_chat(
                    client, provider, api_url, api_key, model, oai_messages,
                    openai_tool_schemas(),
                )
                message = _assistant_message(payload, provider)
                tool_calls = message.get("tool_calls") or []
                if not isinstance(tool_calls, list):
                    raise ProviderUnavailableError(
                        provider, f"{provider} returned an invalid response",
                    )
                if tool_calls and round_index == COWRITER_MAX_TOOL_ROUNDS:
                    raise ProviderUnavailableError(
                        provider, f"{provider} exceeded the tool-call limit",
                    )
                content = message.get("content") or ""
                if not isinstance(content, str):
                    raise ProviderUnavailableError(
                        provider, f"{provider} returned an invalid response",
                    )
                if content:
                    text_chunks.append(content)
                    yield AssistantTextEvent(text=content)
                if not tool_calls:
                    yield FinalEvent(text="".join(text_chunks).strip())
                    return
                oai_messages.append({
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": tool_calls,
                })
                for call in tool_calls:
                    call_id, name, arguments = _parse_tool_call(call, provider)
                    yield ToolCallEvent(tool_use_id=call_id, name=name, input=arguments)
                    result, is_error = execute_cowriter_tool(
                        session, user, name, arguments,
                    )
                    yield ToolResultEvent(
                        tool_use_id=call_id, content=result, is_error=is_error,
                    )
                    oai_messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": result,
                    })
    except ProviderUnavailableError:
        raise
    except httpx.HTTPError as exc:
        raise ProviderUnavailableError(
            provider, f"{provider} is currently unavailable",
        ) from exc
    raise AssertionError("unreachable")


async def _post_chat(
    client: httpx.AsyncClient,
    provider: str,
    api_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    tool_schemas: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        response = await client.post(
            api_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "tools": tool_schemas,
            },
        )
    except httpx.HTTPError as exc:
        raise ProviderUnavailableError(
            provider, f"{provider} is currently unavailable",
        ) from exc
    if response.status_code >= 400:
        raise ProviderUnavailableError(
            provider, f"{provider} is currently unavailable",
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderUnavailableError(
            provider, f"{provider} is currently unavailable",
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderUnavailableError(
            provider, f"{provider} is currently unavailable",
        )
    return payload


def _assistant_message(
    payload: Mapping[str, object], provider: str,
) -> dict[str, object]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderUnavailableError(
            provider, f"{provider} is currently unavailable",
        )
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise ProviderUnavailableError(
            provider, f"{provider} is currently unavailable",
        )
    return message


def call_openai_compatible_once(
    *,
    provider: str,
    api_url: str,
    api_key: str,
    model: str,
    prompt: str,
    timeout: int,
    system: str | None = None,
) -> str:
    """Synchronous, tool-free, single-turn completion.

    Used by the lyrical-coherence judge (#315), which needs one verdict, not
    the tool-using multi-round chat ``stream_openai_compatible_turn`` gives
    the co-writer — so it runs under the judge's own budget, not the
    co-writer's much longer session timeout.
    """
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        response = httpx.post(
            api_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "messages": messages},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise ProviderUnavailableError(
            provider, f"{provider} is currently unavailable",
        ) from exc
    if response.status_code >= 400:
        raise ProviderUnavailableError(
            provider, f"{provider} is currently unavailable",
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderUnavailableError(
            provider, f"{provider} is currently unavailable",
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderUnavailableError(
            provider, f"{provider} is currently unavailable",
        )
    message = _assistant_message(payload, provider)
    content = message.get("content")
    if not isinstance(content, str) or not content:
        raise ProviderUnavailableError(
            provider, f"{provider} returned an invalid response",
        )
    return content


def _parse_tool_call(call: object, provider: str) -> tuple[str, str, dict[str, Any]]:
    if not isinstance(call, dict):
        raise ProviderUnavailableError(
            provider, f"{provider} is currently unavailable",
        )
    function = call.get("function") if isinstance(call.get("function"), dict) else None
    if function is None:
        raise ProviderUnavailableError(
            provider, f"{provider} returned an invalid tool call",
        )
    call_id = call.get("id")
    name = function.get("name")
    if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
        raise ProviderUnavailableError(
            provider, f"{provider} returned an invalid tool call",
        )
    raw_args = function.get("arguments") or "{}"
    if isinstance(raw_args, str):
        try:
            arguments = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            raise ProviderUnavailableError(
                provider, f"{provider} returned invalid tool arguments",
            ) from exc
    elif isinstance(raw_args, dict):
        arguments = raw_args
    else:
        raise ProviderUnavailableError(
            provider, f"{provider} returned invalid tool arguments",
        )
    if not isinstance(arguments, dict):
        raise ProviderUnavailableError(
            provider, f"{provider} returned invalid tool arguments",
        )
    return call_id, name, arguments

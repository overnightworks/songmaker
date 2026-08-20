"""OpenAI-compatible HTTP adapter used by Grok and Codex."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
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
from songmaker_cli.cowriter.tools import execute_cowriter_tool, openai_tool_schemas
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
    oai_messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    oai_messages.extend(messages)
    text_chunks: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=COWRITER_CLI_TIMEOUT_SECONDS) as client:
            for _round in range(COWRITER_MAX_TOOL_ROUNDS):
                payload = await _post_chat(
                    client, provider, api_url, api_key, model, oai_messages,
                )
                message = _assistant_message(payload, provider)
                tool_calls = message.get("tool_calls") or []
                content = message.get("content") or ""
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
    raise ProviderUnavailableError(
        provider, f"{provider} exceeded the tool-call limit",
    )


async def _post_chat(
    client: httpx.AsyncClient,
    provider: str,
    api_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
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
                "tools": openai_tool_schemas(),
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
    payload = response.json()
    if not isinstance(payload, dict):
        raise ProviderUnavailableError(
            provider, f"{provider} is currently unavailable",
        )
    return payload


def _assistant_message(payload: dict[str, Any], provider: str) -> dict[str, Any]:
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


def _parse_tool_call(call: object, provider: str) -> tuple[str, str, dict[str, Any]]:
    if not isinstance(call, dict):
        raise ProviderUnavailableError(
            provider, f"{provider} is currently unavailable",
        )
    function = call.get("function") if isinstance(call.get("function"), dict) else {}
    raw_args = function.get("arguments") or "{}"
    if isinstance(raw_args, str):
        try:
            arguments = json.loads(raw_args)
        except json.JSONDecodeError:
            arguments = {}
    elif isinstance(raw_args, dict):
        arguments = raw_args
    else:
        arguments = {}
    return (
        str(call.get("id") or ""),
        str(function.get("name") or ""),
        arguments if isinstance(arguments, dict) else {},
    )

"""OpenAI-compatible HTTP adapter used by Grok and Codex."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx
from sqlalchemy.orm import Session

from songmaker_cli.claude.provider import StreamEvent
from songmaker_cli.constants import COWRITER_CLI_TIMEOUT_SECONDS
from songmaker_cli.cowriter.errors import (
    ProviderUnavailableError,
    SafeRouteReasonCode,
    normalize_route_failure,
)
from songmaker_cli.cowriter.tool_loop import (
    FinalText,
    InitialTurn,
    TextDelta,
    ToolCall,
    ToolCallBatch,
    ToolLoopLimitError,
    ToolLoopProtocolError,
    ToolResultBatch,
    TransportResponse,
    stream_tool_loop,
)
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

    try:
        async with httpx.AsyncClient(timeout=COWRITER_CLI_TIMEOUT_SECONDS) as client:
            transport = _OpenAITransport(
                client=client,
                provider=provider,
                api_url=api_url,
                api_key=api_key,
                model=model,
                tool_schemas=openai_tool_schemas(),
            )
            async for event in stream_tool_loop(
                provider=provider,
                route="api",
                system=system,
                messages=messages,
                transport=transport,
                executor=lambda name, arguments: execute_cowriter_tool(
                    session, user, name, arguments,
                ),
            ):
                yield event
    except ToolLoopLimitError as exc:
        raise ProviderUnavailableError(
            provider,
            "api",
            normalize_route_failure(SafeRouteReasonCode.TOOL_LIMIT_EXCEEDED),
        ) from exc
    except ToolLoopProtocolError as exc:
        raise ProviderUnavailableError(
            provider,
            "api",
            normalize_route_failure(SafeRouteReasonCode.API_PROTOCOL_ERROR),
        ) from exc
    except ProviderUnavailableError:
        raise
    except httpx.HTTPError as exc:
        raise ProviderUnavailableError(
            provider,
            "api",
            normalize_route_failure(SafeRouteReasonCode.API_HTTP_ERROR),
        ) from exc
    except Exception as exc:
        raise ProviderUnavailableError(
            provider,
            "api",
            normalize_route_failure(SafeRouteReasonCode.TOOL_EXECUTION_FAILED),
        ) from exc


class _OpenAITransport:
    """OpenAI chat-completions wire format behind the shared loop contract."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        provider: str,
        api_url: str,
        api_key: str,
        model: str,
        tool_schemas: list[dict[str, Any]],
    ) -> None:
        self._client = client
        self._provider = provider
        self._api_url = api_url
        self._api_key = api_key
        self._model = model
        self._tool_schemas = tool_schemas
        self._messages: list[dict[str, Any]] | None = None
        self._assistant_message: dict[str, object] | None = None

    async def aclose(self) -> None:
        """The enclosing HTTP client context owns connection cleanup."""

    async def stream(
        self, message: InitialTurn | ToolResultBatch,
    ) -> AsyncIterator[TransportResponse]:
        self._append_message(message)
        payload = await _post_chat(
            self._client,
            self._provider,
            self._api_url,
            self._api_key,
            self._model,
            self._messages,
            self._tool_schemas,
        )
        assistant_message = _assistant_message(payload, self._provider)
        tool_calls = assistant_message.get("tool_calls") or []
        if not isinstance(tool_calls, list):
            raise ProviderUnavailableError(
                self._provider,
                "api",
                normalize_route_failure(SafeRouteReasonCode.API_PROTOCOL_ERROR),
            )
        content = assistant_message.get("content") or ""
        if not isinstance(content, str):
            raise ProviderUnavailableError(
                self._provider,
                "api",
                normalize_route_failure(SafeRouteReasonCode.API_PROTOCOL_ERROR),
            )
        if content:
            yield TextDelta(content)
        if not tool_calls:
            yield FinalText()
            return
        self._assistant_message = {
            "role": "assistant",
            "content": content or None,
            "tool_calls": tool_calls,
        }
        yield ToolCallBatch(tuple(
            ToolCall(call_id, name, arguments)
            for call_id, name, arguments in (
                _parse_tool_call(call, self._provider) for call in tool_calls
            )
        ))

    def _append_message(self, message: InitialTurn | ToolResultBatch) -> None:
        if isinstance(message, InitialTurn):
            if self._messages is not None:
                raise ToolLoopProtocolError()
            self._messages = [{"role": "system", "content": message.system}, *message.messages]
            return
        if self._messages is None or self._assistant_message is None:
            raise ToolLoopProtocolError()
        self._messages.append(self._assistant_message)
        self._messages.extend({
            "role": "tool",
            "tool_call_id": result.tool_use_id,
            "content": result.content,
        } for result in message.results)
        self._assistant_message = None


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
            provider,
            "api",
            normalize_route_failure(SafeRouteReasonCode.API_HTTP_ERROR),
        ) from exc
    return _response_payload(response, provider)


def _response_payload(response: httpx.Response, provider: str) -> dict[str, Any]:
    if response.status_code >= 400:
        raise ProviderUnavailableError(
            provider,
            "api",
            normalize_route_failure(SafeRouteReasonCode.API_HTTP_ERROR),
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderUnavailableError(
            provider,
            "api",
            normalize_route_failure(SafeRouteReasonCode.API_PROTOCOL_ERROR),
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderUnavailableError(
            provider,
            "api",
            normalize_route_failure(SafeRouteReasonCode.API_PROTOCOL_ERROR),
        )
    return payload


def _assistant_message(
    payload: Mapping[str, object], provider: str,
) -> dict[str, object]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderUnavailableError(
            provider,
            "api",
            normalize_route_failure(SafeRouteReasonCode.API_PROTOCOL_ERROR),
        )
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise ProviderUnavailableError(
            provider,
            "api",
            normalize_route_failure(SafeRouteReasonCode.API_PROTOCOL_ERROR),
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
            provider,
            "api",
            normalize_route_failure(SafeRouteReasonCode.API_HTTP_ERROR),
        ) from exc
    payload = _response_payload(response, provider)
    message = _assistant_message(payload, provider)
    content = message.get("content")
    if not isinstance(content, str) or not content:
        raise ProviderUnavailableError(
            provider,
            "api",
            normalize_route_failure(SafeRouteReasonCode.API_PROTOCOL_ERROR),
        )
    return content


def _parse_tool_call(call: object, provider: str) -> tuple[str, str, dict[str, Any]]:
    if not isinstance(call, dict):
        raise ProviderUnavailableError(
            provider,
            "api",
            normalize_route_failure(SafeRouteReasonCode.TOOL_PROTOCOL_ERROR),
        )
    function = call.get("function") if isinstance(call.get("function"), dict) else None
    if function is None:
        raise ProviderUnavailableError(
            provider,
            "api",
            normalize_route_failure(SafeRouteReasonCode.TOOL_PROTOCOL_ERROR),
        )
    call_id = call.get("id")
    name = function.get("name")
    if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
        raise ProviderUnavailableError(
            provider,
            "api",
            normalize_route_failure(SafeRouteReasonCode.TOOL_PROTOCOL_ERROR),
        )
    raw_args = function.get("arguments") or "{}"
    if isinstance(raw_args, str):
        try:
            arguments = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            raise ProviderUnavailableError(
                provider,
                "api",
                normalize_route_failure(SafeRouteReasonCode.TOOL_PROTOCOL_ERROR),
            ) from exc
    elif isinstance(raw_args, dict):
        arguments = raw_args
    else:
        raise ProviderUnavailableError(
            provider,
            "api",
            normalize_route_failure(SafeRouteReasonCode.TOOL_PROTOCOL_ERROR),
        )
    if not isinstance(arguments, dict):
        raise ProviderUnavailableError(
            provider,
            "api",
            normalize_route_failure(SafeRouteReasonCode.TOOL_PROTOCOL_ERROR),
        )
    return call_id, name, arguments

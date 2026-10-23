"""Canonical songmaker tool catalog for every co-writer provider.

Claude reaches these functions through the MCP server and the agent
service through ``/mcp``. Grok and Codex call ``execute_cowriter_tool``
in-process. Query logic and ownership checks stay in ``mcp_server.tools``.

``execute_cowriter_tool``'s ``arguments: dict[str, Any]`` is exempt from
``scripts/check_no_silent_fallbacks.py``'s dict-any-in-signature rule:
the tools below share no single argument shape, only their own JSON
Schema in ``CowriterTool.parameters``. Collapsing that into named
per-tool argument models is tracked as a follow-up — see #332, finding F15.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from agent_providers.tool_loop import ToolOutcome
from agent_providers.tools import ToolCatalog, ToolDeclaration
from pydantic import BaseModel
from sqlalchemy.orm import Session
from webauth.ports import AuthenticatedUser

from songmaker_cli.constants import GET_SONG_TOOL_DESCRIPTION
from songmaker_cli.mcp_server.tools import (
    MCPToolError,
    tool_create_song,
    tool_get_generation,
    tool_get_song,
    tool_get_version,
    tool_list_albums,
    tool_list_songs,
    tool_rename_song,
    tool_search_songs,
    tool_suggest_album_cover,
    tool_update_song_lyrics,
    tool_update_song_prompt,
    tool_update_song_style,
)

_STRING = {"type": "string"}
_INT = {"type": "integer"}

_JSON_TYPE_CHECKS: Mapping[str, Callable[[object], bool]] = {
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
}
_OBJECT_KEYWORDS = frozenset({"type", "properties", "additionalProperties", "required"})


@dataclass(frozen=True)
class CowriterTool:
    name: str
    description: str
    parameters: dict[str, Any]
    write: bool
    handler: Callable[..., Any]

    def __post_init__(self) -> None:
        require_supported_declaration(self.parameters)


def _object(
    properties: Mapping[str, object], required: list[str] | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": dict(properties),
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def require_supported_declaration(parameters: Mapping[str, Any]) -> None:
    """Refuse a declaration beyond the subset ``_object`` emits and the validator reads."""
    unsupported = parameters.keys() - _OBJECT_KEYWORDS
    properties = parameters.get("properties", {})
    if (
        unsupported
        or parameters.get("type") != "object"
        or parameters.get("additionalProperties") is not False
        or any(
            len(schema) != 1 or schema.get("type") not in _JSON_TYPE_CHECKS
            for schema in properties.values()
        )
        or not set(parameters.get("required", ())) <= properties.keys()
    ):
        raise ValueError(f"unsupported tool declaration: {sorted(unsupported)}")


COWRITER_TOOLS: tuple[CowriterTool, ...] = (
    CowriterTool(
        "list_albums",
        "List all albums owned by the current user.",
        _object({}),
        False,
        tool_list_albums,
    ),
    CowriterTool(
        "list_songs",
        "List songs. Without album_id, every owned song; with album_id, that album.",
        _object({"album_id": _STRING}),
        False,
        tool_list_songs,
    ),
    CowriterTool(
        "search_songs",
        "Search songs by title substring. Limit defaults to 20, max 50.",
        _object({"query": _STRING, "limit": _INT}, ["query"]),
        False,
        tool_search_songs,
    ),
    CowriterTool(
        "get_song",
        GET_SONG_TOOL_DESCRIPTION,
        _object({"song_id": _STRING}, ["song_id"]),
        False,
        tool_get_song,
    ),
    CowriterTool(
        "get_version",
        "Read a specific version snapshot of a song.",
        _object({"song_id": _STRING, "version_id": _STRING}, ["song_id", "version_id"]),
        False,
        tool_get_version,
    ),
    CowriterTool(
        "get_generation",
        "Read a generation's metadata, scores, whisper transcript, and rating.",
        _object({"generation_id": _STRING}, ["generation_id"]),
        False,
        tool_get_generation,
    ),
    CowriterTool(
        "create_song",
        "Create a new song in an album.",
        _object(
            {
                "album_id": _STRING,
                "title": _STRING,
                "lyrics": _STRING,
                "prompt": _STRING,
            },
            ["album_id", "title"],
        ),
        True,
        tool_create_song,
    ),
    CowriterTool(
        "update_song_lyrics",
        "Replace the song's current lyrics.",
        _object({"song_id": _STRING, "lyrics": _STRING}, ["song_id", "lyrics"]),
        True,
        tool_update_song_lyrics,
    ),
    CowriterTool(
        "update_song_prompt",
        "Replace the song's current style prompt.",
        _object({"song_id": _STRING, "prompt": _STRING}, ["song_id", "prompt"]),
        True,
        tool_update_song_prompt,
    ),
    CowriterTool(
        "update_song_style",
        "Update bpm, key_scale, and/or audio_duration.",
        _object({
            "song_id": _STRING,
            "bpm": _INT,
            "key_scale": _STRING,
            "audio_duration": _INT,
        }, ["song_id"]),
        True,
        tool_update_song_style,
    ),
    CowriterTool(
        "rename_song",
        "Rename a song's title.",
        _object({"song_id": _STRING, "title": _STRING}, ["song_id", "title"]),
        True,
        tool_rename_song,
    ),
    CowriterTool(
        "suggest_album_cover",
        (
            "Request one more album cover suggestion; earlier suggestions stay "
            "pending. Returns the queued job ID and status."
        ),
        _object({"album_id": _STRING}, ["album_id"]),
        True,
        tool_suggest_album_cover,
    ),
)

_TOOLS_BY_NAME = {tool.name: tool for tool in COWRITER_TOOLS}

COWRITER_TOOL_CATALOG: ToolCatalog = ToolCatalog(
    tools=tuple(
        ToolDeclaration(
            name=tool.name,
            description=tool.description,
            parameters=tool.parameters,
        )
        for tool in COWRITER_TOOLS
    ),
)
"""The same catalog the provider layer renders, parses and validates against."""


def _serialize(result: Any) -> str:
    if isinstance(result, list):
        return json.dumps(
            [
                item.model_dump(mode="json") if isinstance(item, BaseModel) else item
                for item in result
            ],
            default=str,
        )
    if isinstance(result, BaseModel):
        return json.dumps(result.model_dump(mode="json"), default=str)
    return json.dumps(result, default=str)


def _refusal_of(tool: CowriterTool, arguments: Mapping[str, Any]) -> str | None:
    """The first way ``arguments`` break the tool's declaration, naming the field."""
    properties = tool.parameters["properties"]
    for key in arguments:
        if key not in properties:
            return f"Unknown argument: {key}"
    for key in tool.parameters.get("required", ()):
        if key not in arguments:
            return f"Missing required argument: {key}"
    for key, value in arguments.items():
        expected = properties[key]["type"]
        if not _JSON_TYPE_CHECKS[expected](value):
            return f"Argument {key} must be of type {expected}"
    return None


def execute_cowriter_tool(
    session: Session,
    user: AuthenticatedUser,
    name: str,
    arguments: dict[str, Any],
) -> ToolOutcome:
    tool = _TOOLS_BY_NAME.get(name)
    if tool is None:
        return ToolOutcome(f"Unknown tool: {name}", True)
    refusal = _refusal_of(tool, arguments)
    if refusal is not None:
        return ToolOutcome(refusal, True)
    try:
        result = tool.handler(session, user, **arguments)
        if tool.write:
            session.commit()
        return ToolOutcome(_serialize(result), False)
    except MCPToolError as exc:
        session.rollback()
        return ToolOutcome(str(exc), True)
    except TypeError as exc:
        session.rollback()
        return ToolOutcome(str(exc), True)
    except Exception:
        session.rollback()
        raise

"""Canonical songmaker tool catalog for every co-writer provider.

Claude reaches these functions through the MCP server. Grok and Codex
call ``execute_cowriter_tool`` in-process. Query logic and ownership
checks stay in ``mcp_server.tools``.

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

from pydantic import BaseModel
from sqlalchemy.orm import Session

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
from songmaker_cli.middleware import AuthenticatedUser

_STRING = {"type": "string"}
_INT = {"type": "integer"}


@dataclass(frozen=True)
class CowriterTool:
    name: str
    description: str
    parameters: dict[str, Any]
    write: bool
    handler: Callable[..., Any]


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
        "Read the full state of a song.",
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
        "Request three album cover suggestions. Returns the queued job ID and status.",
        _object({"album_id": _STRING}, ["album_id"]),
        True,
        tool_suggest_album_cover,
    ),
)

_TOOLS_BY_NAME = {tool.name: tool for tool in COWRITER_TOOLS}


def openai_tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in COWRITER_TOOLS
    ]


def anthropic_tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.parameters,
        }
        for tool in COWRITER_TOOLS
    ]


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


def execute_cowriter_tool(
    session: Session,
    user: AuthenticatedUser,
    name: str,
    arguments: dict[str, Any],
) -> tuple[str, bool]:
    tool = _TOOLS_BY_NAME.get(name)
    if tool is None:
        return f"Unknown tool: {name}", True
    allowed = set(tool.parameters.get("properties", {}))
    filtered = {key: value for key, value in arguments.items() if key in allowed}
    try:
        result = tool.handler(session, user, **filtered)
        if tool.write:
            session.commit()
        return _serialize(result), False
    except MCPToolError as exc:
        session.rollback()
        return str(exc), True
    except TypeError as exc:
        session.rollback()
        return str(exc), True
    except Exception:
        session.rollback()
        raise

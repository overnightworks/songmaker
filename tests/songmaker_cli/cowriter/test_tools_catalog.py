"""Songmaker's co-writer tools: the catalog, its declarations and its argument checks."""

from __future__ import annotations

import pytest

from songmaker_cli.cowriter.mcp_spec import MCP_TOOL_NAMES
from songmaker_cli.cowriter.tools import (
    COWRITER_TOOLS,
    CowriterTool,
    execute_cowriter_tool,
)


def test_the_co_writer_tools_are_the_mcp_server_tools_plus_the_coherence_verdict():
    assert {tool.name for tool in COWRITER_TOOLS} == MCP_TOOL_NAMES | {"save_coherence_verdict"}


def test_executing_an_unknown_tool_is_a_refused_outcome_not_a_crash():
    outcome = execute_cowriter_tool(None, None, "delete_everything", {})

    assert outcome.is_error is True
    assert outcome.content == "Unknown tool: delete_everything"


@pytest.mark.parametrize(
    ("tool_name", "arguments", "named_field"),
    [
        ("update_song_lyrics", {"song_id": "s1", "lyrics": None}, "lyrics"),
        ("update_song_style", {"song_id": "s1", "bpm": "120"}, "bpm"),
        ("update_song_style", {"song_id": "s1", "bpm": True}, "bpm"),
        ("update_song_style", {"song_id": "s1", "bpm": 120.0}, "bpm"),
        ("update_song_lyrics", {"lyrics": "la"}, "song_id"),
        ("get_song", {"song_id": "s1", "extra": 1}, "extra"),
        ("list_albums", {"album_id": "a1"}, "album_id"),
        ("search_songs", {"query": 7}, "query"),
        ("save_coherence_verdict", {"generation_id": "g", "score": "8", "summary": "s"}, "score"),
        ("save_coherence_verdict", {"generation_id": "g", "score": 8.0, "summary": "s"}, "score"),
        ("save_coherence_verdict", {"generation_id": "g", "score": True, "summary": "s"}, "score"),
        ("save_coherence_verdict", {"generation_id": "g", "score": 8, "summary": 5}, "summary"),
        ("save_coherence_verdict", {"generation_id": "g", "summary": "s"}, "score"),
        (
            "save_coherence_verdict",
            {"generation_id": "g", "score": 8, "summary": "s", "extra": 1},
            "extra",
        ),
    ],
)
def test_arguments_that_break_the_declaration_are_refused_naming_the_field_before_any_handler_runs(
    tool_name, arguments, named_field,
):
    # No session: a handler that ran would crash, and a commit would too.
    outcome = execute_cowriter_tool(None, None, tool_name, arguments)

    assert outcome.is_error is True
    assert named_field in outcome.content


@pytest.mark.parametrize(
    "parameters",
    [
        {"type": "object", "properties": {"a": {"type": "number"}}, "additionalProperties": False},
        {"type": "object", "properties": {"a": {"type": "string", "enum": ["x"]}},
         "additionalProperties": False},
        {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False,
         "oneOf": []},
        {"type": "object", "properties": {"a": {"type": "string"}}},
        {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False,
         "required": ["b"]},
    ],
)
def test_a_declaration_beyond_the_supported_subset_is_refused_at_definition(parameters):
    with pytest.raises(ValueError):
        CowriterTool("bad_tool", "A tool.", parameters, False, execute_cowriter_tool)

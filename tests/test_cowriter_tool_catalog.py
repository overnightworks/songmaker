"""Songmaker's tool catalog is the port the provider layer renders and validates.

The prompt text below is a wire contract with every subscription-CLI model:
it is pinned byte for byte against the file the pre-library rendering wrote,
so moving the protocol into ``agent_providers`` cannot silently reword what a
model is told about songmaker's tools.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_providers.text_tool_protocol import render_tool_catalog

from songmaker_cli.cowriter.mcp_spec import MCP_TOOL_NAMES
from songmaker_cli.cowriter.tools import (
    COWRITER_TOOL_CATALOG,
    COWRITER_TOOLS,
    CowriterTool,
    execute_cowriter_tool,
)

SHIPPED_PROMPT = (
    Path(__file__).with_name("fixtures") / "cowriter_tool_catalog_prompt.txt"
).read_text(encoding="utf-8")


def test_the_rendered_catalog_is_byte_for_byte_the_prompt_that_shipped():
    assert render_tool_catalog(COWRITER_TOOL_CATALOG) == SHIPPED_PROMPT


def test_rendering_the_same_catalog_twice_produces_the_same_prompt():
    assert render_tool_catalog(COWRITER_TOOL_CATALOG) == render_tool_catalog(
        COWRITER_TOOL_CATALOG,
    )


def test_the_catalog_declares_every_canonical_tool_in_its_canonical_order():
    assert [tool.name for tool in COWRITER_TOOL_CATALOG.tools] == [
        tool.name for tool in COWRITER_TOOLS
    ]
    assert [tool.parameters for tool in COWRITER_TOOL_CATALOG.tools] == [
        tool.parameters for tool in COWRITER_TOOLS
    ]


def test_the_catalog_wears_the_songmaker_markers():
    assert COWRITER_TOOL_CATALOG.markup.call_open_tag == "<songmaker_tool_call>"


def test_the_co_writer_tools_are_exactly_the_mcp_server_tools():
    assert {tool.name for tool in COWRITER_TOOLS} == MCP_TOOL_NAMES


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

"""The subscription-CLI text tool wire contract is deliberately strict."""

from __future__ import annotations

import logging

import pytest
from provider_test_support import COWRITER_TOOL_CATALOG

from agent_providers.text_tool_protocol import (
    FinalText,
    TextToolCall,
    TextToolProtocolError,
    TextToolStreamParser,
    parse_text_tool_response,
    render_tool_catalog,
    render_tool_result,
)
from agent_providers.tools import ToolCatalog, ToolDeclaration, ToolProtocolMarkup


def _call(payload: str) -> str:
    return f"<songmaker_tool_call>\n{payload}\n</songmaker_tool_call>"


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            _call('{"name":"get_song","arguments":{"song_id":"song-1"}}'),
            TextToolCall("get_song", {"song_id": "song-1"}),
        ),
        (
            " \t\r\n<songmaker_tool_call>\r\n"
            '{"name":"list_songs","arguments":{}}\r\n'
            "</songmaker_tool_call>\n ",
            TextToolCall("list_songs", {}),
        ),
    ],
)
def test_parses_a_leading_call_with_allowed_newlines_and_outer_whitespace(response, expected):
    assert parse_text_tool_response(COWRITER_TOOL_CATALOG, response) == expected


@pytest.mark.parametrize(
    ("chunks", "expected"),
    [
        (
            [
                " \n<songmaker_to",
                "ol_call>\n{\"name\":\"get_song\",",
                "\"arguments\":{\"song_id\":\"song-1\"}}\n</songmaker_tool_call>",
            ],
            TextToolCall("get_song", {"song_id": "song-1"}),
        ),
        (
            [
                "<songmaker_tool_call>\r",
                "\n{\"name\":\"list_songs\",\"arguments\":{}}\r\n",
                "</songmaker_tool_call>",
            ],
            TextToolCall("list_songs", {}),
        ),
    ],
)
def test_stream_parser_buffers_a_call_split_across_text_events(chunks, expected):
    parser = TextToolStreamParser(COWRITER_TOOL_CATALOG)

    emitted = [parser.feed(chunk) for chunk in chunks]

    assert emitted == [""] * len(chunks)
    assert parser.finish() == expected


def test_stream_parser_executes_a_line_delimited_call_after_streamed_prose():
    parser = TextToolStreamParser(COWRITER_TOOL_CATALOG)

    assert parser.feed("I'll look that up.\n<songmaker_to") == "I'll look that up.\n"
    assert parser.feed("ol_call>\n{\"name\":\"get_song\",") == ""
    assert parser.feed("\"arguments\":{\"song_id\":\"song-1\"}}\n</songmaker_tool_call>") == ""

    assert parser.finish() == TextToolCall("get_song", {"song_id": "song-1"})


def test_stream_parser_leaves_a_fenced_line_delimited_call_as_assistant_text():
    parser = TextToolStreamParser(COWRITER_TOOL_CATALOG)
    chunks = [
        "```json\n<songmaker_tool",
        '_call>\n{"name":"get_song","arguments":{"song_id":"song-1"}}\n',
        "</songmaker_tool_call>\n```",
    ]

    assert [parser.feed(chunk) for chunk in chunks] == chunks
    assert parser.finish() == FinalText("")


def test_stream_parser_executes_an_unfenced_call_after_a_fenced_example():
    parser = TextToolStreamParser(COWRITER_TOOL_CATALOG)
    example = "```json\n" + _call('{"name":"list_songs","arguments":{}}') + "\n```\n"

    assert parser.feed(example + "<songmaker_tool") == example
    assert parser.feed(
        '_call>\n{"name":"get_song","arguments":{"song_id":"song-1"}}\n'
        "</songmaker_tool_call>"
    ) == ""
    assert parser.finish() == TextToolCall("get_song", {"song_id": "song-1"})


@pytest.mark.parametrize(
    "response",
    [
        "An answer with <songmaker_tool_call> in running text.",
        "```json\n" + _call('{"name":"get_song","arguments":{"song_id":"song-1"}}') + "\n```",
    ],
)
def test_nonleading_or_fenced_call_syntax_is_ordinary_final_text(response):
    assert parse_text_tool_response(COWRITER_TOOL_CATALOG, response) == FinalText(response)


def test_stream_parser_forwards_ordinary_text_and_keeps_only_whitespace_until_finish():
    parser = TextToolStreamParser(COWRITER_TOOL_CATALOG)

    assert parser.feed("hello ") == "hello "
    assert parser.feed("world") == "world"
    assert parser.finish() == FinalText("")

    whitespace_parser = TextToolStreamParser(COWRITER_TOOL_CATALOG)

    assert whitespace_parser.feed(" \t\n") == ""
    assert whitespace_parser.finish() == FinalText(" \t\n")


@pytest.mark.parametrize(
    "response",
    [
        _call('{"name":"list_songs","arguments":{}}</songmaker_tool_call>\n'
              '<songmaker_tool_call>\n{"name":"list_songs","arguments":{}}'),
        "<songmaker_tool_call>\nHere is the call: "
        '{"name":"list_songs","arguments":{}}\n</songmaker_tool_call>',
        "<songmaker_tool_call>\n{\"name\":\"list_songs\",\"arguments\":{}",
        _call("not json"),
        _call("[]"),
    ],
)
def test_malformed_call_shapes_are_named_protocol_errors(response):
    with pytest.raises(TextToolProtocolError):
        parse_text_tool_response(COWRITER_TOOL_CATALOG, response)


@pytest.mark.parametrize(
    "payload",
    [
        '{"name":"list_songs","arguments":{},"extra":true}',
        '{"name":"list_songs"}',
        '{"name":"list_songs","arguments":"no"}',
        '{"name":"list_songs","arguments":[]}',
        '{"name":"list_songs","arguments":null}',
        '{"name":"get_song","arguments":{}}',
        '{"name":"get_song","arguments":{"song_id":3}}',
        '{"name":"get_song","arguments":{"song_id":"song-1","extra":true}}',
    ],
)
def test_schema_violations_are_named_protocol_errors_before_execution(payload):
    response = _call(payload)
    with pytest.raises(TextToolProtocolError):
        parse_text_tool_response(COWRITER_TOOL_CATALOG, response)


@pytest.mark.parametrize("name", ["delete_everything"])
def test_unknown_tool_is_a_named_protocol_error_before_execution(name):
    response = _call(f'{{"name":"{name}","arguments":{{}}}}')
    with pytest.raises(TextToolProtocolError):
        parse_text_tool_response(COWRITER_TOOL_CATALOG, response)


def test_tool_results_are_json_data_in_the_result_tags():
    assert render_tool_result(COWRITER_TOOL_CATALOG, {"song_id": "song-1", "updated": True}) == (
        '<songmaker_tool_result>\n{"song_id":"song-1","updated":true}\n'
        "</songmaker_tool_result>"
    )


def test_protocol_rejection_never_logs_model_or_protocol_text(caplog):
    secret_protocol = _call(
        '{"name":"get_song","arguments":{"song_id":"song-secret","lyrics":"private lyrics"}}'
    )

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(TextToolProtocolError) as raised:
            parse_text_tool_response(COWRITER_TOOL_CATALOG, secret_protocol)

    assert raised.value.__cause__ is None
    assert secret_protocol not in caplog.text
    assert "song-secret" not in caplog.text
    assert "private lyrics" not in caplog.text


A_BRANDED_CATALOG = ToolCatalog(
    tools=(
        ToolDeclaration(
            name="open_slide",
            description="Open one slide of the deck.",
            parameters={
                "type": "object",
                "properties": {"slide_id": {"type": "string"}},
                "required": ["slide_id"],
                "additionalProperties": False,
            },
        ),
    ),
    markup=ToolProtocolMarkup(tag_namespace="atelier", product_name="Atelier"),
)


def test_the_default_markup_is_the_wording_this_package_shipped_with():
    markup = ToolProtocolMarkup()

    assert markup.call_open_tag == "<songmaker_tool_call>"
    assert markup.call_close_tag == "</songmaker_tool_call>"
    assert markup.result_open_tag == "<songmaker_tool_result>"
    assert markup.result_close_tag == "</songmaker_tool_result>"
    assert markup.product_name == "Songmaker"


def test_a_host_brands_the_prompt_and_the_markers_it_is_parsed_with():
    call = (
        "<atelier_tool_call>\n"
        '{"name":"open_slide","arguments":{"slide_id":"slide-1"}}\n'
        "</atelier_tool_call>"
    )

    prompt = render_tool_catalog(A_BRANDED_CATALOG)

    assert prompt.startswith("To call a Atelier tool,")
    assert "<atelier_tool_call>" in prompt
    assert "songmaker" not in prompt
    assert parse_text_tool_response(A_BRANDED_CATALOG, call) == TextToolCall(
        "open_slide", {"slide_id": "slide-1"},
    )
    assert render_tool_result(A_BRANDED_CATALOG, {"ok": True}) == (
        '<atelier_tool_result>\n{"ok":true}\n</atelier_tool_result>'
    )


def test_a_branded_catalog_reads_another_hosts_markers_as_ordinary_text():
    songmaker_call = _call('{"name":"open_slide","arguments":{"slide_id":"slide-1"}}')

    assert parse_text_tool_response(A_BRANDED_CATALOG, songmaker_call) == FinalText(
        songmaker_call,
    )


def test_a_catalog_refuses_a_tool_it_never_declared():
    undeclared = (
        "<atelier_tool_call>\n"
        '{"name":"get_song","arguments":{"song_id":"song-1"}}\n'
        "</atelier_tool_call>"
    )

    with pytest.raises(TextToolProtocolError):
        parse_text_tool_response(A_BRANDED_CATALOG, undeclared)

"""A person's own agent reads a refusal's sentence and its catalog key from the tool answer."""

from __future__ import annotations

from support.mcp_world import McpWorld


def test_a_second_preset_of_the_same_name_is_refused_with_its_sentence_and_key(
    household: McpWorld,
) -> None:
    arguments = {"name": "Fresh", "model_mode": "sft", "params": {}}
    household.call("create_preset", arguments)

    reply = household.call("create_preset", arguments)

    assert reply.is_error
    assert reply.json() == {
        "detail": "A preset with that name already exists",
        "message": {"key": "presetRefusal.nameTaken", "values": {}},
    }

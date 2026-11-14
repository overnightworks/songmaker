"""A person's own agent reads a refusal's sentence and its catalog key from the tool answer."""

from __future__ import annotations

from support.mcp_tool_table import BOB
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


def test_a_take_nobody_owns_is_refused_with_its_sentence_and_key(household: McpWorld) -> None:
    reply = household.call("get_take", {"gen_id": "no-such-take"})

    assert reply.is_error
    assert reply.json() == {
        "detail": "Generation not found",
        "message": {"key": "generationRefusal.notFound", "values": {}},
    }


def test_a_preset_of_another_person_is_refused_like_a_missing_one(household: McpWorld) -> None:
    foreign = household.call("update_preset", {"preset_id": f"preset-{BOB}", "name": "Fresh"})
    missing = household.call("update_preset", {"preset_id": "no-such-preset", "name": "Fresh"})

    assert foreign.is_error
    assert foreign.json() == missing.json() == {
        "detail": "Preset not found",
        "message": {"key": "presetRefusal.notFound", "values": {}},
    }

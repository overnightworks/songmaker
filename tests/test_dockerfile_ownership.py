"""No image changes ownership of its tree recursively in its final stage."""

from __future__ import annotations

import re

import pytest
from support.dockerfile_stages import final_stage_instructions
from support.repository_root import REPOSITORY_ROOT

RECURSIVE_CHOWN = re.compile(r"\bchown(?:\s+-\S+)*?\s+(?:-\w*R\w*|--recursive)\b")


@pytest.mark.parametrize(
    "instruction",
    [
        "RUN chown -R songmaker:songmaker /app",
        "RUN chown -f -R songmaker:songmaker /app",
        "RUN chown --verbose --recursive songmaker:songmaker /app",
    ],
)
def test_recursive_chown_is_found_after_other_options(instruction: str) -> None:
    assert RECURSIVE_CHOWN.search(instruction)


def test_no_final_stage_instruction_changes_ownership_recursively() -> None:
    offenders = [
        instruction
        for instruction in final_stage_instructions(REPOSITORY_ROOT / "Dockerfile")
        if RECURSIVE_CHOWN.search(instruction)
    ]

    assert offenders == []

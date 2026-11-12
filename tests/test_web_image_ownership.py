"""The web image leaves its code owned by root."""

from __future__ import annotations

import re

from support.dockerfile_stages import final_stage_instructions
from support.repository_root import REPOSITORY_ROOT

RECURSIVE_CHOWN = re.compile(r"\bchown\s+(?:-\w*R|--recursive)")


def test_no_final_stage_instruction_changes_ownership_recursively() -> None:
    offenders = [
        instruction
        for instruction in final_stage_instructions(REPOSITORY_ROOT / "Dockerfile")
        if RECURSIVE_CHOWN.search(instruction)
    ]

    assert offenders == []

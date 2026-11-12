"""Reads a Dockerfile as instructions, whole or per build stage."""

from __future__ import annotations

from pathlib import Path


def dockerfile_instructions(dockerfile: Path) -> list[str]:
    """Every instruction of the file with continuation lines joined and comments dropped."""
    instructions: list[str] = []
    current_instruction = ""
    for line in dockerfile.read_text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        current_instruction += line.rstrip().removesuffix("\\") + " "
        if line.rstrip().endswith("\\"):
            continue
        instructions.append(current_instruction.strip())
        current_instruction = ""
    return instructions


def final_stage_instructions(dockerfile: Path) -> list[str]:
    """The instructions from the file's last ``FROM`` on."""
    instructions = dockerfile_instructions(dockerfile)
    last_stage_start = max(
        index
        for index, instruction in enumerate(instructions)
        if instruction.upper().startswith("FROM ")
    )
    return instructions[last_stage_start:]

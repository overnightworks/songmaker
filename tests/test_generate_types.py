"""Tests for the FastAPI API type generator."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import generate_types  # noqa: E402


class SeededChild(BaseModel):
    label: str


class SeededRequest(BaseModel):
    children: list[SeededChild | str]


class SeededResponse(BaseModel):
    child: SeededChild


def test_check_detects_seeded_route_models_and_accepts_generated_types(
    tmp_path: Path,
    capsys,
) -> None:
    router = APIRouter()

    @router.post("/seed", response_model=SeededResponse)
    async def seed(request: SeededRequest) -> SeededResponse:
        return SeededResponse(child=request.children[0])

    result = generate_types.generate((router,))
    output_path = tmp_path / "types.ts"
    output_path.write_text(generate_types.HEADER)

    assert not generate_types.check_generated_types(result, output_path)
    failed_output = capsys.readouterr().out
    assert "Checked 4 API models" in failed_output
    assert "out of sync" in failed_output
    assert "SeededResponse" in failed_output
    assert "export interface SeededResponse" in result.content
    assert "export interface SeededRequest" in result.content
    assert "children: (SeededChild | string)[]" in result.content

    output_path.write_text(result.content)

    assert generate_types.check_generated_types(result, output_path)
    assert "Checked 4 API models" in capsys.readouterr().out

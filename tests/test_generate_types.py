"""Tests for the FastAPI API type generator."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Literal

import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import generate_types  # noqa: E402


class SeededChild(BaseModel):
    label: str


class SeededRequest(BaseModel):
    children: list[SeededChild | str]


class SeededResponse(BaseModel):
    child: SeededChild


class DiscriminatedAlbumHit(BaseModel):
    type: Literal["album"] = "album"


class DiscriminatedSongHit(BaseModel):
    type: Literal["song"] = "song"


DiscriminatedHit = Annotated[
    DiscriminatedAlbumHit | DiscriminatedSongHit,
    Field(discriminator="type"),
]


class DiscriminatedHitResponse(BaseModel):
    items: list[DiscriminatedHit]


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
    assert "Checked 3 API models (3 from FastAPI routes, 0 from api_models exports" in failed_output
    assert "out of sync" in failed_output
    assert "SeededResponse" in failed_output
    assert "export interface SeededResponse" in result.content
    assert "export interface SeededRequest" in result.content
    assert "children: (SeededChild | string)[]" in result.content

    output_path.write_text(result.content)

    assert generate_types.check_generated_types(result, output_path)
    checked_output = capsys.readouterr().out
    assert (
        "Checked 3 API models (3 from FastAPI routes, 0 from api_models exports"
        in checked_output
    )


def test_generates_parenthesized_discriminated_union_list() -> None:
    assert (
        generate_types._py_type_to_ts(list[DiscriminatedHit])
        == "(DiscriminatedAlbumHit | DiscriminatedSongHit)[]"
    )


def test_exempts_internal_routes_and_reports_their_count() -> None:
    router = APIRouter()

    @router.post("/api/internal/worker")
    async def register_worker(request: SeededRequest) -> None:
        del request

    result = generate_types.generate((router,))

    assert SeededRequest not in result.models
    assert "1 exempt routes" in generate_types._checked_message(result)


def test_route_routers_cover_every_api_route_in_the_real_app(tmp_path: Path) -> None:
    from conftest import make_test_app

    client, _ = make_test_app(tmp_path)
    app_route_paths = {
        route.path
        for route in client.app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/")
    }
    discovered_route_paths = {
        route.path
        for router in generate_types._route_routers()
        for route in router.routes
        if isinstance(route, APIRoute)
    }

    assert app_route_paths <= discovered_route_paths


@pytest.mark.parametrize("arguments", (["generate_types.py", "--check"], ["generate_types.py"]))
def test_route_introspection_failure_exits_without_writing_types(
    arguments: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "types.ts"
    output_path.write_text("existing types")

    def unavailable_routers() -> tuple[APIRouter, ...]:
        raise ModuleNotFoundError("router module is unavailable")

    monkeypatch.setattr(generate_types, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(generate_types, "_route_routers", unavailable_routers)
    monkeypatch.setattr(sys, "argv", arguments)

    with pytest.raises(SystemExit) as error:
        generate_types.main()

    assert error.value.code == 1
    assert output_path.read_text() == "existing types"
    error_output = capsys.readouterr().out
    assert "FAIL: route introspection unavailable: router module is unavailable" in error_output

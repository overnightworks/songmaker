"""Tests for ``scripts/check_pinned_images_match.py``."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_pinned_images_match as checker  # noqa: E402

COMPOSE_PIN = "postgres:16.15-alpine@sha256:" + "a" * 64
DRIFTED_PIN = "postgres:16.16-alpine@sha256:" + "b" * 64


def _write_compose(directory: Path, postgres_image: str) -> Path:
    path = directory / "docker-compose.yml"
    path.write_text(
        textwrap.dedent(
            f"""\
            services:
              redis:
                image: redis:7
              postgres:
                image: {postgres_image}
            """
        )
    )
    return path


def _write_workflow(directory: Path, service_image: str) -> Path:
    path = directory / "ci.yml"
    path.write_text(
        textwrap.dedent(
            f"""\
            on: push
            jobs:
              backend:
                runs-on: ubuntu-latest
              postgresql-contract:
                runs-on: ubuntu-latest
                services:
                  postgres:
                    image: {service_image}
            """
        )
    )
    return path


def test_equal_pins_pass(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    compose = _write_compose(tmp_path, COMPOSE_PIN)
    workflow = _write_workflow(tmp_path, COMPOSE_PIN)

    assert checker.run(compose, workflow) == 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    ("compose_image", "workflow_image"),
    [
        pytest.param(COMPOSE_PIN, DRIFTED_PIN, id="ci_behind_compose"),
        pytest.param(DRIFTED_PIN, COMPOSE_PIN, id="compose_moved_first"),
    ],
)
def test_drifting_pins_fail_and_name_both_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    compose_image: str,
    workflow_image: str,
) -> None:
    compose = _write_compose(tmp_path, compose_image)
    workflow = _write_workflow(tmp_path, workflow_image)

    assert checker.run(compose, workflow) == 1
    message = capsys.readouterr().err
    assert compose_image in message
    assert workflow_image in message


def test_missing_ci_postgres_service_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    compose = _write_compose(tmp_path, COMPOSE_PIN)
    workflow = tmp_path / "ci.yml"
    workflow.write_text("on: push\njobs:\n  backend:\n    runs-on: ubuntu-latest\n")

    assert checker.run(compose, workflow) == 1
    assert "postgres" in capsys.readouterr().err


def test_repository_pins_match() -> None:
    assert checker.main() == 0

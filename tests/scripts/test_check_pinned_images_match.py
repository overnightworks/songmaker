"""Tests for ``scripts/check_pinned_images_match.py``."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_pinned_images_match as checker  # noqa: E402

POSTGRES_PIN = "postgres:16.15-alpine@sha256:" + "a" * 64
REDIS_PIN = "redis:7.4.12-alpine@sha256:" + "c" * 64
DRIFTED_POSTGRES_PIN = "postgres:16.16-alpine@sha256:" + "b" * 64
DRIFTED_REDIS_PIN = "redis:7.4.13-alpine@sha256:" + "d" * 64


def _write_compose(directory: Path, postgres_image: str, redis_image: str) -> Path:
    path = directory / "docker-compose.test.yml"
    path.write_text(
        textwrap.dedent(
            f"""\
            services:
              redis:
                image: {redis_image}
              postgres:
                image: {postgres_image}
            """
        )
    )
    return path


def _write_workflow(directory: Path, postgres_image: str, redis_image: str) -> Path:
    path = directory / "ci.yml"
    path.write_text(
        textwrap.dedent(
            f"""\
            on: push
            jobs:
              backend:
                runs-on: ubuntu-latest
              database-tests:
                runs-on: ubuntu-latest
                services:
                  postgres:
                    image: {postgres_image}
                  redis:
                    image: {redis_image}
            """
        )
    )
    return path


def test_equal_pins_pass(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    compose = _write_compose(tmp_path, POSTGRES_PIN, REDIS_PIN)
    workflow = _write_workflow(tmp_path, POSTGRES_PIN, REDIS_PIN)

    assert checker.run(compose, workflow) == 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    ("compose_images", "workflow_images"),
    [
        pytest.param(
            (POSTGRES_PIN, REDIS_PIN), (DRIFTED_POSTGRES_PIN, REDIS_PIN), id="postgres_ci_behind"
        ),
        pytest.param(
            (DRIFTED_POSTGRES_PIN, REDIS_PIN),
            (POSTGRES_PIN, REDIS_PIN),
            id="postgres_compose_first",
        ),
        pytest.param(
            (POSTGRES_PIN, REDIS_PIN), (POSTGRES_PIN, DRIFTED_REDIS_PIN), id="redis_ci_behind"
        ),
        pytest.param(
            (POSTGRES_PIN, DRIFTED_REDIS_PIN), (POSTGRES_PIN, REDIS_PIN), id="redis_compose_first"
        ),
    ],
)
def test_drifting_pins_fail_and_name_both_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    compose_images: tuple[str, str],
    workflow_images: tuple[str, str],
) -> None:
    compose = _write_compose(tmp_path, *compose_images)
    workflow = _write_workflow(tmp_path, *workflow_images)

    assert checker.run(compose, workflow) == 1
    message = capsys.readouterr().err
    assert all(image in message for image in {*compose_images} ^ {*workflow_images})


@pytest.mark.parametrize(
    ("missing", "declared", "declared_image"),
    [("postgres", "redis", REDIS_PIN), ("redis", "postgres", POSTGRES_PIN)],
)
def test_missing_ci_service_fails(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    missing: str,
    declared: str,
    declared_image: str,
) -> None:
    compose = _write_compose(tmp_path, POSTGRES_PIN, REDIS_PIN)
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "on: push\njobs:\n  backend:\n    runs-on: ubuntu-latest\n"
        f"    services:\n      {declared}:\n        image: {declared_image}\n"
    )

    assert checker.run(compose, workflow) == 1
    assert f"'{missing}'" in capsys.readouterr().err


def _platform_manifests(postgres_image: str, redis_image: str) -> dict[str, str]:
    def statefulset(name: str, image: str) -> str:
        return (
            "apiVersion: apps/v1\nkind: StatefulSet\nspec:\n  template:\n    spec:\n"
            f"      containers:\n        - name: {name}\n"
            f"          image: docker.io/library/{image}\n"
        )

    return {
        checker.PLATFORM_MANIFESTS["postgres"]: "kind: Namespace\n---\n"
        + statefulset("postgres", postgres_image),
        checker.PLATFORM_MANIFESTS["redis"]: statefulset("redis", redis_image),
    }


def test_platform_leg_passes_when_tags_match_whatever_the_digest(tmp_path: Path) -> None:
    compose = _write_compose(tmp_path, POSTGRES_PIN, REDIS_PIN)
    workflow = _write_workflow(tmp_path, POSTGRES_PIN, REDIS_PIN)
    manifests = _platform_manifests(
        POSTGRES_PIN.replace("a" * 64, "e" * 64), REDIS_PIN.replace("c" * 64, "f" * 64)
    )

    assert checker.run(compose, workflow, manifests.__getitem__) == 0


@pytest.mark.parametrize(
    ("platform_postgres", "platform_redis", "drifted_service"),
    [
        pytest.param(DRIFTED_POSTGRES_PIN, REDIS_PIN, "postgres", id="platform_postgres_ahead"),
        pytest.param(POSTGRES_PIN, DRIFTED_REDIS_PIN, "redis", id="platform_redis_ahead"),
    ],
)
def test_platform_leg_fails_when_the_platform_runs_another_tag(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    platform_postgres: str,
    platform_redis: str,
    drifted_service: str,
) -> None:
    compose = _write_compose(tmp_path, POSTGRES_PIN, REDIS_PIN)
    workflow = _write_workflow(tmp_path, POSTGRES_PIN, REDIS_PIN)
    manifests = _platform_manifests(platform_postgres, platform_redis)

    assert checker.run(compose, workflow, manifests.__getitem__) == 1
    assert f"{drifted_service} differs from the platform" in capsys.readouterr().err


def test_platform_leg_fails_when_the_manifest_names_no_image(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    compose = _write_compose(tmp_path, POSTGRES_PIN, REDIS_PIN)
    workflow = _write_workflow(tmp_path, POSTGRES_PIN, REDIS_PIN)

    assert checker.run(compose, workflow, lambda _path: "kind: Namespace\n") == 1
    assert "no 'postgres' image" in capsys.readouterr().err


def test_repository_pins_match() -> None:
    assert checker.main([]) == 0

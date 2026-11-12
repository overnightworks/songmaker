"""CI guard: CI's Postgres and Redis services run the images the test stack pins.

Dependabot moves the pins in docker/docker-compose.test.yml only; the services in
.github/workflows/ci.yml repeat them by hand, so a compose bump would leave CI
testing another Postgres or Redis than the test stack boots.

Run from the project root:

    python scripts/check_pinned_images_match.py
"""
# ruff: noqa: T201 - this check reports a pin mismatch on stderr

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPOSITORY_ROOT / "docker/docker-compose.test.yml"
WORKFLOW_FILE = REPOSITORY_ROOT / ".github/workflows/ci.yml"
SERVICE_NAMES = ("postgres", "redis")


def _compose_image(compose_file: Path, service_name: str) -> str | None:
    document = yaml.safe_load(compose_file.read_text())
    return document.get("services", {}).get(service_name, {}).get("image")


def _workflow_images(workflow_file: Path, service_name: str) -> dict[str, str]:
    """Map each job that declares the service to that service's image."""
    jobs = yaml.safe_load(workflow_file.read_text()).get("jobs", {})
    return {
        job_name: job["services"][service_name]["image"]
        for job_name, job in jobs.items()
        if service_name in job.get("services", {})
    }


def _mismatches(compose_file: Path, workflow_file: Path, service_name: str) -> list[str]:
    compose_image = _compose_image(compose_file, service_name)
    workflow_images = _workflow_images(workflow_file, service_name)
    if compose_image is None:
        return [f"{compose_file}: no '{service_name}' service image"]
    if not workflow_images:
        return [f"{workflow_file}: no job declares a '{service_name}' service"]
    return [
        f"{service_name} image differs: {compose_file.name} pins {compose_image}, "
        f"{workflow_file.name} job '{job}' pins {image}"
        for job, image in workflow_images.items()
        if image != compose_image
    ]


def run(compose_file: Path, workflow_file: Path) -> int:
    messages = [
        message
        for service_name in SERVICE_NAMES
        for message in _mismatches(compose_file, workflow_file, service_name)
    ]
    for message in messages:
        print(message, file=sys.stderr)
    return 1 if messages else 0


def main() -> int:
    return run(COMPOSE_FILE, WORKFLOW_FILE)


if __name__ == "__main__":
    raise SystemExit(main())

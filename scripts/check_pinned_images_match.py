"""CI guard: CI's Postgres service runs the image docker-compose.yml pins.

Dependabot moves the pin in docker-compose.yml only; the service in
.github/workflows/ci.yml repeats it by hand, so a compose bump would leave CI
testing another Postgres than the one deployed.

Run from the project root:

    python scripts/check_pinned_images_match.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPOSITORY_ROOT / "docker-compose.yml"
WORKFLOW_FILE = REPOSITORY_ROOT / ".github/workflows/ci.yml"
SERVICE_NAME = "postgres"


def _compose_image(compose_file: Path) -> str | None:
    document = yaml.safe_load(compose_file.read_text())
    return document.get("services", {}).get(SERVICE_NAME, {}).get("image")


def _workflow_images(workflow_file: Path) -> dict[str, str]:
    """Map each job that declares a Postgres service to that service's image."""
    jobs = yaml.safe_load(workflow_file.read_text()).get("jobs", {})
    return {
        job_name: job["services"][SERVICE_NAME]["image"]
        for job_name, job in jobs.items()
        if SERVICE_NAME in job.get("services", {})
    }


def run(compose_file: Path, workflow_file: Path) -> int:
    compose_image = _compose_image(compose_file)
    workflow_images = _workflow_images(workflow_file)
    if compose_image is None:
        print(f"{compose_file}: no '{SERVICE_NAME}' service image", file=sys.stderr)
        return 1
    if not workflow_images:
        print(f"{workflow_file}: no job declares a '{SERVICE_NAME}' service", file=sys.stderr)
        return 1
    drifted = {job: image for job, image in workflow_images.items() if image != compose_image}
    for job, image in drifted.items():
        print(
            f"{SERVICE_NAME} image differs: {compose_file.name} pins {compose_image}, "
            f"{workflow_file.name} job '{job}' pins {image}",
            file=sys.stderr,
        )
    return 1 if drifted else 0


def main() -> int:
    return run(COMPOSE_FILE, WORKFLOW_FILE)


if __name__ == "__main__":
    raise SystemExit(main())

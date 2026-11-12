"""CI guard: CI's Postgres and Redis services run the images the test stack pins,
and those pins carry the version tag the platform runs live.

Dependabot moves the pins in docker/docker-compose.test.yml only; the services in
.github/workflows/ci.yml repeat them by hand, so a compose bump would leave CI
testing another Postgres or Redis than the test stack boots. The platform leg
(``--platform``, CI only because it reads overnightworks/platform's main over the
network) fails when a test pin's version tag differs from the platform's.

Run from the project root:

    python scripts/check_pinned_images_match.py [--platform]
"""
# ruff: noqa: T201 - this check reports a pin mismatch on stderr

from __future__ import annotations

import argparse
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPOSITORY_ROOT / "docker/docker-compose.test.yml"
WORKFLOW_FILE = REPOSITORY_ROOT / ".github/workflows/ci.yml"
SERVICE_NAMES = ("postgres", "redis")
PLATFORM_RAW_URL = "https://raw.githubusercontent.com/overnightworks/platform/main/"
PLATFORM_MANIFESTS = {
    "postgres": "infrastructure/postgres/postgres.yaml",
    "redis": "apps/songmaker/redis.yaml",
}
FETCH_TIMEOUT_SECONDS = 30


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


def fetch_platform_manifest(relative_path: str) -> str:
    url = PLATFORM_RAW_URL + relative_path
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed https URL
        return response.read().decode()


def _version_tag(image: str) -> str:
    """The tag of ``registry/name:tag@sha256:digest``."""
    return image.split("@", 1)[0].rsplit(":", 1)[-1]


def _images_in(node: object, service_name: str) -> list[str]:
    """Images of ``service_name`` found anywhere in a Kubernetes-style manifest."""
    if isinstance(node, dict):
        found = [
            value
            for key, value in node.items()
            if key == "image" and isinstance(value, str) and f"/{service_name}:" in value
        ]
        return found + [i for value in node.values() for i in _images_in(value, service_name)]
    if isinstance(node, list):
        return [i for value in node for i in _images_in(value, service_name)]
    return []


def _platform_mismatches(
    compose_file: Path, service_name: str, fetch: Callable[[str], str]
) -> list[str]:
    compose_image = _compose_image(compose_file, service_name)
    if compose_image is None:
        return []  # reported by the compose leg
    manifest_path = PLATFORM_MANIFESTS[service_name]
    platform_images = [
        image
        for document in yaml.safe_load_all(fetch(manifest_path))
        for image in _images_in(document, service_name)
    ]
    if not platform_images:
        return [f"platform {manifest_path}: no '{service_name}' image"]
    if _version_tag(platform_images[0]) == _version_tag(compose_image):
        return []
    return [
        f"{service_name} differs from the platform: {compose_file.name} pins {compose_image}, "
        f"platform {manifest_path} runs {platform_images[0]}"
    ]


def run(
    compose_file: Path,
    workflow_file: Path,
    platform_fetch: Callable[[str], str] | None = None,
) -> int:
    messages = [
        message
        for service_name in SERVICE_NAMES
        for message in _mismatches(compose_file, workflow_file, service_name)
    ]
    if platform_fetch is not None:
        messages += [
            message
            for service_name in SERVICE_NAMES
            for message in _platform_mismatches(compose_file, service_name, platform_fetch)
        ]
    for message in messages:
        print(message, file=sys.stderr)
    return 1 if messages else 0


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--platform", action="store_true", help="also compare with the platform's main (network)"
    )
    options = parser.parse_args(arguments)
    return run(COMPOSE_FILE, WORKFLOW_FILE, fetch_platform_manifest if options.platform else None)


if __name__ == "__main__":
    raise SystemExit(main())

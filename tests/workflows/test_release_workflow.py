"""Repository contract for the Release workflow (live proof is a dispatch)."""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RELEASE_JOBS = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())["jobs"]
COMPOSE_SERVICES = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
QUALITY_WORKFLOWS = "overnightworks/quality/"


def _compose_dockerfiles(services: dict[str, dict] = COMPOSE_SERVICES) -> set[str]:
    dockerfiles = set()
    for name, service in services.items():
        build = service.get("build")
        if build is None:
            continue
        assert isinstance(build, dict), f"service {name} writes build as a string"
        dockerfiles.add(build["dockerfile"])
    return dockerfiles


def test_released_dockerfiles_are_the_compose_built_ones():
    released = {entry["file"] for entry in RELEASE_JOBS["image"]["strategy"]["matrix"]["include"]}
    assert released == _compose_dockerfiles()


def test_a_compose_build_written_as_a_string_fails_loudly():
    with pytest.raises(AssertionError, match="writes build as a string"):
        _compose_dockerfiles({"extra": {"build": "./extra"}})


def _quality_pins() -> list[str]:
    return [
        job["uses"].partition("@")[2]
        for job in RELEASE_JOBS.values()
        if job.get("uses", "").startswith(QUALITY_WORKFLOWS)
    ]


def test_every_quality_workflow_is_pinned_to_one_commit():
    pins = _quality_pins()
    assert pins
    assert len(set(pins)) == 1
    assert re.fullmatch(r"[0-9a-f]{40}", pins[0])


def test_no_job_inherits_secrets():
    assert not any(job.get("secrets") == "inherit" for job in RELEASE_JOBS.values())

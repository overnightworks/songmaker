"""G1–G3: Repository contract for the reusable quality gate (live proof is CI)."""

import datetime
import os
import re
import subprocess
import tomllib
from itertools import product
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_TEXT = (ROOT / ".github/workflows/ci.yml").read_text()
WORKFLOW = yaml.safe_load(WORKFLOW_TEXT)
JOBS = WORKFLOW["jobs"]
REPORTS = ("reports/coverage.xml", "reports/frontend-coverage/lcov.info")


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        (
            "needs",
            [
                "backend",
                "alert-rules",
                "postgresql-contract",
                "frontend",
                "coverage",
            ],
        ),
        ("if", "${{ !cancelled() }}"),
        ("permissions", {"contents": "read", "actions": "read"}),
        ("with", {"coverage-artifact": "coverage"}),
        ("secrets", {"SONAR_TOKEN": "${{ secrets.SONAR_TOKEN }}"}),
    ],
)
def test_g1_caller_contract(key, expected):
    assert JOBS["quality"][key] == expected


def test_g1_caller_identity_and_pin():
    assert "name" not in JOBS["quality"]
    assert "sonar" not in JOBS
    reference = JOBS["quality"]["uses"]
    assert re.fullmatch(
        r"overnightworks/quality/\.github/workflows/gate\.yml@[0-9a-f]{40}",
        reference,
    )
    assert re.search(
        rf"^\s+uses: {re.escape(reference)} # v0\.4\.0$",
        WORKFLOW_TEXT,
        re.MULTILINE,
    )


def test_g1_mandatory_names_match_rendered_dependencies():
    rendered_names = set()
    for job_id in set(JOBS["quality"]["needs"]) - {"coverage"}:
        job = JOBS[job_id]
        matrix = job.get("strategy", {}).get("matrix", {})
        for values in product(*matrix.values()):
            name = job["name"]
            for axis, value in zip(matrix, values, strict=True):
                name = name.replace("${{ matrix." + axis + " }}", str(value))
            rendered_names.add(name)
    config = tomllib.loads((ROOT / "quality/config.toml").read_text())
    assert set(config) == {"gate"}
    assert set(config["gate"]) == {"mandatory_jobs", "loosened"}
    loosened = config["gate"]["loosened"]
    assert isinstance(loosened, list)
    assert len(loosened) == 1
    entry = loosened[0]
    assert set(entry) == {"what", "item", "date", "reason"}
    assert isinstance(entry["date"], datetime.date)
    assert entry["what"] == 'mandatory job "Acceptance evidence (integration)" removed'
    mandatory = config["gate"]["mandatory_jobs"]
    assert len(mandatory) == len(set(mandatory)) == 4
    assert set(mandatory) == rendered_names


def test_g1_main_and_pull_requests_reach_the_gate():
    events = WORKFLOW.get("on", WORKFLOW.get(True))
    assert events == {
        "push": {"branches": ["main"]},
        "pull_request": {"branches": ["main"]},
        "workflow_dispatch": None,
    }
    assert WORKFLOW["concurrency"]["cancel-in-progress"] == "${{ github.ref != 'refs/heads/main' }}"


def test_g2_assembly_transports_both_reports():
    assembly = JOBS["coverage"]
    assert assembly["needs"] == ["backend", "frontend"]
    steps = assembly["steps"]
    downloads = [s for s in steps if s.get("uses", "").startswith("actions/download-artifact@")]
    assert [s["with"] for s in downloads] == [
        {"name": "sonar-coverage-backend", "path": "reports"},
        {"name": "sonar-coverage-frontend", "path": "reports"},
    ]
    assert not any(s.get("uses", "").startswith("actions/checkout@") for s in steps)
    (upload,) = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@")]
    assert upload["with"]["name"] == JOBS["quality"]["with"]["coverage-artifact"]
    assert upload["with"]["path"].splitlines() == list(REPORTS)
    assert upload["with"]["overwrite"] is True
    assert upload["with"]["if-no-files-found"] == "error"
    paths = [Path(p) for p in upload["with"]["path"].splitlines()]
    artifact_root = Path(os.path.commonpath([p.parent for p in paths]))
    properties = dict(
        line.split("=", 1)
        for line in (ROOT / "sonar-project.properties").read_text().splitlines()
        if line and not line.startswith("#")
    )
    assert [
        properties[key]
        for key in (
            "sonar.python.coverage.reportPaths",
            "sonar.javascript.lcov.reportPaths",
        )
    ] == [str(p.relative_to(artifact_root)) for p in paths]


@pytest.mark.parametrize("report", REPORTS)
@pytest.mark.parametrize("state", ["missing", "empty", "present"])
def test_g2_assembly_rejects_missing_or_empty_reports(tmp_path, report, state):
    for relative in REPORTS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative != report or state != "missing":
            path.write_text("" if relative == report and state == "empty" else "coverage")
    (script,) = [s["run"] for s in JOBS["coverage"]["steps"] if "run" in s]
    result = subprocess.run(["bash", "-e", "-c", script], cwd=tmp_path, check=False)
    assert (result.returncode == 0) == (state == "present")


def test_g3_properties_have_no_gate_overrides_or_exemptions():
    keys = {
        line.split("=", 1)[0]
        for line in (ROOT / "sonar-project.properties").read_text().splitlines()
        if line and not line.startswith("#")
    }
    assert "sonar.qualitygate.wait" not in keys
    assert not any(key.startswith("sonar.issue.ignore.") for key in keys)


@pytest.mark.parametrize("job_id", ["coverage", "quality"])
def test_g3_new_action_references_are_commit_pinned(job_id):
    job = JOBS[job_id]
    references = (
        [job["uses"]]
        if "uses" in job
        else [step["uses"] for step in job["steps"] if "uses" in step]
    )
    assert references
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref) for ref in references)

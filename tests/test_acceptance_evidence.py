from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
SCRIPT = PROJECT_ROOT / "scripts/acceptance_evidence.py"
sys.path.insert(0, str(SCRIPT.parent))
SPECIFICATION = importlib.util.spec_from_file_location("songmaker_acceptance_evidence", SCRIPT)
assert SPECIFICATION is not None
assert SPECIFICATION.loader is not None
MODULE = importlib.util.module_from_spec(SPECIFICATION)
sys.modules[SPECIFICATION.name] = MODULE
SPECIFICATION.loader.exec_module(MODULE)

AcceptanceClaim = MODULE.AcceptanceClaim
AcceptanceEvidenceError = MODULE.AcceptanceEvidenceError
AcceptanceEntry = MODULE.AcceptanceEntry
collect_claims = MODULE.collect_claims
run = MODULE.run
validate_claims = MODULE.validate_claims


def write_test_source(tmp_path: Path, source: str) -> Path:
    tests = tmp_path / "tests"
    tests.mkdir()
    target = tests / "test_claim.py"
    target.write_text(source, encoding="utf-8")
    return tests


def acceptance_entry(identifier: str, *, proof_kind: str = "integration", critical: bool = True):
    return AcceptanceEntry(
        identifier, "A musician sees the expected state.", ("REQ-DEMO-01",), proof_kind, critical
    )


def source_text(*lines: str) -> str:
    return "\n".join(lines) + "\n"


PYTEST_CONFIG = source_text(
    "[tool.pytest.ini_options]",
    'markers = ["acceptance(identifier): Acceptance evidence claim."]',
)
MALFORMED_MARKERS = (
    source_text("import pytest", "pytestmark = pytest.mark.acceptance('ACC-DEMO-01')"),
    source_text(
        "import pytest",
        "class TestClaim:",
        "    @pytest.mark.acceptance('ACC-DEMO-01')",
        "    def test_claim(self):",
        "        pass",
    ),
    source_text(
        "from pytest import mark as marks",
        "@marks.acceptance('ACC-DEMO-01')",
        "def test_claim():",
        "    pass",
    ),
    source_text(
        "import pytest",
        "@pytest.mark.acceptance(identifier='ACC-DEMO-01')",
        "def test_claim():",
        "    pass",
    ),
    source_text(
        "import pytest",
        "@pytest.mark.acceptance('ACC-DEMO-01', 'ACC-DEMO-02')",
        "def test_claim():",
        "    pass",
    ),
    source_text(
        "import pytest",
        "identifier = 'ACC-DEMO-01'",
        "@pytest.mark.acceptance(identifier)",
        "def test_claim():",
        "    pass",
    ),
    source_text(
        "import pytest",
        "@pytest.mark.acceptance('ACC-DEMO-01')",
        "@pytest.mark.acceptance('ACC-DEMO-01')",
        "def test_claim():",
        "    pass",
    ),
    source_text(
        "from pytest.mark import acceptance",
        "@acceptance('ACC-DEMO-01')",
        "def test_claim():",
        "    pass",
    ),
    source_text(
        "import pytest",
        "@pytest.mark.acceptance",
        "def test_claim():",
        "    pass",
    ),
)


@pytest.mark.parametrize(
    "source",
    MALFORMED_MARKERS,
)
def test_collect_claims_rejects_malformed_markers(tmp_path: Path, source: str) -> None:
    with pytest.raises(AcceptanceEvidenceError):
        collect_claims(write_test_source(tmp_path, source).parent)


def test_validate_claims_rejects_unknown_duplicate_and_orphaned_critical_acceptances(
    tmp_path: Path,
) -> None:
    tests = write_test_source(
        tmp_path,
        source_text(
            "import pytest",
            "@pytest.mark.acceptance('ACC-UNKNOWN-01')",
            "def test_claim():",
            "    pass",
        ),
    )
    unknown = collect_claims(tests.parent)
    with pytest.raises(AcceptanceEvidenceError, match="unknown acceptance"):
        validate_claims(unknown, (acceptance_entry("ACC-DEMO-01"),))
    duplicate = (
        AcceptanceClaim("tests/test_one.py::test_claim", "ACC-DEMO-01"),
        AcceptanceClaim("tests/test_two.py::test_claim", "ACC-DEMO-01"),
    )
    with pytest.raises(AcceptanceEvidenceError, match="duplicate test claims"):
        validate_claims(duplicate, (acceptance_entry("ACC-DEMO-01"),))
    with pytest.raises(AcceptanceEvidenceError, match="has no test claim"):
        validate_claims((), (acceptance_entry("ACC-DEMO-01"),))


def test_validate_claims_allows_only_unclaimed_noncritical_integration() -> None:
    assert validate_claims((), (acceptance_entry("ACC-DEMO-01", critical=False),)) == ()
    with pytest.raises(AcceptanceEvidenceError, match="unsupported proof_kind"):
        validate_claims(
            (), (acceptance_entry("ACC-DEMO-01", proof_kind="browser", critical=False),)
        )


def test_run_writes_a_failed_report_when_validation_fails(tmp_path: Path, monkeypatch) -> None:
    def fail_loading(_: Path):
        raise AcceptanceEvidenceError("manifest failure")

    monkeypatch.setattr(MODULE, "load_claims", fail_loading)
    output = tmp_path / "report.json"
    assert run(PROJECT_ROOT, output) == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    assert report["overall_outcome"] == "failed"
    assert report["exit_status"] == 2
    assert (
        report["head"]
        == subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
        ).strip()
    )
    assert report["records"] == []


def test_run_writes_a_failed_report_when_collection_fails(tmp_path: Path, monkeypatch) -> None:
    def fail_collection(_: Path):
        raise AcceptanceEvidenceError("collection failure")

    monkeypatch.setattr(MODULE, "collect_claims", fail_collection)
    output = tmp_path / "report.json"
    assert run(PROJECT_ROOT, output) == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["overall_outcome"] == "failed"
    assert report["exit_status"] == 2
    assert report["error"] == "collection failure"


def test_run_retains_known_claims_when_manifest_validation_fails(
    tmp_path: Path, monkeypatch
) -> None:
    claims = (
        AcceptanceClaim("tests/test_second.py::test_second", "ACC-DEMO-02"),
        AcceptanceClaim("tests/test_first.py::test_first", "ACC-DEMO-01"),
    )
    monkeypatch.setattr(MODULE, "collect_claims", lambda _: claims)
    monkeypatch.setattr(MODULE, "read_requirement_shelf", lambda _: object())
    monkeypatch.setattr(
        MODULE,
        "read_acceptance_manifest",
        lambda *_: (
            acceptance_entry("ACC-DEMO-01"),
            acceptance_entry("ACC-DEMO-02", proof_kind="browser"),
            acceptance_entry("ACC-ORPHAN-01"),
        ),
    )
    first_output = tmp_path / "first.json"
    second_output = tmp_path / "second.json"

    assert run(tmp_path, first_output) == 2
    assert run(tmp_path, second_output) == 2

    first_report = json.loads(first_output.read_text(encoding="utf-8"))
    second_report = json.loads(second_output.read_text(encoding="utf-8"))
    assert first_report["error"] == (
        "acceptance ACC-DEMO-02 has unsupported proof_kind 'browser'"
    )
    assert first_report["exit_status"] == 2
    assert first_report["overall_outcome"] == "failed"
    assert first_report["records"] == second_report["records"] == [
        {
            "acceptance_id": "ACC-DEMO-01",
            "command": [*MODULE.PYTEST_COMMAND, "tests/test_first.py::test_first"],
            "exit_status": None,
            "nodeid": "tests/test_first.py::test_first",
            "outcome": "not_run",
            "proof_kind": "integration",
        },
        {
            "acceptance_id": "ACC-DEMO-02",
            "command": [*MODULE.PYTEST_COMMAND, "tests/test_second.py::test_second"],
            "exit_status": None,
            "nodeid": "tests/test_second.py::test_second",
            "outcome": "not_run",
            "proof_kind": "browser",
        },
    ]


def test_run_retains_only_claims_discovered_before_collection_failure(
    tmp_path: Path, monkeypatch
) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_one_known.py").write_text(
        source_text(
            "import pytest",
            "@pytest.mark.acceptance('ACC-DEMO-01')",
            "def test_known():",
            "    pass",
        ),
        encoding="utf-8",
    )
    (tests / "test_two_broken.py").write_text("def test_broken(:\n", encoding="utf-8")
    actual_run = subprocess.run

    def reject_pytest(command, *arguments, **keywords):
        if command[:3] == list(MODULE.PYTEST_COMMAND[:3]):
            raise AssertionError("pytest must not run after collection failure")
        return actual_run(command, *arguments, **keywords)

    monkeypatch.setattr(MODULE.subprocess, "run", reject_pytest)
    output = tmp_path / "report.json"

    assert run(tmp_path, output) == 2

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["error"] == "cannot parse tests/test_two_broken.py"
    assert report["overall_outcome"] == "failed"
    assert report["records"] == [
        {
            "acceptance_id": "ACC-DEMO-01",
            "command": [*MODULE.PYTEST_COMMAND, "tests/test_one_known.py::test_known"],
            "exit_status": None,
            "nodeid": "tests/test_one_known.py::test_known",
            "outcome": "not_run",
            "proof_kind": "integration",
        }
    ]


def test_run_retains_all_known_claims_when_pytest_cannot_start(tmp_path: Path, monkeypatch) -> None:
    claims = (
        AcceptanceClaim("tests/test_one.py::test_one", "ACC-DEMO-01"),
        AcceptanceClaim("tests/test_two.py::test_two", "ACC-DEMO-02"),
    )
    monkeypatch.setattr(MODULE, "load_claims", lambda _: claims)
    actual_run = subprocess.run

    def fail_pytest(command, *arguments, **keywords):
        if command[:3] == list(MODULE.PYTEST_COMMAND[:3]):
            raise OSError("pytest executable unavailable")
        return actual_run(command, *arguments, **keywords)

    monkeypatch.setattr(MODULE.subprocess, "run", fail_pytest)
    output = tmp_path / "report.json"

    assert run(PROJECT_ROOT, output) == 2

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["error"] == "pytest executable unavailable"
    assert report["exit_status"] == 2
    assert report["overall_outcome"] == "failed"
    assert report["records"] == [
        {
            "acceptance_id": "ACC-DEMO-01",
            "command": [*MODULE.PYTEST_COMMAND, "tests/test_one.py::test_one"],
            "exit_status": None,
            "nodeid": "tests/test_one.py::test_one",
            "outcome": "not_run",
            "proof_kind": "integration",
        },
        {
            "acceptance_id": "ACC-DEMO-02",
            "command": [*MODULE.PYTEST_COMMAND, "tests/test_two.py::test_two"],
            "exit_status": None,
            "nodeid": "tests/test_two.py::test_two",
            "outcome": "not_run",
            "proof_kind": "integration",
        },
    ]


def test_github_metadata_records_the_actions_run(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "FlexOr2/songmaker")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "4")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    assert MODULE._github_metadata() == {
        "repository": "FlexOr2/songmaker",
        "run_id": "123",
        "run_attempt": "4",
        "url": "https://github.com/FlexOr2/songmaker/actions/runs/123",
    }


def test_run_writes_a_failure_record_for_a_failing_pytest_claim(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    tests = project / "tests"
    tests.mkdir(parents=True)
    (project / "pyproject.toml").write_text(PYTEST_CONFIG, encoding="utf-8")
    (tests / "test_claim.py").write_text(
        source_text(
            "import pytest",
            "",
            "@pytest.mark.acceptance('ACC-DEMO-01')",
            "def test_claim():",
            "    assert False",
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "--quiet"], cwd=project, check=True)
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "test",
        ],
        cwd=project,
        check=True,
    )
    claim = AcceptanceClaim("tests/test_claim.py::test_claim", "ACC-DEMO-01")
    monkeypatch.setattr(MODULE, "load_claims", lambda _: (claim,))
    output = project / "artifacts/report.json"
    assert run(project, output) == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["overall_outcome"] == "failed"
    assert report["exit_status"] == 1
    assert report["command"][-1] == claim.nodeid
    assert report["records"] == [
        {
            "acceptance_id": "ACC-DEMO-01",
            "command": report["command"],
            "exit_status": 1,
            "nodeid": claim.nodeid,
            "outcome": "failed",
            "proof_kind": "integration",
        }
    ]


def test_run_writes_a_success_record_for_a_passing_pytest_claim(
    tmp_path: Path, monkeypatch
) -> None:
    for variable in (
        "GITHUB_ACTIONS",
        "GITHUB_REPOSITORY",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
        "GITHUB_SERVER_URL",
    ):
        monkeypatch.delenv(variable, raising=False)
    project = tmp_path / "project"
    tests = project / "tests"
    tests.mkdir(parents=True)
    (project / "pyproject.toml").write_text(PYTEST_CONFIG, encoding="utf-8")
    (tests / "test_claim.py").write_text(
        source_text(
            "import pytest",
            "",
            "@pytest.mark.acceptance('ACC-DEMO-01')",
            "def test_claim():",
            "    assert True",
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "--quiet"], cwd=project, check=True)
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "test",
        ],
        cwd=project,
        check=True,
    )
    claim = AcceptanceClaim("tests/test_claim.py::test_claim", "ACC-DEMO-01")
    monkeypatch.setattr(MODULE, "load_claims", lambda _: (claim,))
    output = project / "artifacts/report.json"
    assert run(project, output) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    assert len(report["head"]) == 40
    assert report["github"] == {
        "repository": None,
        "run_attempt": None,
        "run_id": None,
        "url": None,
    }
    assert report["overall_outcome"] == "passed"
    assert report["exit_status"] == 0
    assert report["records"][0]["acceptance_id"] == "ACC-DEMO-01"
    assert report["records"][0]["nodeid"] == claim.nodeid
    assert report["records"][0]["outcome"] == "passed"

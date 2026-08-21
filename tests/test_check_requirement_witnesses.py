from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
CHECKER = Path("scripts/check_requirement_witnesses.py")
WORKFLOW = Path(".github/workflows/requirement-witnesses.yml")


def test_empty_repository_check_needs_no_token_and_makes_no_network_request(
    tmp_path: Path,
) -> None:
    project = tmp_path / "empty-project"
    registry = project / "docs/requirements/revisions.toml"
    registry.parent.mkdir(parents=True)
    registry.write_text("schema_version = 2\n", encoding="utf-8")
    environment = os.environ.copy()
    environment.pop("GITHUB_TOKEN", None)

    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / CHECKER)],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 approval witness(es)" in result.stdout
    assert "No network request was made" in result.stdout
    assert "point-in-time" in result.stdout


def test_live_workflow_is_read_only_and_does_not_expose_a_token_to_forks() -> None:
    workflow = (PROJECT_ROOT / WORKFLOW).read_text(encoding="utf-8")

    assert "contents: read" in workflow
    assert "issues: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "pull_request_target" not in workflow
    assert "github.event.pull_request.head.repo.full_name == github.repository" in workflow
    assert "GITHUB_TOKEN: ${{ github.token }}" in workflow
    assert workflow.count("GITHUB_TOKEN:") == 1
    assert "types: [edited, deleted]" in workflow
    assert "schedule:" in workflow
    assert "timeout-minutes: 3" in workflow
    assert "timeout --signal=TERM --kill-after=5s 120s python" in workflow
    assert "python scripts/check_requirement_witnesses.py" in workflow

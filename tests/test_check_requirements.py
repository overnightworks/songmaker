from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
GATE = Path("scripts/check_requirements.py")
CONTRACT = Path("scripts/requirement_contract.py")
DOCUMENT = Path("docs/requirements/0001-albums.md")
WITNESSES = Path("docs/requirements/witnesses")
WORKFLOW = Path(".github/workflows/requirements.yml")
SPECIFICATION = importlib.util.spec_from_file_location(
    "requirement_contract", PROJECT_ROOT / CONTRACT
)
assert SPECIFICATION is not None
assert SPECIFICATION.loader is not None
CONTRACT_MODULE = importlib.util.module_from_spec(SPECIFICATION)
sys.modules[SPECIFICATION.name] = CONTRACT_MODULE
SPECIFICATION.loader.exec_module(CONTRACT_MODULE)

ACCEPTANCE_LOCATION = CONTRACT_MODULE.ACCEPTANCE_LOCATION
PRODUCT_LOCATION = CONTRACT_MODULE.PRODUCT_LOCATION
REGISTRY_LOCATION = CONTRACT_MODULE.REGISTRY_LOCATION
approval_bytes = CONTRACT_MODULE.approval_bytes
EXPECTED_OPERATOR_ID = CONTRACT_MODULE.EXPECTED_OPERATOR_ID
EXPECTED_REPOSITORY_FULL_NAME = CONTRACT_MODULE.EXPECTED_REPOSITORY_FULL_NAME
EXPECTED_REPOSITORY_ID = CONTRACT_MODULE.EXPECTED_REPOSITORY_ID
read_acceptance_manifest = CONTRACT_MODULE.read_acceptance_manifest
read_requirement_shelf = CONTRACT_MODULE.read_requirement_shelf
render_product_view = CONTRACT_MODULE.render_product_view


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def content(sentence: str = "Every song belongs to one album.") -> bytes:
    return (
        "# Albums and songs\n\n"
        "## Intent\n\nA musician organizes a coherent release.\n\n"
        f"## Rules\n\n### REQ-ALBUM-01: {sentence}\n"
        "Quelle: OPERATOR — issue 41\n"
    ).encode("utf-8")


def revision_table(
    content_digest: str,
    *,
    predecessor: str = "GENESIS",
    comment: int = 1001,
) -> str:
    witness = witness_bytes(content_digest, comment)
    return (
        "[[revision]]\n"
        'document = "0001"\n'
        f'path = "{DOCUMENT}"\n'
        f'content_sha256 = "{content_digest}"\n'
        f'witness_path = "{WITNESSES}/{comment}.json"\n'
        f'witness_sha256 = "{digest(witness)}"\n'
        f'predecessor = "{predecessor}"\n'
    )


def witness_bytes(content_digest: str, comment: int) -> bytes:
    body = approval_bytes("0001", content_digest)
    payload = {
        "schema_version": 1,
        "repository_id": EXPECTED_REPOSITORY_ID,
        "repository_full_name": EXPECTED_REPOSITORY_FULL_NAME,
        "issue_id": 2001,
        "issue_number": 41,
        "comment_id": comment,
        "author_id": EXPECTED_OPERATOR_ID,
        "created_at": "2026-08-21T12:00:00Z",
        "updated_at": "2026-08-21T12:00:00Z",
        "body_base64": base64.b64encode(body).decode("ascii"),
        "body_sha256": digest(body),
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def write_witness(project: Path, content_digest: str, comment: int) -> None:
    target = project / WITNESSES / f"{comment}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(witness_bytes(content_digest, comment))


def copied_contract(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    for relative in (GATE, CONTRACT, PRODUCT_LOCATION):
        destination = project / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT_ROOT / relative, destination)
    shutil.copytree(
        PROJECT_ROOT / REGISTRY_LOCATION.parent,
        project / REGISTRY_LOCATION.parent,
    )
    shutil.copytree(
        PROJECT_ROOT / ACCEPTANCE_LOCATION.parent,
        project / ACCEPTANCE_LOCATION.parent,
    )
    return project


def refresh_product(project: Path) -> None:
    shelf = read_requirement_shelf(project)
    acceptance = read_acceptance_manifest(project, shelf)
    (project / PRODUCT_LOCATION).write_text(
        render_product_view(shelf, acceptance), encoding="utf-8"
    )


def activate(project: Path, *, document_content: bytes | None = None) -> str:
    current = document_content or content()
    (project / DOCUMENT).write_bytes(current)
    current_digest = digest(current)
    (project / REGISTRY_LOCATION).write_text(
        "schema_version = 2\n\n" + revision_table(current_digest),
        encoding="utf-8",
    )
    write_witness(project, current_digest, 1001)
    refresh_product(project)
    return current_digest


def commit(project: Path, message: str) -> str:
    if not (project / ".git").exists():
        subprocess.run(["git", "init", "--quiet"], cwd=project, check=True)
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test-builder",
            "-c",
            "user.email=test-builder@invalid",
            "commit",
            "--quiet",
            "-m",
            message,
        ],
        cwd=project,
        check=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def run_gate(
    project: Path,
    *arguments: str,
    github_actions: bool = False,
    event: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["GITHUB_ACTIONS"] = "true" if github_actions else "false"
    if event is None:
        environment.pop("GITHUB_EVENT_NAME", None)
    else:
        environment["GITHUB_EVENT_NAME"] = event
    return subprocess.run(
        [sys.executable, str(GATE), *arguments],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_repository_contract_and_honesty_boundary_pass() -> None:
    result = run_gate(PROJECT_ROOT, "--current-only")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 document(s), 0 rule(s), 0 acceptance sentence(s)" in result.stdout
    assert "does not fetch: GitHub" in result.stdout


def test_product_view_is_exactly_derived(tmp_path: Path) -> None:
    project = copied_contract(tmp_path)
    (project / PRODUCT_LOCATION).write_text("# Handwritten status\n", encoding="utf-8")

    result = run_gate(project, "--current-only")

    assert result.returncode != 0
    assert "PRODUCT.md is stale" in result.stderr


def test_product_view_must_be_a_regular_file(tmp_path: Path) -> None:
    project = copied_contract(tmp_path)
    product = project / PRODUCT_LOCATION
    outside = tmp_path / "PRODUCT.md"
    outside.write_bytes(product.read_bytes())
    product.unlink()
    product.symlink_to(outside)

    result = run_gate(project, "--current-only")

    assert result.returncode != 0
    assert "regular non-symlink" in result.stderr


def test_documented_and_executable_honesty_bounds_cannot_drift(
    tmp_path: Path,
) -> None:
    project = copied_contract(tmp_path)
    readme = project / "docs/requirements/README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace(
            "does not fetch: GitHub or another live authority",
            "does not fetch: anything",
        ),
        encoding="utf-8",
    )

    result = run_gate(project, "--current-only")

    assert result.returncode != 0
    assert "honesty boundary differ" in result.stderr


def test_greenfield_may_add_a_first_valid_genesis_against_the_exact_base(
    tmp_path: Path,
) -> None:
    project = copied_contract(tmp_path)
    base = commit(project, "empty contract")
    activate(project)

    result = run_gate(project, "--base-revision", base)

    assert result.returncode == 0, result.stdout + result.stderr


def test_empty_schema_one_migrates_once_to_empty_schema_two(tmp_path: Path) -> None:
    project = copied_contract(tmp_path)
    registry = project / REGISTRY_LOCATION
    registry.write_text("schema_version = 1\n", encoding="utf-8")
    base = commit(project, "schema one empty contract")
    registry.write_text("schema_version = 2\n", encoding="utf-8")

    result = run_gate(project, "--base-revision", base)

    assert result.returncode == 0, result.stdout + result.stderr


def test_schema_one_migration_cannot_activate_a_revision_in_the_same_diff(
    tmp_path: Path,
) -> None:
    project = copied_contract(tmp_path)
    registry = project / REGISTRY_LOCATION
    registry.write_text("schema_version = 1\n", encoding="utf-8")
    base = commit(project, "schema one empty contract")
    activate(project)

    result = run_gate(project, "--base-revision", base)

    assert result.returncode != 0
    assert "must migrate to empty schema 2 before activation" in result.stderr


def test_a_valid_successor_appends_to_immutable_history(tmp_path: Path) -> None:
    project = copied_contract(tmp_path)
    predecessor = activate(project)
    base = commit(project, "active genesis")
    successor = content("Every saved song belongs to exactly one album.")
    successor_digest = digest(successor)
    (project / DOCUMENT).write_bytes(successor)
    with (project / REGISTRY_LOCATION).open("a", encoding="utf-8") as registry:
        registry.write(
            "\n" + revision_table(successor_digest, predecessor=predecessor, comment=1002)
        )
    write_witness(project, successor_digest, 1002)

    result = run_gate(project, "--base-revision", base)

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("mutation", ("rewrite", "delete", "restart"))
def test_existing_revision_history_cannot_be_changed_deleted_or_restarted(
    tmp_path: Path, mutation: str
) -> None:
    project = copied_contract(tmp_path)
    current_digest = activate(project)
    base = commit(project, "active genesis")
    registry = project / REGISTRY_LOCATION
    if mutation == "rewrite":
        old_witness_digest = digest(witness_bytes(current_digest, 1001))
        new_witness_digest = digest(witness_bytes(current_digest, 1002))
        registry.write_text(
            registry.read_text(encoding="utf-8").replace(
                "witnesses/1001.json", "witnesses/1002.json"
            ).replace(old_witness_digest, new_witness_digest),
            encoding="utf-8",
        )
        (project / WITNESSES / "1001.json").unlink()
        write_witness(project, current_digest, 1002)
    elif mutation == "delete":
        (project / DOCUMENT).unlink()
        (project / WITNESSES / "1001.json").unlink()
        registry.write_text("schema_version = 2\n", encoding="utf-8")
        refresh_product(project)
    else:
        replacement = content("A replacement must not restart history.")
        (project / DOCUMENT).write_bytes(replacement)
        registry.write_text(
            "schema_version = 2\n\n" + revision_table(digest(replacement), comment=1002),
            encoding="utf-8",
        )
        (project / WITNESSES / "1001.json").unlink()
        write_witness(project, digest(replacement), 1002)

    result = run_gate(project, "--base-revision", base)

    assert result.returncode != 0
    assert "changed or deleted" in result.stderr


@pytest.mark.parametrize("base", ("HEAD", "0" * 40, "A" * 40, "abc"))
def test_base_revision_must_be_exact_lowercase_and_resolvable(tmp_path: Path, base: str) -> None:
    project = copied_contract(tmp_path)
    commit(project, "empty contract")

    result = run_gate(project, "--base-revision", base)

    assert result.returncode != 0
    assert "absent or unresolvable" in result.stderr


def test_base_registry_must_be_a_regular_git_blob(tmp_path: Path) -> None:
    project = copied_contract(tmp_path)
    registry = project / REGISTRY_LOCATION
    saved = registry.read_bytes()
    outside = project / "base-registry.toml"
    outside.write_bytes(saved)
    registry.unlink()
    registry.symlink_to(outside)
    base = commit(project, "symlink registry")
    registry.unlink()
    registry.write_bytes(saved)

    result = run_gate(project, "--base-revision", base)

    assert result.returncode != 0
    assert "not a regular Git file" in result.stderr


def test_base_witness_must_be_a_regular_git_blob(tmp_path: Path) -> None:
    project = copied_contract(tmp_path)
    activate(project)
    witness = project / WITNESSES / "1001.json"
    saved = witness.read_bytes()
    outside = project / "base-witness.json"
    outside.write_bytes(saved)
    witness.unlink()
    witness.symlink_to(outside)
    base = commit(project, "symlink witness")
    witness.unlink()
    witness.write_bytes(saved)

    result = run_gate(project, "--base-revision", base)

    assert result.returncode != 0
    assert "not a regular Git file" in result.stderr


def test_pre_registry_base_cannot_hide_a_numbered_requirement(tmp_path: Path) -> None:
    project = copied_contract(tmp_path)
    registry = project / REGISTRY_LOCATION
    registry.unlink()
    (project / DOCUMENT).write_bytes(content())
    base = commit(project, "unregistered requirement")
    (project / DOCUMENT).unlink()
    registry.write_text("schema_version = 2\n", encoding="utf-8")

    result = run_gate(project, "--base-revision", base)

    assert result.returncode != 0
    assert "numbered requirements without a registry" in result.stderr


def test_every_gate_run_requires_an_explicit_history_mode(tmp_path: Path) -> None:
    result = run_gate(copied_contract(tmp_path))

    assert result.returncode == 2
    assert "one of the arguments" in result.stderr


@pytest.mark.parametrize("event", ("pull_request", "push", "schedule"))
def test_current_only_cannot_bypass_temporal_checks_in_automatic_actions(
    tmp_path: Path, event: str
) -> None:
    result = run_gate(
        copied_contract(tmp_path),
        "--current-only",
        github_actions=True,
        event=event,
    )

    assert result.returncode != 0
    assert "only for workflow_dispatch" in result.stderr


def test_workflow_dispatch_may_explicitly_check_only_the_current_snapshot(
    tmp_path: Path,
) -> None:
    result = run_gate(
        copied_contract(tmp_path),
        "--current-only",
        github_actions=True,
        event="workflow_dispatch",
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_base_and_current_only_modes_are_mutually_exclusive(tmp_path: Path) -> None:
    result = run_gate(
        copied_contract(tmp_path),
        "--base-revision",
        "0" * 40,
        "--current-only",
    )

    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr


def test_exact_base_verification_refuses_a_shallow_repository(tmp_path: Path) -> None:
    source = copied_contract(tmp_path)
    commit(source, "first")
    (source / "marker.txt").write_text("second\n", encoding="utf-8")
    commit(source, "second")
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", f"file://{source}", str(shallow)],
        check=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=shallow,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    result = run_gate(shallow, "--base-revision", head)

    assert result.returncode != 0
    assert "shallow repository" in result.stderr


def test_workflow_wires_each_event_to_the_only_allowed_history_mode() -> None:
    workflow = (PROJECT_ROOT / WORKFLOW).read_text(encoding="utf-8")

    assert "fetch-depth: 0" in workflow
    assert "persist-credentials: false" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "if: github.event_name == 'pull_request'" in workflow
    assert "${{ github.event.pull_request.base.sha }}" in workflow
    assert "if: github.event_name == 'push'" in workflow
    assert "${{ github.event.before }}" in workflow
    assert "if: github.event_name == 'workflow_dispatch'" in workflow
    assert "python scripts/check_requirements.py --current-only" in workflow

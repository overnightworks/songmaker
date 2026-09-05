from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from requirement_contract import AcceptanceEntry, read_acceptance_manifest, read_requirement_shelf

TESTS_DIRECTORY = Path("tests")
REPORT_SCHEMA_VERSION = 1
PYTEST_COMMAND = (sys.executable, "-m", "pytest", "-n", "0", "-q", "--strict-markers")


class AcceptanceEvidenceError(Exception):
    pass


class KnownClaimsError(AcceptanceEvidenceError):
    def __init__(self, error: Exception, claims: tuple[AcceptanceClaim, ...]) -> None:
        super().__init__(str(error))
        self.claims = claims


class ClaimsExecutionError(AcceptanceEvidenceError):
    def __init__(
        self, error: Exception, records: list[dict[str, object]], commands: list[str]
    ) -> None:
        super().__init__(str(error))
        self.records = records
        self.commands = commands


@dataclass(frozen=True, slots=True)
class AcceptanceClaim:
    nodeid: str
    acceptance_id: str
    proof_kind: str = "integration"


def collect_claims(project_root: Path) -> tuple[AcceptanceClaim, ...]:
    tests_directory = project_root / TESTS_DIRECTORY
    if not tests_directory.is_dir() or tests_directory.is_symlink():
        raise AcceptanceEvidenceError(f"{TESTS_DIRECTORY} must be a regular directory")
    claims: list[AcceptanceClaim] = []
    claimed_ids: set[str] = set()
    for source in sorted(tests_directory.rglob("*.py")):
        try:
            if not source.is_file() or source.is_symlink():
                raise AcceptanceEvidenceError(
                    f"{source.relative_to(project_root)} must be a regular file"
                )
            try:
                tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            except (OSError, UnicodeDecodeError, SyntaxError) as error:
                raise AcceptanceEvidenceError(
                    f"cannot parse {source.relative_to(project_root)}"
                ) from error
            _claims_from_module(project_root, source, tree, claimed_ids, claims)
        except AcceptanceEvidenceError as error:
            raise KnownClaimsError(error, tuple(claims)) from error
    return tuple(claims)


def validate_claims(
    claims: tuple[AcceptanceClaim, ...], acceptances: tuple[AcceptanceEntry, ...]
) -> tuple[AcceptanceClaim, ...]:
    entries = {entry.identifier: entry for entry in acceptances}
    claim_ids: set[str] = set()
    for claim in claims:
        if claim.acceptance_id in claim_ids:
            raise AcceptanceEvidenceError(
                f"acceptance {claim.acceptance_id} has duplicate test claims"
            )
        claim_ids.add(claim.acceptance_id)
    for entry in acceptances:
        if entry.proof_kind != "integration":
            raise AcceptanceEvidenceError(
                f"acceptance {entry.identifier} has unsupported proof_kind {entry.proof_kind!r}"
            )
    claimed_ids = {claim.acceptance_id for claim in claims}
    for claim in claims:
        if claim.acceptance_id not in entries:
            raise AcceptanceEvidenceError(
                f"test {claim.nodeid} claims unknown acceptance {claim.acceptance_id}"
            )
    for entry in acceptances:
        if entry.critical and entry.identifier not in claimed_ids:
            raise AcceptanceEvidenceError(
                f"critical integration acceptance {entry.identifier} has no test claim"
            )
    return tuple(
        AcceptanceClaim(claim.nodeid, claim.acceptance_id, entries[claim.acceptance_id].proof_kind)
        for claim in claims
    )


def load_claims(project_root: Path) -> tuple[AcceptanceClaim, ...]:
    claims = collect_claims(project_root)
    acceptances: tuple[AcceptanceEntry, ...] = ()
    try:
        shelf = read_requirement_shelf(project_root)
        acceptances = read_acceptance_manifest(project_root, shelf)
        return validate_claims(claims, acceptances)
    except Exception as error:
        raise KnownClaimsError(error, _claims_with_proof_kinds(claims, acceptances)) from error


def run_claims(
    project_root: Path, claims: tuple[AcceptanceClaim, ...]
) -> tuple[list[dict[str, object]], int, list[str]]:
    records: list[dict[str, object]] = []
    commands: list[str] = []
    exit_status = 0
    for index, claim in enumerate(claims):
        command = [*PYTEST_COMMAND, claim.nodeid]
        commands.extend(command)
        try:
            result = subprocess.run(command, cwd=project_root, check=False)
        except Exception as error:
            records.extend(_not_run_records(claims[index:]))
            raise ClaimsExecutionError(error, records, commands) from error
        records.append(
            {
                "nodeid": claim.nodeid,
                "acceptance_id": claim.acceptance_id,
                "proof_kind": claim.proof_kind,
                "outcome": "passed" if result.returncode == 0 else "failed",
                "command": command,
                "exit_status": result.returncode,
            }
        )
        if result.returncode != 0 and exit_status == 0:
            exit_status = result.returncode
    return records, exit_status, commands


def run(project_root: Path, output: Path) -> int:
    report = _report_envelope(project_root)
    exit_status = 2
    try:
        claims = load_claims(project_root)
        records, exit_status, command = run_claims(project_root, claims)
        report["records"] = records
        report["command"] = command
    except KnownClaimsError as error:
        report["records"] = _not_run_records(error.claims)
        report["error"] = str(error)
        report["command"] = ["acceptance-evidence", "check"]
    except ClaimsExecutionError as error:
        report["records"] = error.records
        report["error"] = str(error)
        report["command"] = error.commands
    except Exception as error:
        report["error"] = str(error)
        report["command"] = ["acceptance-evidence", "check"]
    report["exit_status"] = exit_status
    report["overall_outcome"] = "passed" if exit_status == 0 else "failed"
    _write_report(output, report)
    return exit_status


def _claims_from_module(
    project_root: Path,
    source: Path,
    tree: ast.Module,
    claimed_ids: set[str],
    claims: list[AcceptanceClaim],
) -> None:
    accepted_attributes: set[int] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        markers = [
            decorator for decorator in node.decorator_list if _looks_like_acceptance(decorator)
        ]
        if not markers:
            continue
        location = f"{source.relative_to(project_root)}:{node.lineno}"
        if not node.name.startswith("test_"):
            raise AcceptanceEvidenceError(f"{location} acceptance marker is not on test_*")
        if len(markers) != 1:
            raise AcceptanceEvidenceError(f"{location} has duplicate acceptance markers")
        marker = markers[0]
        if not _is_direct_marker(marker):
            raise AcceptanceEvidenceError(f"{location} acceptance marker must be direct")
        assert isinstance(marker, ast.Call)
        if len(marker.args) != 1 or marker.keywords:
            raise AcceptanceEvidenceError(f"{location} acceptance marker needs one literal ID")
        argument = marker.args[0]
        if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
            raise AcceptanceEvidenceError(f"{location} acceptance marker ID must be literal")
        identifier = argument.value
        if identifier in claimed_ids:
            raise AcceptanceEvidenceError(f"acceptance {identifier} has duplicate test claims")
        claimed_ids.add(identifier)
        accepted_attributes.add(id(marker.func))
        relative = source.relative_to(project_root).as_posix()
        claims.append(AcceptanceClaim(f"{relative}::{node.name}", identifier))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "acceptance"
            and id(node) not in accepted_attributes
        ):
            location = f"{source.relative_to(project_root)}:{node.lineno}"
            raise AcceptanceEvidenceError(f"{location} acceptance marker is not direct top-level")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "acceptance"
        ):
            location = f"{source.relative_to(project_root)}:{node.lineno}"
            raise AcceptanceEvidenceError(f"{location} acceptance marker is not direct top-level")
def _claims_with_proof_kinds(
    claims: tuple[AcceptanceClaim, ...], acceptances: tuple[AcceptanceEntry, ...]
) -> tuple[AcceptanceClaim, ...]:
    proof_kinds = {entry.identifier: entry.proof_kind for entry in acceptances}
    return tuple(
        AcceptanceClaim(
            claim.nodeid,
            claim.acceptance_id,
            proof_kinds.get(claim.acceptance_id, claim.proof_kind),
        )
        for claim in claims
    )


def _not_run_records(claims: tuple[AcceptanceClaim, ...]) -> list[dict[str, object]]:
    return [
        {
            "nodeid": claim.nodeid,
            "acceptance_id": claim.acceptance_id,
            "proof_kind": claim.proof_kind,
            "outcome": "not_run",
            "command": [*PYTEST_COMMAND, claim.nodeid],
            "exit_status": None,
        }
        for claim in sorted(
            claims, key=lambda claim: (claim.nodeid, claim.acceptance_id, claim.proof_kind)
        )
    ]


def _looks_like_acceptance(expression: ast.expr) -> bool:
    target = expression.func if isinstance(expression, ast.Call) else expression
    return (
        isinstance(target, ast.Attribute)
        and target.attr == "acceptance"
        or (isinstance(target, ast.Name) and target.id == "acceptance")
    )


def _is_direct_marker(expression: ast.expr) -> bool:
    if not isinstance(expression, ast.Call) or not isinstance(expression.func, ast.Attribute):
        return False
    marker = expression.func
    if marker.attr != "acceptance" or not isinstance(marker.value, ast.Attribute):
        return False
    return (
        marker.value.attr == "mark"
        and isinstance(marker.value.value, ast.Name)
        and marker.value.value.id == "pytest"
    )


def _report_envelope(project_root: Path) -> dict[str, Any]:
    try:
        head = _checked_out_head(project_root)
    except Exception as error:
        head = None
        error_text: str | None = str(error)
    else:
        error_text = None
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "head": head,
        "github": _github_metadata(),
        "command": [],
        "exit_status": None,
        "overall_outcome": "failed",
        "records": [],
        "error": error_text,
    }


def _checked_out_head(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    head = result.stdout.strip()
    if result.returncode != 0 or len(head) != 40:
        raise AcceptanceEvidenceError("cannot determine checked-out HEAD")
    return head


def _github_metadata() -> dict[str, object | None]:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return {"repository": None, "run_id": None, "run_attempt": None, "url": None}
    repository = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT")
    server_url = os.environ.get("GITHUB_SERVER_URL")
    url = (
        f"{server_url}/{repository}/actions/runs/{run_id}"
        if all((server_url, repository, run_id))
        else None
    )
    return {"repository": repository, "run_id": run_id, "run_attempt": run_attempt, "url": url}


def _write_report(output: Path, report: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(
        json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)  # NOSONAR CLI-only output path.


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="check and run acceptance evidence")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="validate the acceptance evidence claims")
    run_parser = commands.add_parser("run", help="validate claims, run them, and write a report")
    run_parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    project_root = Path.cwd()
    if arguments.command == "check":
        try:
            claims = load_claims(project_root)
        except Exception as error:
            print(f"acceptance evidence check failed: {error}", file=sys.stderr)
            return 2
        print(f"acceptance evidence check passed: {len(claims)} claim(s)")
        return 0
    return run(project_root, arguments.output)


if __name__ == "__main__":
    raise SystemExit(main())

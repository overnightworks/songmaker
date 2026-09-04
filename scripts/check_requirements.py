from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from requirement_contract import (
    DOCUMENT_NAME,
    PRODUCT_LOCATION,
    REGISTRY_LOCATION,
    REQUIREMENTS_DIRECTORY,
    RegistrySnapshot,
    RequirementContractError,
    read_acceptance_manifest,
    read_registry_snapshot,
    read_requirement_shelf,
    render_product_view,
)

EXACT_GIT_SHA = re.compile(r"[0-9a-f]{40}")
HONESTY_BOUND = (
    "```text",
    "proves: every numbered requirement is a regular UTF-8 file whose exact bytes "
    "match its sole active registry tip",
    "proves: every revision lineage is predecessor-complete, unbranched, and has "
    "exactly one tip on one fixed path",
    "proves: with an exact VCS base, existing revision fields cannot be changed, "
    "deleted, or restarted",
    "proves: every revision points to exact offline witness bytes for its approval line",
    "proves: every acceptance edge names an active requirement rule",
    "proves: PRODUCT is the exact derived count view of the current offline contract",
    "does not prove: that a configured approval comment still exists or remains unedited on GitHub",
    "does not prove: that the GitHub account action came from a human",
    "does not prove: that an acceptance sentence is meaningful or that any test ran",
    "does not fetch: GitHub or another live authority",
    "```",
)


def render_honesty_bound() -> str:
    return "\n".join(HONESTY_BOUND)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--base-revision")
    mode.add_argument("--current-only", action="store_true")
    return parser.parse_args()


def _git(project_root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # NOSONAR: fixed executable; callers provide shell-free Git argv
        ["git", *arguments], cwd=project_root, check=False, capture_output=True
    )


def _git_bytes(project_root: Path, *arguments: str) -> bytes:
    result = _git(project_root, *arguments)
    if result.returncode != 0:
        raise RequirementContractError(f"exact base revision cannot supply {' '.join(arguments)}")
    return result.stdout


def _git_object_exists(project_root: Path, object_name: str) -> bool:
    return _git(project_root, "cat-file", "-e", object_name).returncode == 0


def _git_regular_file(project_root: Path, base_revision: str, location: Path) -> bytes:
    listing = _git_bytes(project_root, "ls-tree", "-z", base_revision, "--", location.as_posix())
    records = [record for record in listing.split(b"\0") if record]
    try:
        metadata, raw_location = records[0].split(b"\t", 1)
        mode, kind, _object = metadata.decode("ascii").split()
        exact_location = raw_location.decode("utf-8") == location.as_posix()
    except (IndexError, UnicodeDecodeError, ValueError) as error:
        raise RequirementContractError(
            f"{location} is not a regular Git file in exact base {base_revision}"
        ) from error
    if (
        len(records) != 1
        or mode not in {"100644", "100755"}
        or kind != "blob"
        or not exact_location
    ):
        raise RequirementContractError(
            f"{location} is not a regular Git file in exact base {base_revision}"
        )
    return _git_bytes(project_root, "show", f"{base_revision}:{location.as_posix()}")


def _base_snapshot(project_root: Path, base_revision: str) -> RegistrySnapshot:
    registry_object = f"{base_revision}:{REGISTRY_LOCATION.as_posix()}"
    if not _git_object_exists(project_root, registry_object):
        listing = _git_bytes(
            project_root,
            "ls-tree",
            "-r",
            "--name-only",
            "-z",
            base_revision,
            "--",
            REQUIREMENTS_DIRECTORY.as_posix(),
        )
        try:
            locations = [
                Path(raw.decode("utf-8")) for raw in listing.rstrip(b"\0").split(b"\0") if raw
            ]
        except UnicodeDecodeError as error:
            raise RequirementContractError(
                f"exact base {base_revision} has non-UTF-8 requirement paths"
            ) from error
        numbered = [path for path in locations if DOCUMENT_NAME.fullmatch(path.name)]
        if numbered:
            raise RequirementContractError(
                f"exact base {base_revision} has numbered requirements without a registry"
            )
        return RegistrySnapshot(0, ())
    with tempfile.TemporaryDirectory() as temporary:
        base_root = Path(temporary)
        registry = base_root / REGISTRY_LOCATION
        registry.parent.mkdir(parents=True)
        registry.write_bytes(_git_regular_file(project_root, base_revision, REGISTRY_LOCATION))
        snapshot = read_registry_snapshot(base_root, allow_empty_schema_one=True)
    for revision in snapshot.revisions:
        _git_regular_file(project_root, base_revision, revision.location)
        _git_regular_file(project_root, base_revision, revision.witness_location)
    return snapshot


def verify_temporal_history(project_root: Path, base_revision: str) -> None:
    if EXACT_GIT_SHA.fullmatch(base_revision) is None or not _git_object_exists(
        project_root, f"{base_revision}^{{commit}}"
    ):
        raise RequirementContractError(
            f"exact base revision {base_revision!r} is absent or unresolvable"
        )
    shallow = _git_bytes(project_root, "rev-parse", "--is-shallow-repository")
    if shallow.strip() == b"true":
        raise RequirementContractError("exact base verification refuses a shallow repository")
    base = _base_snapshot(project_root, base_revision)
    current = read_registry_snapshot(project_root)
    if base.schema_version == 1:
        if current.revisions:
            raise RequirementContractError(
                "empty registry schema 1 must migrate to empty schema 2 before activation"
            )
        return
    if base.schema_version not in {0, current.schema_version}:
        raise RequirementContractError(
            f"registry schema changed from {base.schema_version} to {current.schema_version}"
        )
    for revision in base.revisions:
        if revision not in current.revisions:
            raise RequirementContractError(
                f"revision {revision.document} {revision.content_sha256} changed or deleted"
            )


def verify_current_contract(project_root: Path) -> tuple[int, int, int]:
    shelf = read_requirement_shelf(project_root)
    acceptance = read_acceptance_manifest(project_root, shelf)
    expected_product = render_product_view(shelf, acceptance).encode("utf-8")
    if _current_regular_bytes(project_root, PRODUCT_LOCATION) != expected_product:
        raise RequirementContractError(
            f"{PRODUCT_LOCATION} is stale; regenerate it from the offline contract"
        )
    documentation_location = REQUIREMENTS_DIRECTORY / "README.md"
    bound_start = "<!-- requirement-gate-bound:start -->"
    bound_end = "<!-- requirement-gate-bound:end -->"
    text = _current_regular_bytes(project_root, documentation_location).decode("utf-8")
    try:
        documented = text.split(bound_start, 1)[1].split(bound_end, 1)[0].strip()
    except IndexError as error:
        raise RequirementContractError(
            "requirements documentation omits the gate honesty boundary"
        ) from error
    if documented != render_honesty_bound():
        raise RequirementContractError(
            "requirements documentation and executable honesty boundary differ"
        )
    return shelf.document_count, len(shelf.rules), len(acceptance)


def _current_regular_bytes(project_root: Path, location: Path) -> bytes:
    root = project_root.resolve()
    parent = root / location.parent
    target = root / location
    if (
        parent.is_symlink()
        or not parent.is_dir()
        or target.is_symlink()
        or not target.is_file()
        or target.parent != parent
    ):
        raise RequirementContractError(f"{location} is not a regular non-symlink file")
    return target.read_bytes()


def _validate_mode(arguments: argparse.Namespace) -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    event = os.environ.get("GITHUB_EVENT_NAME")
    if arguments.current_only:
        if event != "workflow_dispatch":
            raise RequirementContractError(
                "--current-only is allowed in GitHub Actions only for workflow_dispatch"
            )


def main() -> int:
    arguments = _arguments()
    try:
        _validate_mode(arguments)
        documents, rules, acceptance = verify_current_contract(Path.cwd())
        if arguments.base_revision is not None:
            verify_temporal_history(Path.cwd(), arguments.base_revision)
    except (RequirementContractError, UnicodeDecodeError) as error:
        print(f"Requirement gate refused: {error}", file=sys.stderr)
        return 1
    print(
        f"Requirement contract: {documents} document(s), {rules} rule(s), "
        f"{acceptance} acceptance sentence(s)"
    )
    print(render_honesty_bound())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import fcntl
import hashlib
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_requirements as gate  # noqa: E402
import requirement_binder as binder  # noqa: E402
import requirement_contract as contract  # noqa: E402
import requirement_witness as live  # noqa: E402

CANDIDATE = Path("docs/requirements/0001-albums.md")


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def candidate_bytes(sentence: str = "Every song belongs to one album.") -> bytes:
    return (
        "# Albums and songs\n\n"
        "## Intent\n\nA musician organizes a coherent release.\n\n"
        f"## Rules\n\n### REQ-ALBUM-01: {sentence}\n"
        "Quelle: OPERATOR — issue 41\n"
    ).encode()


def git(project: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["/usr/bin/git", *arguments],
        cwd=project,
        check=True,
        capture_output=True,
    )


def commit(project: Path, message: str) -> str:
    git(project, "add", ".")
    subprocess.run(
        [
            "/usr/bin/git",
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
    return git(project, "rev-parse", "HEAD").stdout.decode().strip()


def project_with_empty_contract(tmp_path: Path) -> tuple[Path, str]:
    project = tmp_path / "project"
    requirements = project / contract.REQUIREMENTS_DIRECTORY
    requirements.mkdir(parents=True)
    shutil.copy2(
        PROJECT_ROOT / "docs/requirements/README.md",
        requirements / "README.md",
    )
    (project / contract.REGISTRY_LOCATION).write_text(
        "schema_version = 2\n",
        encoding="utf-8",
    )
    acceptance = project / contract.ACCEPTANCE_LOCATION
    acceptance.parent.mkdir(parents=True)
    acceptance.write_text("schema_version = 1\n", encoding="utf-8")
    shelf = contract.read_requirement_shelf(project)
    acceptance_entries = contract.read_acceptance_manifest(project, shelf)
    product = project / contract.PRODUCT_LOCATION
    product.write_text(
        contract.render_product_view(shelf, acceptance_entries),
        encoding="utf-8",
    )
    git(project, "init", "--quiet")
    base = commit(project, "empty contract")
    return project, base


class FakeClient:
    def __init__(
        self,
        document: str,
        content_digest: str,
        *,
        issue_number: int = 41,
        comment_id: int = 1001,
    ) -> None:
        self.document = document
        self.content_digest = content_digest
        self.issue_number = issue_number
        self.comment_id = comment_id
        self.calls: list[tuple[str, int | None]] = []

    def repository(self, _deadline: float) -> dict[str, Any]:
        self.calls.append(("repository", None))
        return {
            "id": contract.EXPECTED_REPOSITORY_ID,
            "full_name": contract.EXPECTED_REPOSITORY_FULL_NAME,
            "url": f"https://api.github.com/repos/{contract.EXPECTED_REPOSITORY_FULL_NAME}",
            "html_url": f"https://github.com/{contract.EXPECTED_REPOSITORY_FULL_NAME}",
        }

    def issue(self, issue_number: int, _deadline: float) -> dict[str, Any]:
        self.calls.append(("issue", issue_number))
        return {
            "id": 2001,
            "number": self.issue_number,
            "repository_url": f"https://api.github.com/repos/{contract.EXPECTED_REPOSITORY_FULL_NAME}",
            "url": f"https://api.github.com/repos/{contract.EXPECTED_REPOSITORY_FULL_NAME}/issues/{self.issue_number}",
            "html_url": f"https://github.com/{contract.EXPECTED_REPOSITORY_FULL_NAME}/issues/{self.issue_number}",
        }

    def comment(self, comment_id: int, _deadline: float) -> dict[str, Any]:
        self.calls.append(("comment", comment_id))
        body = contract.approval_bytes(self.document, self.content_digest).decode("ascii")
        return {
            "id": self.comment_id,
            "user": {"id": contract.EXPECTED_OPERATOR_ID},
            "issue_url": (
                f"https://api.github.com/repos/{contract.EXPECTED_REPOSITORY_FULL_NAME}/issues/{self.issue_number}"
            ),
            "url": (
                f"https://api.github.com/repos/{contract.EXPECTED_REPOSITORY_FULL_NAME}/issues/comments/"
                f"{self.comment_id}"
            ),
            "html_url": (
                f"https://github.com/{contract.EXPECTED_REPOSITORY_FULL_NAME}/issues/{self.issue_number}"
                f"#issuecomment-{self.comment_id}"
            ),
            "body": body,
            "created_at": "2026-08-21T12:00:00Z",
            "updated_at": "2026-08-21T12:00:00Z",
        }


def prepare_genesis(tmp_path: Path) -> tuple[Path, str, bytes, FakeClient]:
    project, base = project_with_empty_contract(tmp_path)
    content = candidate_bytes()
    (project / CANDIDATE).write_bytes(content)
    return project, base, content, FakeClient("0001", digest(content))


def bind_genesis(project: Path, client: FakeClient) -> binder.BindingResult:
    return binder.bind_requirement_revision(project, str(CANDIDATE), 41, 1001, client)


def test_genesis_binding_prepares_one_complete_reviewable_delta(tmp_path: Path) -> None:
    project, base, content, client = prepare_genesis(tmp_path)
    registry_mode = stat.S_IMODE((project / contract.REGISTRY_LOCATION).stat().st_mode)
    product_mode = stat.S_IMODE((project / contract.PRODUCT_LOCATION).stat().st_mode)

    result = bind_genesis(project, client)

    assert result.document == "0001"
    assert result.content_sha256 == digest(content)
    assert result.head == base
    assert client.calls == [("repository", None), ("issue", 41), ("comment", 1001)]
    assert result.witness_location == Path("docs/requirements/witnesses/1001.json")
    assert stat.S_IMODE((project / result.witness_location).stat().st_mode) == 0o644
    assert stat.S_IMODE((project / contract.REGISTRY_LOCATION).stat().st_mode) == registry_mode
    assert stat.S_IMODE((project / contract.PRODUCT_LOCATION).stat().st_mode) == product_mode
    shelf = contract.read_requirement_shelf(project)
    assert shelf.document_count == 1
    assert shelf.revision_count == 1
    assert shelf.rules[0].identifier == "REQ-ALBUM-01"
    gate.verify_current_contract(project)
    gate.verify_temporal_history(project, base)
    status = git(project, "status", "--porcelain=v2", "-z").stdout
    assert b".requirement-bind-" not in status
    assert binder._status(binder.GitRunner(project)) == {
        CANDIDATE: "?",
        contract.REGISTRY_LOCATION: ".M",
        contract.PRODUCT_LOCATION: ".M",
        Path("docs/requirements/witnesses/1001.json"): "?",
    }


def test_prepared_callback_runs_before_the_binder_lock_is_released(
    tmp_path: Path,
) -> None:
    project, _base, _content, client = prepare_genesis(tmp_path)
    observed: list[str] = []

    def report(result: binder.BindingResult) -> None:
        git_directory = Path(
            git(project, "rev-parse", "--git-dir").stdout.decode().strip()
        )
        if not git_directory.is_absolute():
            git_directory = project / git_directory
        descriptor = os.open(
            git_directory / "songmaker-requirement-bind.lock", os.O_RDWR
        )
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
        observed.append(result.document)

    binder.bind_requirement_revision(
        project,
        str(CANDIDATE),
        41,
        1001,
        client,
        on_prepared=report,
    )

    assert observed == ["0001"]


def test_successor_derives_the_only_predecessor(tmp_path: Path) -> None:
    project, _base, first, client = prepare_genesis(tmp_path)
    bind_genesis(project, client)
    commit(project, "approved genesis")
    second = candidate_bytes("Every saved song belongs to exactly one album.")
    (project / CANDIDATE).write_bytes(second)

    binder.bind_requirement_revision(
        project,
        str(CANDIDATE),
        41,
        1002,
        FakeClient("0001", digest(second), comment_id=1002),
    )

    revisions = contract.read_registry_snapshot(project).revisions
    assert len(revisions) == 2
    assert revisions[-1].predecessor == digest(first)
    assert revisions[-1].content_sha256 == digest(second)


@pytest.mark.parametrize(
    "stage", ("after_witness", "after_registry", "after_product", "before_final_state")
)
def test_every_transaction_failure_rolls_back_to_candidate_only(
    tmp_path: Path, stage: str
) -> None:
    project, _base, _content, client = prepare_genesis(tmp_path)
    registry = (project / contract.REGISTRY_LOCATION).read_bytes()
    product = (project / contract.PRODUCT_LOCATION).read_bytes()

    def fail(selected: str) -> None:
        if selected == stage:
            raise RuntimeError("injected transaction failure")

    with pytest.raises(binder.RequirementBinderError, match="transaction failed"):
        binder.bind_requirement_revision(
            project, str(CANDIDATE), 41, 1001, client, hook=fail
        )

    assert (project / contract.REGISTRY_LOCATION).read_bytes() == registry
    assert (project / contract.PRODUCT_LOCATION).read_bytes() == product
    assert not (project / "docs/requirements/witnesses").exists()
    assert git(project, "status", "--porcelain=v2").stdout.decode().splitlines() == [
        f"? {CANDIDATE}"
    ]


def test_candidate_mutation_during_remote_capture_is_refused_before_write(
    tmp_path: Path,
) -> None:
    project, _base, _content, client = prepare_genesis(tmp_path)

    def mutate(stage: str) -> None:
        if stage == "after_capture":
            (project / CANDIDATE).write_bytes(candidate_bytes("Changed during capture."))

    with pytest.raises(binder.RequirementBinderError, match="changed during live"):
        binder.bind_requirement_revision(
            project, str(CANDIDATE), 41, 1001, client, hook=mutate
        )

    assert not (project / "docs/requirements/witnesses").exists()
    assert (project / contract.REGISTRY_LOCATION).read_text() == "schema_version = 2\n"


@pytest.mark.parametrize(
    "mutation", ("extra", "staged", "intent", "deleted", "renamed")
)
def test_git_state_allows_only_one_unstaged_candidate(
    tmp_path: Path, mutation: str
) -> None:
    project, _base, content, client = prepare_genesis(tmp_path)
    active_client = client
    if mutation == "extra":
        (project / "extra.txt").write_text("extra\n")
    elif mutation == "staged":
        git(project, "add", str(CANDIDATE))
    elif mutation == "intent":
        git(project, "add", "--intent-to-add", str(CANDIDATE))
    else:
        bind_genesis(project, client)
        commit(project, "approved genesis")
        active_client = FakeClient("0001", digest(content), comment_id=1002)
        if mutation == "deleted":
            (project / CANDIDATE).unlink()
        else:
            (project / CANDIDATE).rename(project / CANDIDATE.with_name("0001-renamed.md"))
    with pytest.raises(binder.RequirementBinderError):
        binder.bind_requirement_revision(
            project,
            str(CANDIDATE),
            41,
            active_client.comment_id,
            active_client,
        )

    if mutation in {"extra", "staged", "intent"}:
        assert active_client.calls == []


@pytest.mark.parametrize(
    "path",
    (
        "docs/requirements/../0001-albums.md",
        "docs/requirements/0001-Album.md",
        "docs/requirements/0001-bad name.md",
        "/docs/requirements/0001-albums.md",
    ),
)
def test_binder_candidate_path_is_a_safe_writer_subset(tmp_path: Path, path: str) -> None:
    project, _base, content, _client = prepare_genesis(tmp_path)
    client = FakeClient("0001", digest(content))

    with pytest.raises(binder.RequirementBinderError, match="safe requirement subset"):
        binder.bind_requirement_revision(project, path, 41, 1001, client)


def test_git_children_never_receive_the_github_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, _base, _content, client = prepare_genesis(tmp_path)
    original = binder.subprocess.Popen
    environments: list[dict[str, str] | None] = []

    def recording_popen(*args: Any, **kwargs: Any):
        environments.append(kwargs.get("env"))
        return original(*args, **kwargs)

    monkeypatch.setenv("GITHUB_TOKEN", "must-not-reach-git")
    monkeypatch.setattr(binder.subprocess, "Popen", recording_popen)

    bind_genesis(project, client)

    assert environments
    assert all(environment is not None for environment in environments)
    assert all("GITHUB_TOKEN" not in environment for environment in environments if environment)
    assert all(environment == binder.GIT_ENVIRONMENT for environment in environments)
    assert binder.GIT_ENVIRONMENT["GIT_NO_LAZY_FETCH"] == "1"
    assert binder.GIT_ENVIRONMENT["GIT_NO_REPLACE_OBJECTS"] == "1"


@pytest.mark.parametrize("flag", ("--assume-unchanged", "--skip-worktree"))
def test_index_visibility_flags_are_refused_before_network(
    tmp_path: Path, flag: str
) -> None:
    project, _base, _content, client = prepare_genesis(tmp_path)
    git(project, "update-index", flag, contract.PRODUCT_LOCATION.as_posix())

    with pytest.raises(binder.RequirementBinderError, match="ordinary tracked entries"):
        bind_genesis(project, client)

    assert client.calls == []


def test_final_gate_refuses_last_second_index_changes_without_overwriting_them(
    tmp_path: Path,
) -> None:
    project, _base, _content, client = prepare_genesis(tmp_path)

    def stage_candidate(stage: str) -> None:
        if stage == "before_final_state":
            git(project, "add", str(CANDIDATE))

    with pytest.raises(binder.RequirementBinderRecoveryError, match="recovery refused"):
        binder.bind_requirement_revision(
            project, str(CANDIDATE), 41, 1001, client, hook=stage_candidate
        )

    assert git(project, "diff", "--cached", "--name-only").stdout.decode().strip() == str(
        CANDIDATE
    )
    assert (project / contract.REGISTRY_LOCATION).read_text() == "schema_version = 2\n"
    assert not (project / "docs/requirements/witnesses/1001.json").exists()


@pytest.mark.parametrize("mutation", ("symlink", "oversized", "grammar"))
def test_candidate_must_be_a_bounded_regular_strict_document(
    tmp_path: Path, mutation: str
) -> None:
    project, _base, content, client = prepare_genesis(tmp_path)
    candidate = project / CANDIDATE
    if mutation == "symlink":
        outside = tmp_path / "outside.md"
        outside.write_bytes(content)
        candidate.unlink()
        candidate.symlink_to(outside)
        problem = "regular non-symlink"
    elif mutation == "oversized":
        candidate.write_bytes(b"# Too large\n" + b"x" * contract.MAX_REQUIREMENT_BYTES)
        problem = "byte limit"
    else:
        candidate.write_text("# Missing strict sections\n")
        problem = "invalid sections"

    errors = (binder.RequirementBinderError, contract.RequirementContractError)
    with pytest.raises(errors, match=problem):
        bind_genesis(project, client)

    assert client.calls == []


def test_used_comment_id_is_refused_before_network(tmp_path: Path) -> None:
    project, _base, _first, client = prepare_genesis(tmp_path)
    bind_genesis(project, client)
    commit(project, "approved genesis")
    second = candidate_bytes("A successor needs a fresh approval comment.")
    (project / CANDIDATE).write_bytes(second)
    next_client = FakeClient("0001", digest(second))

    with pytest.raises(binder.RequirementBinderError, match="already exists"):
        binder.bind_requirement_revision(
            project, str(CANDIDATE), 41, 1001, next_client
        )

    assert next_client.calls == []


def test_concurrent_binder_lock_fails_before_network(tmp_path: Path) -> None:
    project, _base, _content, client = prepare_genesis(tmp_path)
    git_directory = Path(git(project, "rev-parse", "--git-dir").stdout.decode().strip())
    if not git_directory.is_absolute():
        git_directory = project / git_directory
    descriptor = os.open(git_directory / "songmaker-requirement-bind.lock", os.O_RDWR | os.O_CREAT)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(binder.RequirementBinderError, match="another requirement binder"):
            bind_genesis(project, client)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    assert client.calls == []


def test_binder_lock_never_follows_a_symlink(tmp_path: Path) -> None:
    project, _base, _content, client = prepare_genesis(tmp_path)
    git_directory = Path(git(project, "rev-parse", "--git-dir").stdout.decode().strip())
    if not git_directory.is_absolute():
        git_directory = project / git_directory
    foreign = tmp_path / "foreign-lock-target"
    foreign.write_bytes(b"preserve me\n")
    (git_directory / "songmaker-requirement-bind.lock").symlink_to(foreign)

    with pytest.raises(binder.RequirementBinderError, match="lock is unavailable"):
        bind_genesis(project, client)

    assert foreign.read_bytes() == b"preserve me\n"
    assert client.calls == []


def test_atomic_witness_collision_never_overwrites_foreign_bytes(tmp_path: Path) -> None:
    project, _base, _content, client = prepare_genesis(tmp_path)
    foreign = b"foreign concurrent bytes\n"

    def collide(stage: str) -> None:
        if stage == "before_witness_link":
            target = project / "docs/requirements/witnesses/1001.json"
            target.write_bytes(foreign)

    with pytest.raises(binder.RequirementBinderRecoveryError, match="recovery refused"):
        binder.bind_requirement_revision(
            project, str(CANDIDATE), 41, 1001, client, hook=collide
        )

    assert (project / "docs/requirements/witnesses/1001.json").read_bytes() == foreign
    assert (project / contract.REGISTRY_LOCATION).read_text() == "schema_version = 2\n"


def test_identical_foreign_witness_collision_is_never_claimed_by_rollback(
    tmp_path: Path,
) -> None:
    project, _base, content, client = prepare_genesis(tmp_path)
    request = live.ApprovalRequest("0001", digest(content), 41, 1001)
    captured = live.LiveApprovalCapture(client, 1.0).capture(request)
    foreign = live.canonical_witness_bytes(captured)
    client.calls.clear()

    def collide(stage: str) -> None:
        if stage == "before_witness_link":
            target = project / "docs/requirements/witnesses/1001.json"
            target.write_bytes(foreign)
            target.chmod(0o644)

    with pytest.raises(binder.RequirementBinderRecoveryError, match="recovery refused"):
        binder.bind_requirement_revision(
            project, str(CANDIDATE), 41, 1001, client, hook=collide
        )

    assert (project / "docs/requirements/witnesses/1001.json").read_bytes() == foreign
    assert (project / contract.REGISTRY_LOCATION).read_text() == "schema_version = 2\n"


def test_rollback_refuses_an_identical_replacement_of_its_installed_witness(
    tmp_path: Path,
) -> None:
    project, _base, _content, client = prepare_genesis(tmp_path)
    witness = project / "docs/requirements/witnesses/1001.json"
    replacement_inode: int | None = None

    def replace_then_fail(stage: str) -> None:
        nonlocal replacement_inode
        if stage == "after_witness":
            exact_bytes = witness.read_bytes()
            witness.unlink()
            witness.write_bytes(exact_bytes)
            witness.chmod(0o644)
            replacement_inode = witness.stat().st_ino
        elif stage == "after_registry":
            raise RuntimeError("force rollback after the replacement")

    with pytest.raises(binder.RequirementBinderRecoveryError, match="recovery refused"):
        binder.bind_requirement_revision(
            project, str(CANDIDATE), 41, 1001, client, hook=replace_then_fail
        )

    assert witness.exists()
    assert witness.stat().st_ino == replacement_inode
    assert (project / contract.REGISTRY_LOCATION).read_text() == "schema_version = 2\n"


def test_rollback_never_overwrites_a_foreign_registry_change(tmp_path: Path) -> None:
    project, _base, _content, client = prepare_genesis(tmp_path)
    foreign = b"schema_version = 2\n# concurrent owner\n"

    def mutate_registry(stage: str) -> None:
        if stage == "after_witness":
            (project / contract.REGISTRY_LOCATION).write_bytes(foreign)

    with pytest.raises(binder.RequirementBinderRecoveryError, match="recovery refused"):
        binder.bind_requirement_revision(
            project,
            str(CANDIDATE),
            41,
            1001,
            client,
            hook=mutate_registry,
        )

    assert (project / contract.REGISTRY_LOCATION).read_bytes() == foreign


@pytest.mark.parametrize("foreign_change", ("extra", "head"))
def test_final_gate_refuses_last_second_repository_changes(
    tmp_path: Path, foreign_change: str
) -> None:
    project, base, _content, client = prepare_genesis(tmp_path)

    def mutate(stage: str) -> None:
        if stage != "before_final_state":
            return
        if foreign_change == "extra":
            (project / "late-extra.txt").write_text("foreign\n")
        else:
            subprocess.run(
                [
                    "/usr/bin/git",
                    "-c",
                    "user.name=foreign-owner",
                    "-c",
                    "user.email=foreign@invalid",
                    "commit",
                    "--allow-empty",
                    "--quiet",
                    "-m",
                    "foreign head",
                ],
                cwd=project,
                check=True,
            )

    with pytest.raises(binder.RequirementBinderRecoveryError, match="recovery refused"):
        binder.bind_requirement_revision(
            project, str(CANDIDATE), 41, 1001, client, hook=mutate
        )

    assert (project / contract.REGISTRY_LOCATION).read_text() == "schema_version = 2\n"
    assert not (project / "docs/requirements/witnesses/1001.json").exists()
    if foreign_change == "extra":
        assert (project / "late-extra.txt").read_text() == "foreign\n"
        assert git(project, "rev-parse", "HEAD").stdout.decode().strip() == base
    else:
        assert git(project, "rev-parse", "HEAD").stdout.decode().strip() != base


@pytest.mark.parametrize("unexpected", ("witness", "document"))
def test_ignored_contract_entries_are_not_outside_the_contract_boundary(
    tmp_path: Path, unexpected: str
) -> None:
    project, _base, _content, client = prepare_genesis(tmp_path)
    git_directory = project / ".git"
    info = git_directory / "info"
    info.mkdir(exist_ok=True)
    if unexpected == "witness":
        relative = Path("docs/requirements/witnesses/ignored.tmp")
    else:
        relative = Path("docs/requirements/0002-ignored.md")
    with (info / "exclude").open("a", encoding="utf-8") as exclusion:
        exclusion.write(f"/{relative.as_posix()}\n")
    target = project / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("ignored but contract-visible\n")

    with pytest.raises(binder.RequirementBinderError, match="directory differs"):
        bind_genesis(project, client)

    assert client.calls == []


@pytest.mark.parametrize("unexpected", ("witness", "document"))
def test_final_contract_gate_refuses_late_ignored_contract_entries(
    tmp_path: Path, unexpected: str
) -> None:
    project, _base, _content, client = prepare_genesis(tmp_path)
    info = project / ".git/info"
    info.mkdir(exist_ok=True)
    if unexpected == "witness":
        relative = Path("docs/requirements/witnesses/late.tmp")
    else:
        relative = Path("docs/requirements/0002-late.md")
    with (info / "exclude").open("a", encoding="utf-8") as exclusion:
        exclusion.write(f"/{relative.as_posix()}\n")

    def mutate(stage: str) -> None:
        if stage == "before_final_state":
            target = project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("late ignored but contract-visible\n")

    with pytest.raises(binder.RequirementBinderRecoveryError, match="recovery refused"):
        binder.bind_requirement_revision(
            project, str(CANDIDATE), 41, 1001, client, hook=mutate
        )

    assert (project / relative).read_text() == "late ignored but contract-visible\n"


def test_contract_directory_scan_accepts_its_exact_entry_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "contract-visible"
    directory.mkdir()
    monkeypatch.setattr(binder, "MAX_CONTRACT_DIRECTORY_ENTRIES", 3)
    for number in range(3):
        (directory / f"ignored-{number}.tmp").touch()

    assert binder._bounded_directory_entries(directory, Path("contract-visible")) == (
        "ignored-0.tmp",
        "ignored-1.tmp",
        "ignored-2.tmp",
    )


@pytest.mark.parametrize("scope", ("requirements", "witnesses"))
def test_ignored_contract_entries_exceed_a_fixed_bound_before_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
) -> None:
    project, _base, _content, client = prepare_genesis(tmp_path)
    if scope == "requirements":
        directory = project / contract.REQUIREMENTS_DIRECTORY
        with os.scandir(directory) as entries:
            baseline_entries = sum(1 for _entry in entries)
        monkeypatch.setattr(
            binder, "MAX_CONTRACT_DIRECTORY_ENTRIES", baseline_entries + 1
        )
        exclusion = "/docs/requirements/ignored-entry-*\n"
    else:
        directory = project / contract.WITNESSES_DIRECTORY
        directory.mkdir()
        monkeypatch.setattr(binder, "MAX_CONTRACT_DIRECTORY_ENTRIES", 1)
        exclusion = "/docs/requirements/witnesses/ignored-entry-*\n"
    with (project / ".git/info/exclude").open("a", encoding="utf-8") as ignored:
        ignored.write(exclusion)
    for number in range(2):
        (directory / f"ignored-entry-{number}.tmp").touch()

    with pytest.raises(binder.RequirementBinderError, match="entry-count limit"):
        bind_genesis(project, client)

    assert client.calls == []

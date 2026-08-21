from __future__ import annotations

import fcntl
import hashlib
import os
import re
import selectors
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from check_requirements import verify_current_contract
from requirement_contract import (
    ACCEPTANCE_LOCATION,
    DOCUMENT_NAME,
    MAX_ACCEPTANCE_BYTES,
    MAX_REGISTRY_BYTES,
    MAX_REQUIREMENT_BYTES,
    MAX_WITNESS_BYTES,
    PRODUCT_LOCATION,
    REGISTRY_LOCATION,
    REQUIREMENTS_DIRECTORY,
    WITNESSES_DIRECTORY,
    RequirementContractError,
    Revision,
    read_acceptance_manifest,
    read_approval_witness,
    read_registry_snapshot,
    read_requirement_shelf,
    render_product_view,
    validate_requirement_candidate,
)
from requirement_witness import (
    LIVE_DEADLINE_SECONDS,
    ApprovalRequest,
    GitHubClient,
    LiveApprovalCapture,
    LiveWitnessError,
    canonical_witness_bytes,
)

GIT_BINARY = Path("/usr/bin/git")
GIT_TIMEOUT_SECONDS = 10.0
MAX_GIT_OUTPUT_BYTES = 1024 * 1024
MAX_BASELINE_FILES = 600
MAX_CONTRACT_DIRECTORY_ENTRIES = MAX_BASELINE_FILES
SAFE_CANDIDATE_NAME = re.compile(r"(?P<document>[0-9]{4})-[a-z0-9][a-z0-9-]*\.md")
EXACT_GIT_SHA = re.compile(r"[0-9a-f]{40}")
EXPECTED_WITNESS_MODE = 0o644
GIT_ENVIRONMENT = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_COUNT": "4",
    "GIT_CONFIG_KEY_0": "core.filemode",
    "GIT_CONFIG_VALUE_0": "true",
    "GIT_CONFIG_KEY_1": "core.fsmonitor",
    "GIT_CONFIG_VALUE_1": "false",
    "GIT_CONFIG_KEY_2": "core.ignorestat",
    "GIT_CONFIG_VALUE_2": "false",
    "GIT_CONFIG_KEY_3": "core.untrackedcache",
    "GIT_CONFIG_VALUE_3": "false",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
}


class RequirementBinderError(Exception):
    pass


class RequirementBinderRecoveryError(RequirementBinderError):
    pass


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    content: bytes
    mode: int


@dataclass(frozen=True, slots=True)
class DirectorySnapshot:
    mode: int
    device: int
    inode: int
    entries: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateState:
    location: Path
    document: str
    status: str
    file: FileSnapshot


@dataclass(frozen=True, slots=True)
class PrewriteSnapshot:
    head: str
    candidate: CandidateState
    registry: FileSnapshot
    product: FileSnapshot
    witness_location: Path
    witness_directory: DirectorySnapshot | None


@dataclass(frozen=True, slots=True)
class BindingPlan:
    head: str
    candidate: CandidateState
    predecessor: str
    issue_number: int
    comment_id: int
    witness_location: Path
    witness_bytes: bytes
    registry_bytes: bytes
    product_bytes: bytes


@dataclass(frozen=True, slots=True)
class BindingResult:
    document: str
    content_sha256: str
    witness_location: Path
    head: str


@dataclass(frozen=True, slots=True)
class OwnedTemp:
    location: Path
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class InstalledWitness:
    location: Path
    device: int
    inode: int
    descriptor: int


class GitRunner:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        if not GIT_BINARY.is_file():
            raise RequirementBinderError("the fixed local Git binary is unavailable")

    def run(
        self,
        *arguments: str,
        allowed: frozenset[int] = frozenset({0}),
        maximum: int = MAX_GIT_OUTPUT_BYTES,
    ) -> tuple[int, bytes]:
        command = [str(GIT_BINARY), *arguments]
        process: subprocess.Popen[bytes] | None = None
        selector = selectors.DefaultSelector()
        stdout = bytearray()
        stderr = bytearray()
        deadline = time.monotonic() + GIT_TIMEOUT_SECONDS
        try:
            process = subprocess.Popen(
                command,
                cwd=self.project_root,
                env=GIT_ENVIRONMENT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
            assert process.stdout is not None
            assert process.stderr is not None
            selector.register(process.stdout, selectors.EVENT_READ, stdout)
            selector.register(process.stderr, selectors.EVENT_READ, stderr)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RequirementBinderError("local Git command exceeded its deadline")
                events = selector.select(min(0.25, remaining))
                if not events and process.poll() is not None:
                    events = [(key, selectors.EVENT_READ) for key in selector.get_map().values()]
                for key, _mask in events:
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    key.data.extend(chunk)
                    if len(stdout) + len(stderr) > maximum:
                        raise RequirementBinderError("local Git output exceeds its size limit")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RequirementBinderError("local Git command exceeded its deadline")
            returncode = process.wait(timeout=remaining)
        except RequirementBinderError:
            if process is not None:
                process.kill()
                process.wait()
            raise
        except Exception as error:
            if process is not None:
                process.kill()
                process.wait()
            raise RequirementBinderError("local Git command failed") from error
        finally:
            selector.close()
        if returncode not in allowed:
            raise RequirementBinderError("local Git command refused the repository state")
        return returncode, bytes(stdout)


def bind_requirement_revision(
    project_root: Path,
    candidate_path: str,
    issue_number: int,
    comment_id: int,
    client: GitHubClient,
    *,
    clock: Callable[[], float] = time.monotonic,
    hook: Callable[[str], None] = lambda _stage: None,
    on_prepared: Callable[[BindingResult], None] | None = None,
) -> BindingResult:
    started = clock()
    deadline = started + LIVE_DEADLINE_SECONDS
    root = project_root.resolve()
    git = GitRunner(root)
    location, document = _candidate_location(candidate_path)
    _positive_identifier(issue_number, "issue number")
    _positive_identifier(comment_id, "comment id")
    _verify_repository_root(git, root)
    git_directory = _git_directory(git)
    with _binder_lock(git_directory):
        baseline_head, baseline_revisions = _verify_head_baseline(git)
        before = _capture_prewrite_snapshot(
            root,
            git,
            location,
            document,
            comment_id,
        )
        if before.head != baseline_head:
            raise RequirementBinderError("HEAD changed while validating its baseline contract")
        predecessor = _predecessor_for(
            baseline_revisions,
            before.candidate,
        )
        request = ApprovalRequest(
            document,
            hashlib.sha256(before.candidate.file.content).hexdigest(),
            issue_number,
            comment_id,
        )
        captured = LiveApprovalCapture(client, deadline).capture(request)
        hook("after_capture")
        if _capture_prewrite_snapshot(
            root, git, location, document, comment_id
        ) != before:
            raise RequirementBinderError("repository state changed during live approval capture")
        witness_bytes = canonical_witness_bytes(captured)
        if len(witness_bytes) > MAX_WITNESS_BYTES:
            raise RequirementBinderError("canonical approval witness exceeds its size limit")
        registry_bytes = _append_revision(
            before.registry.content,
            before.candidate,
            predecessor,
            before.witness_location,
            hashlib.sha256(witness_bytes).hexdigest(),
        )
        product_bytes = _validate_planned_contract(
            git,
            before.head,
            before.candidate,
            before.witness_location,
            witness_bytes,
            registry_bytes,
        )
        plan = BindingPlan(
            before.head,
            before.candidate,
            predecessor,
            issue_number,
            comment_id,
            before.witness_location,
            witness_bytes,
            registry_bytes,
            product_bytes,
        )
        hook("before_write")
        if _capture_prewrite_snapshot(
            root, git, location, document, comment_id
        ) != before:
            raise RequirementBinderError("repository state changed before local binding")
        _install_plan(root, git, before, plan, hook)
        result = BindingResult(
            document,
            request.content_sha256,
            before.witness_location,
            before.head,
        )
        if on_prepared is not None:
            on_prepared(result)
        return result


def _candidate_location(candidate_path: str) -> tuple[Path, str]:
    if not isinstance(candidate_path, str):
        raise RequirementBinderError("candidate path must be text")
    location = Path(candidate_path)
    match = SAFE_CANDIDATE_NAME.fullmatch(location.name)
    if (
        location.is_absolute()
        or ".." in location.parts
        or location.parent != REQUIREMENTS_DIRECTORY
        or match is None
    ):
        raise RequirementBinderError("candidate path is outside the safe requirement subset")
    return Path(*location.parts), match["document"]


def _positive_identifier(value: int, owner: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RequirementBinderError(f"invalid {owner}")


def _verify_repository_root(git: GitRunner, root: Path) -> None:
    _returncode, output = git.run("rev-parse", "--show-toplevel")
    try:
        discovered = Path(output.decode("utf-8").strip()).resolve()
    except UnicodeDecodeError as error:
        raise RequirementBinderError("local Git returned a non-UTF-8 repository path") from error
    if discovered != root:
        raise RequirementBinderError("binder must run at the exact worktree root")
    _returncode, shallow = git.run("rev-parse", "--is-shallow-repository")
    if shallow.strip() == b"true":
        raise RequirementBinderError("binder refuses a shallow repository")


def _git_directory(git: GitRunner) -> Path:
    _returncode, output = git.run("rev-parse", "--path-format=absolute", "--git-dir")
    try:
        location = Path(output.decode("utf-8").strip())
    except UnicodeDecodeError as error:
        raise RequirementBinderError("local Git returned a non-UTF-8 git directory") from error
    if location.is_symlink() or not location.is_dir():
        raise RequirementBinderError("worktree Git directory is not a real directory")
    return location


@contextmanager
def _binder_lock(git_directory: Path) -> Iterator[None]:
    location = git_directory / "songmaker-requirement-bind.lock"
    try:
        descriptor = os.open(
            location,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
        )
    except OSError as error:
        raise RequirementBinderError("requirement binder lock is unavailable") from error
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RequirementBinderError("requirement binder lock is not a regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RequirementBinderError("another requirement binder owns this worktree") from error
        locked = True
        yield
    finally:
        if locked:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _head(git: GitRunner) -> str:
    _returncode, output = git.run("rev-parse", "--verify", "HEAD^{commit}")
    try:
        head = output.decode("ascii").strip()
    except UnicodeDecodeError as error:
        raise RequirementBinderError("local Git returned an invalid HEAD") from error
    if EXACT_GIT_SHA.fullmatch(head) is None:
        raise RequirementBinderError("local Git returned an invalid HEAD")
    return head


def _index_matches_head(git: GitRunner) -> None:
    returncode, _output = git.run(
        "diff",
        "--cached",
        "--quiet",
        "HEAD",
        "--",
        allowed=frozenset({0, 1}),
        maximum=4096,
    )
    if returncode != 0:
        raise RequirementBinderError("Git index must exactly match HEAD")
    for flag in ("-v", "-f"):
        _returncode, entries = git.run("ls-files", flag, "-z")
        if any(
            not entry.startswith(b"H ")
            for entry in entries.split(b"\0")
            if entry
        ):
            raise RequirementBinderError(
                "Git index must contain only ordinary tracked entries"
            )


def _status(git: GitRunner) -> dict[Path, str]:
    _returncode, output = git.run(
        "status",
        "--porcelain=v2",
        "-z",
        "--untracked-files=all",
        "--ignore-submodules=none",
    )
    statuses: dict[Path, str] = {}
    for record in (item for item in output.split(b"\0") if item):
        if record.startswith(b"? "):
            raw_path = record[2:]
            kind = "?"
        elif record.startswith(b"1 "):
            fields = record.split(b" ", 8)
            if len(fields) != 9:
                raise RequirementBinderError("local Git returned malformed status data")
            try:
                kind = fields[1].decode("ascii")
                submodule = fields[2].decode("ascii")
            except UnicodeDecodeError as error:
                raise RequirementBinderError("local Git returned malformed status data") from error
            if submodule != "N...":
                raise RequirementBinderError("binder refuses submodule status changes")
            raw_path = fields[8]
        else:
            raise RequirementBinderError("binder refuses non-ordinary Git status changes")
        try:
            path = Path(raw_path.decode("utf-8"))
        except UnicodeDecodeError as error:
            raise RequirementBinderError("local Git returned a non-UTF-8 path") from error
        if path in statuses:
            raise RequirementBinderError("local Git returned duplicate status paths")
        statuses[path] = kind
    return statuses


def _capture_prewrite_snapshot(
    root: Path,
    git: GitRunner,
    location: Path,
    document: str,
    comment_id: int,
) -> PrewriteSnapshot:
    head = _head(git)
    _index_matches_head(git)
    statuses = _status(git)
    if set(statuses) != {location} or statuses[location] not in {"?", ".M"}:
        raise RequirementBinderError(
            "worktree must contain exactly one uncommitted candidate delta"
        )
    candidate = CandidateState(
        location,
        document,
        statuses[location],
        _file_snapshot(root, location, MAX_REQUIREMENT_BYTES),
    )
    validate_requirement_candidate(candidate.file.content, location)
    registry = _file_snapshot(root, REGISTRY_LOCATION, MAX_REGISTRY_BYTES)
    product = _file_snapshot(root, PRODUCT_LOCATION, MAX_REQUIREMENT_BYTES)
    witness_location = WITNESSES_DIRECTORY / f"{comment_id}.json"
    witness_target = root / witness_location
    if witness_target.exists() or witness_target.is_symlink():
        raise RequirementBinderError("approval witness target already exists")
    witness_directory = _directory_snapshot(root, WITNESSES_DIRECTORY)
    _verify_contract_paths_without_candidate(root, candidate, witness_directory)
    return PrewriteSnapshot(
        head,
        candidate,
        registry,
        product,
        witness_location,
        witness_directory,
    )


def _file_snapshot(root: Path, location: Path, maximum: int) -> FileSnapshot:
    target = root / location
    parent = target.parent
    if parent.is_symlink() or not parent.is_dir() or target.is_symlink() or not target.is_file():
        raise RequirementBinderError(f"{location} is not a regular non-symlink file")
    opened = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(opened)
        if not stat.S_ISREG(metadata.st_mode):
            raise RequirementBinderError(f"{location} is not a regular file")
        buffer = bytearray()
        while len(buffer) <= maximum:
            chunk = os.read(opened, min(8192, maximum + 1 - len(buffer)))
            if not chunk:
                break
            buffer.extend(chunk)
        if len(buffer) > maximum:
            raise RequirementBinderError(f"{location} exceeds its byte limit")
        content = bytes(buffer)
    finally:
        os.close(opened)
    return FileSnapshot(
        content,
        stat.S_IMODE(metadata.st_mode),
    )


def _directory_snapshot(root: Path, location: Path) -> DirectorySnapshot | None:
    target = root / location
    if not target.exists() and not target.is_symlink():
        return None
    if target.is_symlink() or not target.is_dir():
        raise RequirementBinderError(f"{location} is not a real directory")
    metadata = target.stat()
    entries = _bounded_directory_entries(target, location)
    return DirectorySnapshot(
        stat.S_IMODE(metadata.st_mode), metadata.st_dev, metadata.st_ino, entries
    )


def _bounded_directory_entries(directory: Path, location: Path) -> tuple[str, ...]:
    entries: list[str] = []
    try:
        with os.scandir(directory) as discovered:
            for entry in discovered:
                if len(entries) >= MAX_CONTRACT_DIRECTORY_ENTRIES:
                    raise RequirementBinderError(
                        f"{location} exceeds its entry-count limit"
                    )
                entries.append(entry.name)
    except RequirementBinderError:
        raise
    except OSError as error:
        raise RequirementBinderError(f"cannot scan contract directory {location}") from error
    return tuple(sorted(entries))


def _verify_contract_paths_without_candidate(
    root: Path,
    candidate: CandidateState,
    witness_directory: DirectorySnapshot | None,
) -> None:
    revisions = read_registry_snapshot(root).revisions
    expected_documents = {revision.location for revision in revisions} | {candidate.location}
    requirements_directory = root / REQUIREMENTS_DIRECTORY
    requirement_entries = _bounded_directory_entries(
        requirements_directory, REQUIREMENTS_DIRECTORY
    )
    discovered_documents = {
        REQUIREMENTS_DIRECTORY / name
        for name in requirement_entries
        if DOCUMENT_NAME.fullmatch(name)
    }
    if discovered_documents != expected_documents:
        raise RequirementBinderError(
            "requirement directory differs from the baseline plus candidate"
        )
    expected_witnesses = {revision.witness_location.name for revision in revisions}
    discovered_witnesses = (
        set(witness_directory.entries) if witness_directory is not None else set()
    )
    if discovered_witnesses != expected_witnesses:
        raise RequirementBinderError("witness directory differs from the baseline registry")
    for revision in revisions:
        read_approval_witness(root, revision)


def _verify_head_baseline(git: GitRunner) -> tuple[str, tuple[Revision, ...]]:
    head = _head(git)
    with tempfile.TemporaryDirectory() as temporary:
        baseline = Path(temporary)
        _materialize_head(git, baseline, head)
        verify_current_contract(baseline)
        revisions = read_requirement_shelf(baseline).revisions
    if _head(git) != head:
        raise RequirementBinderError("HEAD changed while reading its baseline contract")
    return head, revisions


def _materialize_head(git: GitRunner, destination: Path, head: str) -> None:
    _returncode, listing = git.run(
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        head,
        "--",
        REQUIREMENTS_DIRECTORY.as_posix(),
        ACCEPTANCE_LOCATION.as_posix(),
        PRODUCT_LOCATION.as_posix(),
    )
    records = [record for record in listing.split(b"\0") if record]
    if len(records) > MAX_BASELINE_FILES:
        raise RequirementBinderError("HEAD contract has too many files")
    for record in records:
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, kind, object_id = metadata.decode("ascii").split()
            path = Path(raw_path.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            raise RequirementBinderError("HEAD contract tree is malformed") from error
        if path.is_absolute() or ".." in path.parts:
            raise RequirementBinderError("HEAD contract tree contains an unsafe path")
        in_owned_scope = (
            path == PRODUCT_LOCATION
            or path == ACCEPTANCE_LOCATION
            or path.is_relative_to(REQUIREMENTS_DIRECTORY)
        )
        if not in_owned_scope:
            raise RequirementBinderError("HEAD contract tree escaped its owned paths")
        if mode not in {"100644", "100755"} or kind != "blob":
            raise RequirementBinderError("HEAD contract contains a non-regular Git object")
        maximum = _baseline_file_limit(path)
        _returncode, content = git.run("cat-file", "blob", object_id, maximum=maximum + 1)
        if len(content) > maximum:
            raise RequirementBinderError(f"HEAD {path} exceeds its byte limit")
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _baseline_file_limit(path: Path) -> int:
    if path == REGISTRY_LOCATION or path == ACCEPTANCE_LOCATION:
        return MAX_REGISTRY_BYTES if path == REGISTRY_LOCATION else MAX_ACCEPTANCE_BYTES
    if path.parent == WITNESSES_DIRECTORY:
        return MAX_WITNESS_BYTES
    return MAX_REQUIREMENT_BYTES


def _predecessor_for(
    revisions: tuple[Revision, ...], candidate: CandidateState
) -> str:
    lineage = [revision for revision in revisions if revision.document == candidate.document]
    if not lineage:
        if candidate.status != "?":
            raise RequirementBinderError("Genesis candidate must be exactly one untracked file")
        if any(revision.location == candidate.location for revision in revisions):
            raise RequirementBinderError("candidate path already belongs to another document")
        return "GENESIS"
    if candidate.status != ".M":
        raise RequirementBinderError("Successor candidate must be an unstaged tracked modification")
    if any(revision.location != candidate.location for revision in lineage):
        raise RequirementBinderError("Successor candidate changed its fixed lineage path")
    predecessors = {
        revision.predecessor for revision in lineage if revision.predecessor != "GENESIS"
    }
    tips = [revision for revision in lineage if revision.content_sha256 not in predecessors]
    if len(tips) != 1:
        raise RequirementBinderError("baseline requirement lineage has no unique tip")
    digest = hashlib.sha256(candidate.file.content).hexdigest()
    if digest == tips[0].content_sha256:
        raise RequirementBinderError("Successor candidate bytes are unchanged")
    return tips[0].content_sha256


def _append_revision(
    registry: bytes,
    candidate: CandidateState,
    predecessor: str,
    witness_location: Path,
    witness_digest: str,
) -> bytes:
    content_digest = hashlib.sha256(candidate.file.content).hexdigest()
    separator = b"\n" if registry.endswith(b"\n") else b"\n\n"
    table = (
        "[[revision]]\n"
        f'document = "{candidate.document}"\n'
        f'path = "{candidate.location.as_posix()}"\n'
        f'content_sha256 = "{content_digest}"\n'
        f'witness_path = "{witness_location.as_posix()}"\n'
        f'witness_sha256 = "{witness_digest}"\n'
        f'predecessor = "{predecessor}"\n'
    ).encode("ascii")
    rendered = registry + separator + table
    if len(rendered) > MAX_REGISTRY_BYTES:
        raise RequirementBinderError("planned registry exceeds its byte limit")
    return rendered


def _validate_planned_contract(
    git: GitRunner,
    head: str,
    candidate: CandidateState,
    witness_location: Path,
    witness_bytes: bytes,
    registry_bytes: bytes,
) -> bytes:
    with tempfile.TemporaryDirectory() as temporary:
        planned = Path(temporary)
        _materialize_head(git, planned, head)
        target = planned / candidate.location
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(candidate.file.content)
        registry = planned / REGISTRY_LOCATION
        registry.write_bytes(registry_bytes)
        witness = planned / witness_location
        witness.parent.mkdir(parents=True, exist_ok=True)
        witness.write_bytes(witness_bytes)
        shelf = read_requirement_shelf(planned)
        acceptance = read_acceptance_manifest(planned, shelf)
        product_bytes = render_product_view(shelf, acceptance).encode("utf-8")
        (planned / PRODUCT_LOCATION).write_bytes(product_bytes)
        verify_current_contract(planned)
        return product_bytes


def _install_plan(
    root: Path,
    git: GitRunner,
    before: PrewriteSnapshot,
    plan: BindingPlan,
    hook: Callable[[str], None],
) -> None:
    owned_temps: list[OwnedTemp] = []
    created_directory: DirectorySnapshot | None = None
    installed_witness: InstalledWitness | None = None
    try:
        witness_directory = root / WITNESSES_DIRECTORY
        if before.witness_directory is None:
            witness_directory.mkdir(mode=0o755)
            created_directory = _directory_snapshot(root, WITNESSES_DIRECTORY)
            assert created_directory is not None
            _fsync_directory(witness_directory.parent)
        witness_temp = _write_temp(
            witness_directory,
            plan.witness_bytes,
            EXPECTED_WITNESS_MODE,
        )
        owned_temps.append(witness_temp)
        registry_temp = _write_temp(
            (root / REGISTRY_LOCATION).parent,
            plan.registry_bytes,
            before.registry.mode,
        )
        owned_temps.append(registry_temp)
        product_temp: OwnedTemp | None = None
        if plan.product_bytes != before.product.content:
            product_temp = _write_temp(
                (root / PRODUCT_LOCATION).parent,
                plan.product_bytes,
                before.product.mode,
            )
            owned_temps.append(product_temp)
        hook("before_witness_link")
        os.link(witness_temp.location, root / plan.witness_location)
        witness_descriptor = os.open(
            root / plan.witness_location,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        linked_metadata = os.fstat(witness_descriptor)
        if (
            linked_metadata.st_dev != witness_temp.device
            or linked_metadata.st_ino != witness_temp.inode
        ):
            os.close(witness_descriptor)
            raise RequirementBinderRecoveryError(
                "installed approval witness identity changed before ownership capture"
            )
        installed_witness = InstalledWitness(
            root / plan.witness_location,
            witness_temp.device,
            witness_temp.inode,
            witness_descriptor,
        )
        _unlink_owned(witness_temp)
        owned_temps.remove(witness_temp)
        _fsync_directory(witness_directory)
        hook("after_witness")
        _require_exact_file(root, REGISTRY_LOCATION, before.registry)
        os.replace(registry_temp.location, root / REGISTRY_LOCATION)
        owned_temps.remove(registry_temp)
        _fsync_directory((root / REGISTRY_LOCATION).parent)
        hook("after_registry")
        if product_temp is not None:
            _require_exact_file(root, PRODUCT_LOCATION, before.product)
            os.replace(product_temp.location, root / PRODUCT_LOCATION)
            owned_temps.remove(product_temp)
            _fsync_directory((root / PRODUCT_LOCATION).parent)
        hook("after_product")
        hook("before_final_state")
        _verify_final_state(root, git, before, plan)
    except Exception as error:
        try:
            _rollback(
                root,
                git,
                before,
                plan,
                owned_temps,
                created_directory,
                installed_witness,
            )
        except Exception as recovery_error:
            raise RequirementBinderRecoveryError(
                "binding failed and automatic recovery refused changed bytes; "
                "inspect the worktree before continuing"
            ) from recovery_error
        if isinstance(error, (RequirementBinderError, RequirementContractError, LiveWitnessError)):
            raise RequirementBinderError(str(error)) from error
        raise RequirementBinderError("local binding transaction failed") from error
    finally:
        if installed_witness is not None:
            os.close(installed_witness.descriptor)


def _write_temp(directory: Path, content: bytes, mode: int) -> OwnedTemp:
    descriptor, raw_location = tempfile.mkstemp(prefix=".requirement-bind-", dir=directory)
    location = Path(raw_location)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        metadata = location.stat()
        return OwnedTemp(location, metadata.st_dev, metadata.st_ino)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        location.unlink(missing_ok=True)
        raise


def _unlink_owned(owned: OwnedTemp) -> None:
    try:
        metadata = owned.location.lstat()
    except FileNotFoundError:
        return
    if metadata.st_dev != owned.device or metadata.st_ino != owned.inode:
        raise RequirementBinderRecoveryError("temporary file identity changed")
    owned.location.unlink()


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_exact_file(root: Path, location: Path, expected: FileSnapshot) -> None:
    if _file_snapshot(root, location, max(len(expected.content), 1)) != expected:
        raise RequirementBinderError(f"{location} changed during local binding")


def _restore_file(
    root: Path,
    location: Path,
    before: FileSnapshot,
    installed: bytes,
) -> None:
    current = _file_snapshot(root, location, max(len(before.content), len(installed), 1))
    if current == before:
        return
    if current.content != installed or current.mode != before.mode:
        raise RequirementBinderRecoveryError(f"rollback refuses changed {location}")
    temporary = _write_temp((root / location).parent, before.content, before.mode)
    try:
        os.replace(temporary.location, root / location)
        _fsync_directory((root / location).parent)
    finally:
        _unlink_owned(temporary)


def _rollback(
    root: Path,
    git: GitRunner,
    before: PrewriteSnapshot,
    plan: BindingPlan,
    owned_temps: list[OwnedTemp],
    created_directory: DirectorySnapshot | None,
    installed_witness: InstalledWitness | None,
) -> None:
    for owned in tuple(owned_temps):
        _unlink_owned(owned)
    _restore_file(root, REGISTRY_LOCATION, before.registry, plan.registry_bytes)
    _restore_file(root, PRODUCT_LOCATION, before.product, plan.product_bytes)
    if installed_witness is not None:
        _remove_installed_witness(root, plan, installed_witness)
    if created_directory is not None:
        current_directory = _directory_snapshot(root, WITNESSES_DIRECTORY)
        if current_directory != created_directory:
            raise RequirementBinderRecoveryError("rollback refuses changed witness directory")
        (root / WITNESSES_DIRECTORY).rmdir()
        _fsync_directory((root / WITNESSES_DIRECTORY).parent)
    restored = _capture_prewrite_snapshot(
        root,
        git,
        before.candidate.location,
        before.candidate.document,
        plan.comment_id,
    )
    if restored != before:
        raise RequirementBinderRecoveryError("rollback did not restore the candidate-only snapshot")
    baseline_head, _revisions = _verify_head_baseline(git)
    if baseline_head != before.head:
        raise RequirementBinderRecoveryError("rollback HEAD differs from its baseline")


def _remove_installed_witness(
    root: Path,
    plan: BindingPlan,
    installed: InstalledWitness,
) -> None:
    held = os.fstat(installed.descriptor)
    if held.st_dev != installed.device or held.st_ino != installed.inode:
        raise RequirementBinderRecoveryError("rollback lost approval witness ownership")
    try:
        metadata = installed.location.lstat()
    except FileNotFoundError:
        return
    if metadata.st_dev != installed.device or metadata.st_ino != installed.inode:
        raise RequirementBinderRecoveryError("rollback refuses replaced approval witness")
    current = _file_snapshot(root, plan.witness_location, MAX_WITNESS_BYTES)
    if current.content != plan.witness_bytes or current.mode != EXPECTED_WITNESS_MODE:
        raise RequirementBinderRecoveryError("rollback refuses changed approval witness")
    _unlink_owned(OwnedTemp(installed.location, installed.device, installed.inode))
    _fsync_directory(installed.location.parent)


def _verify_exact_head_history(root: Path, git: GitRunner, expected_head: str) -> None:
    if _head(git) != expected_head:
        raise RequirementBinderError("HEAD changed during exact history verification")
    with tempfile.TemporaryDirectory() as temporary:
        baseline = Path(temporary)
        _materialize_head(git, baseline, expected_head)
        base = read_registry_snapshot(baseline)
    current = read_registry_snapshot(root)
    if base.schema_version != current.schema_version:
        raise RequirementBinderError("registry schema changed during local binding")
    for revision in base.revisions:
        if revision not in current.revisions:
            raise RequirementBinderError(
                f"revision {revision.document} {revision.content_sha256} changed or deleted"
            )


def _verify_final_state(
    root: Path,
    git: GitRunner,
    before: PrewriteSnapshot,
    plan: BindingPlan,
) -> None:
    verify_current_contract(root)
    _verify_exact_head_history(root, git, before.head)
    if _head(git) != before.head:
        raise RequirementBinderError("HEAD changed before binding commit point")
    _index_matches_head(git)
    expected = {
        before.candidate.location: before.candidate.status,
        REGISTRY_LOCATION: ".M",
        plan.witness_location: "?",
    }
    if plan.product_bytes != before.product.content:
        expected[PRODUCT_LOCATION] = ".M"
    if _status(git) != expected:
        raise RequirementBinderError("final worktree contains unexpected binding deltas")
    _require_exact_file(root, before.candidate.location, before.candidate.file)
    registry = _file_snapshot(root, REGISTRY_LOCATION, len(plan.registry_bytes))
    if registry.content != plan.registry_bytes or registry.mode != before.registry.mode:
        raise RequirementBinderError("final registry bytes or mode differ from the plan")
    product = _file_snapshot(root, PRODUCT_LOCATION, max(len(plan.product_bytes), 1))
    if product.content != plan.product_bytes or product.mode != before.product.mode:
        raise RequirementBinderError("final PRODUCT bytes or mode differ from the plan")
    witness = _file_snapshot(root, plan.witness_location, MAX_WITNESS_BYTES)
    if witness.content != plan.witness_bytes or witness.mode != EXPECTED_WITNESS_MODE:
        raise RequirementBinderError("final witness bytes or mode differ from the plan")

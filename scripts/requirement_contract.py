from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIREMENTS_DIRECTORY = Path("docs/requirements")
WITNESSES_DIRECTORY = REQUIREMENTS_DIRECTORY / "witnesses"
REGISTRY_LOCATION = REQUIREMENTS_DIRECTORY / "revisions.toml"
ACCEPTANCE_LOCATION = Path("docs/acceptance/acceptance.toml")
PRODUCT_LOCATION = Path("docs/PRODUCT.md")
DOCUMENT_NAME = re.compile(r"^(?P<document>\d{4})-.+\.md$")
WITNESS_NAME = re.compile(r"^(?P<comment>[1-9][0-9]*)\.json$")
REQUIREMENT_IDENTIFIER = re.compile(r"REQ-[A-Z0-9]+-[0-9]{2}")
REQUIREMENT_HEADING = re.compile(
    r"### (?P<identifier>REQ-[A-Z0-9]+-[0-9]{2}):\s*(?P<sentence>\S.*)"
)
SOURCE_LINE = re.compile(r"Quelle: (?:OPERATOR|DESK) — \S.*")
ACCEPTANCE_IDENTIFIER = re.compile(r"ACC-[A-Z0-9]+-[0-9]{2}")
DIGEST = re.compile(r"[0-9a-f]{64}")
GITHUB_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
GENESIS = "GENESIS"
REGISTRY_SCHEMA_VERSION = 2
ACCEPTANCE_SCHEMA_VERSION = 1
WITNESS_SCHEMA_VERSION = 1
EXPECTED_REPOSITORY_ID = 1163644113
EXPECTED_REPOSITORY_FULL_NAME = "FlexOr2/songmaker"
EXPECTED_OPERATOR_ID = 44832414
MAX_REGISTRY_BYTES = 1024 * 1024
MAX_REVISIONS = 256
MAX_REQUIREMENT_BYTES = 256 * 1024
MAX_ACCEPTANCE_BYTES = 1024 * 1024
MAX_ACCEPTANCE_ENTRIES = 4096
MAX_WITNESS_BYTES = 4096
MAX_APPROVAL_BODY_BYTES = 256
MAX_APPROVAL_BODY_BASE64 = 4 * ((MAX_APPROVAL_BODY_BYTES + 2) // 3)
REGISTRY_FIELDS = frozenset({"schema_version", "revision"})
REVISION_FIELDS = frozenset(
    {
        "document",
        "path",
        "content_sha256",
        "witness_path",
        "witness_sha256",
        "predecessor",
    }
)
WITNESS_FIELDS = frozenset(
    {
        "schema_version",
        "repository_id",
        "repository_full_name",
        "issue_id",
        "issue_number",
        "comment_id",
        "author_id",
        "created_at",
        "updated_at",
        "body_base64",
        "body_sha256",
    }
)
ACCEPTANCE_ROOT_FIELDS = frozenset({"schema_version", "acceptance"})
ACCEPTANCE_FIELDS = frozenset({"id", "text", "requirements", "proof_kind", "critical"})
PROOF_KINDS = frozenset({"unit", "integration", "browser", "operator"})


class RequirementContractError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RequirementRule:
    identifier: str
    located_in: Path


@dataclass(frozen=True, slots=True)
class Revision:
    document: str
    location: Path
    content_sha256: str
    witness_location: Path
    witness_sha256: str
    predecessor: str


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    schema_version: int
    revisions: tuple[Revision, ...]


@dataclass(frozen=True, slots=True)
class RequirementShelf:
    document_count: int
    revision_count: int
    rules: tuple[RequirementRule, ...]
    revisions: tuple[Revision, ...]


@dataclass(frozen=True, slots=True)
class ApprovalWitness:
    repository_id: int
    repository_full_name: str
    issue_id: int
    issue_number: int
    comment_id: int
    author_id: int
    created_at: str
    updated_at: str
    body: bytes
    body_sha256: str
    located_in: Path


@dataclass(frozen=True, slots=True)
class AcceptanceEntry:
    identifier: str
    text: str
    requirements: tuple[str, ...]
    proof_kind: str
    critical: bool


def approval_bytes(document: str, content_digest: str) -> bytes:
    return f"APPROVE REQUIREMENT REVISION {document} sha256:{content_digest}".encode("ascii")


def read_requirement_registry(project_root: Path) -> tuple[Revision, ...]:
    return read_registry_snapshot(project_root).revisions


def read_registry_snapshot(
    project_root: Path, *, allow_empty_schema_one: bool = False
) -> RegistrySnapshot:
    raw = _read_toml(project_root, REGISTRY_LOCATION, MAX_REGISTRY_BYTES)
    _exact_fields(raw, REGISTRY_FIELDS, str(REGISTRY_LOCATION))
    version = _schema_version(raw, REGISTRY_LOCATION, {1, REGISTRY_SCHEMA_VERSION})
    entries = raw.get("revision", [])
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise RequirementContractError(f"{REGISTRY_LOCATION} revision must be an array of tables")
    if len(entries) > MAX_REVISIONS:
        raise RequirementContractError(
            f"{REGISTRY_LOCATION} has {len(entries)} revisions; maximum is {MAX_REVISIONS}"
        )
    if version == 1:
        if not allow_empty_schema_one or entries:
            raise RequirementContractError(
                f"{REGISTRY_LOCATION} schema 1 is allowed only as an empty exact-base migration"
            )
        return RegistrySnapshot(version, ())
    return RegistrySnapshot(version, tuple(_revision(item) for item in entries))


def read_requirement_shelf(project_root: Path) -> RequirementShelf:
    revisions = read_requirement_registry(project_root)
    groups: defaultdict[str, list[Revision]] = defaultdict(list)
    location_owners: dict[Path, str] = {}
    for revision in revisions:
        owner = location_owners.setdefault(revision.location, revision.document)
        if owner != revision.document:
            raise RequirementContractError(
                f"{revision.location} has document owners {owner} and {revision.document}"
            )
        groups[revision.document].append(revision)
    for document, lineage in groups.items():
        if len({revision.location for revision in lineage}) != 1:
            raise RequirementContractError(f"requirement {document} has more than one lineage path")

    requirement_directory = _real_directory(project_root, REQUIREMENTS_DIRECTORY)
    discovered_documents = {
        path.relative_to(project_root.resolve())
        for path in requirement_directory.iterdir()
        if DOCUMENT_NAME.fullmatch(path.name)
    }
    registered_documents = set(location_owners)
    if missing := sorted(discovered_documents - registered_documents):
        raise RequirementContractError(f"requirement registry omits {', '.join(map(str, missing))}")
    if absent := sorted(registered_documents - discovered_documents):
        raise RequirementContractError(
            f"requirement registry names absent {', '.join(map(str, absent))}"
        )

    active_revisions = {
        document: _lineage_tip(document, tuple(lineage))
        for document, lineage in sorted(groups.items())
    }
    _verify_witness_shelf(project_root, revisions)
    rules: list[RequirementRule] = []
    for active in active_revisions.values():
        rules.extend(_read_requirement_document(project_root, active))

    seen: dict[str, Path] = {}
    for rule in rules:
        if previous := seen.get(rule.identifier):
            raise RequirementContractError(
                f"{rule.located_in} publishes {rule.identifier} again; first in {previous}"
            )
        seen[rule.identifier] = rule.located_in
    return RequirementShelf(len(groups), len(revisions), tuple(rules), revisions)


def read_approval_witness(project_root: Path, revision: Revision) -> ApprovalWitness:
    raw_bytes = _read_bytes(project_root, revision.witness_location, MAX_WITNESS_BYTES)
    actual_digest = hashlib.sha256(raw_bytes).hexdigest()
    if actual_digest != revision.witness_sha256:
        raise RequirementContractError(
            f"{revision.witness_location} has digest {actual_digest}, expected "
            f"{revision.witness_sha256}"
        )
    raw = _read_json_object(raw_bytes, revision.witness_location)
    _exact_fields(raw, WITNESS_FIELDS, str(revision.witness_location))
    _schema_version(raw, revision.witness_location, {WITNESS_SCHEMA_VERSION})
    repository_id = _positive_int(raw, "repository_id", revision.witness_location)
    if repository_id != EXPECTED_REPOSITORY_ID:
        raise RequirementContractError(
            f"{revision.witness_location} has repository_id {repository_id}, expected "
            f"{EXPECTED_REPOSITORY_ID}"
        )
    repository_name = raw.get("repository_full_name")
    if repository_name != EXPECTED_REPOSITORY_FULL_NAME:
        raise RequirementContractError(
            f"{revision.witness_location} has repository_full_name {repository_name!r}"
        )
    issue_id = _positive_int(raw, "issue_id", revision.witness_location)
    issue_number = _positive_int(raw, "issue_number", revision.witness_location)
    comment_id = _positive_int(raw, "comment_id", revision.witness_location)
    author_id = _positive_int(raw, "author_id", revision.witness_location)
    if author_id != EXPECTED_OPERATOR_ID:
        raise RequirementContractError(
            f"{revision.witness_location} has author_id {author_id}, expected "
            f"{EXPECTED_OPERATOR_ID}"
        )
    name_match = WITNESS_NAME.fullmatch(revision.witness_location.name)
    if name_match is None or int(name_match["comment"]) != comment_id:
        raise RequirementContractError(
            f"{revision.witness_location} does not match comment_id {comment_id}"
        )
    created_at = _timestamp(raw, "created_at", revision.witness_location)
    updated_at = _timestamp(raw, "updated_at", revision.witness_location)
    if created_at != updated_at:
        raise RequirementContractError(
            f"{revision.witness_location} records an edited approval comment"
        )
    encoded_body = raw.get("body_base64")
    if not isinstance(encoded_body, str) or len(encoded_body) > MAX_APPROVAL_BODY_BASE64:
        raise RequirementContractError(
            f"{revision.witness_location} has invalid or oversized body_base64"
        )
    try:
        body = base64.b64decode(encoded_body, validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError) as error:
        raise RequirementContractError(
            f"{revision.witness_location} has invalid body_base64"
        ) from error
    canonical_body = base64.b64encode(body).decode("ascii")
    if len(body) > MAX_APPROVAL_BODY_BYTES or canonical_body != encoded_body:
        raise RequirementContractError(
            f"{revision.witness_location} has noncanonical or oversized body_base64"
        )
    body_digest = _matching_text(
        raw, "body_sha256", DIGEST, str(revision.witness_location)
    )
    if hashlib.sha256(body).hexdigest() != body_digest:
        raise RequirementContractError(
            f"{revision.witness_location} body digest does not match its exact bytes"
        )
    expected_body = approval_bytes(revision.document, revision.content_sha256)
    if body != expected_body:
        raise RequirementContractError(
            f"{revision.witness_location} body is not the exact approval line for "
            f"revision {revision.document}"
        )
    return ApprovalWitness(
        repository_id,
        repository_name,
        issue_id,
        issue_number,
        comment_id,
        author_id,
        created_at,
        updated_at,
        body,
        body_digest,
        revision.witness_location,
    )


def read_acceptance_manifest(
    project_root: Path, shelf: RequirementShelf
) -> tuple[AcceptanceEntry, ...]:
    raw = _read_toml(project_root, ACCEPTANCE_LOCATION, MAX_ACCEPTANCE_BYTES)
    _exact_fields(raw, ACCEPTANCE_ROOT_FIELDS, str(ACCEPTANCE_LOCATION))
    _schema_version(raw, ACCEPTANCE_LOCATION, {ACCEPTANCE_SCHEMA_VERSION})
    entries = raw.get("acceptance", [])
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise RequirementContractError(
            f"{ACCEPTANCE_LOCATION} acceptance must be an array of tables"
        )
    if len(entries) > MAX_ACCEPTANCE_ENTRIES:
        raise RequirementContractError(
            f"{ACCEPTANCE_LOCATION} has {len(entries)} entries; maximum is "
            f"{MAX_ACCEPTANCE_ENTRIES}"
        )
    active_requirements = {rule.identifier for rule in shelf.rules}
    accepted: list[AcceptanceEntry] = []
    identifiers: set[str] = set()
    for raw_entry in entries:
        entry = _acceptance_entry(raw_entry)
        if entry.identifier in identifiers:
            raise RequirementContractError(
                f"acceptance {entry.identifier} is declared more than once"
            )
        identifiers.add(entry.identifier)
        for requirement in entry.requirements:
            if requirement not in active_requirements:
                raise RequirementContractError(
                    f"acceptance {entry.identifier} references inactive requirement {requirement}"
                )
        accepted.append(entry)
    return tuple(accepted)


def render_product_view(shelf: RequirementShelf, acceptance: tuple[AcceptanceEntry, ...]) -> str:
    return (
        "# Product status\n\n"
        "<!-- Generated from the requirement and acceptance registries; do not edit. -->\n\n"
        f"- Active requirement documents: {shelf.document_count}\n"
        f"- Active requirement rules: {len(shelf.rules)}\n"
        f"- Declared acceptance sentences: {len(acceptance)}\n\n"
        "No implementation status is claimed. Issue #42 must bind acceptance to "
        "executed tests before this view may report implementation.\n"
    )


def _revision(raw: dict[str, Any]) -> Revision:
    _exact_fields(raw, REVISION_FIELDS, "revision entry")
    document = _matching_text(raw, "document", re.compile(r"\d{4}"), "revision")
    location = _requirement_location(raw.get("path"), document)
    content_digest = _matching_text(raw, "content_sha256", DIGEST, f"revision {document}")
    witness_location = _witness_location(raw.get("witness_path"), document)
    witness_digest = _matching_text(raw, "witness_sha256", DIGEST, f"revision {document}")
    predecessor = raw.get("predecessor")
    if not isinstance(predecessor, str) or (
        predecessor != GENESIS and DIGEST.fullmatch(predecessor) is None
    ):
        raise RequirementContractError(
            f"revision {document} has invalid predecessor {predecessor!r}"
        )
    return Revision(
        document,
        location,
        content_digest,
        witness_location,
        witness_digest,
        predecessor,
    )


def _acceptance_entry(raw: dict[str, Any]) -> AcceptanceEntry:
    _exact_fields(raw, ACCEPTANCE_FIELDS, "acceptance entry")
    identifier = _matching_text(raw, "id", ACCEPTANCE_IDENTIFIER, "acceptance entry")
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        raise RequirementContractError(f"acceptance {identifier} has invalid text {text!r}")
    requirements = raw.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        raise RequirementContractError(
            f"acceptance {identifier} requirements must be a nonempty list"
        )
    if not all(
        isinstance(requirement, str) and REQUIREMENT_IDENTIFIER.fullmatch(requirement) is not None
        for requirement in requirements
    ):
        raise RequirementContractError(
            f"acceptance {identifier} has malformed requirement identifiers"
        )
    if len(set(requirements)) != len(requirements):
        raise RequirementContractError(f"acceptance {identifier} repeats a requirement edge")
    proof_kind = raw.get("proof_kind")
    if not isinstance(proof_kind, str) or proof_kind not in PROOF_KINDS:
        raise RequirementContractError(
            f"acceptance {identifier} has unsupported proof_kind {proof_kind!r}"
        )
    critical = raw.get("critical")
    if not isinstance(critical, bool):
        raise RequirementContractError(f"acceptance {identifier} has invalid critical {critical!r}")
    return AcceptanceEntry(identifier, text.strip(), tuple(requirements), proof_kind, critical)


def _lineage_tip(document: str, lineage: tuple[Revision, ...]) -> Revision:
    by_digest = {revision.content_sha256: revision for revision in lineage}
    if len(by_digest) != len(lineage):
        raise RequirementContractError(f"requirement {document} repeats a revision")
    for revision in lineage:
        if revision.predecessor == revision.content_sha256:
            raise RequirementContractError(
                f"requirement {document} revision {revision.content_sha256} references itself"
            )
        if revision.predecessor != GENESIS and revision.predecessor not in by_digest:
            raise RequirementContractError(
                f"requirement {document} revision {revision.content_sha256} has unknown "
                f"predecessor {revision.predecessor}"
            )
    for revision in lineage:
        visited: set[str] = set()
        cursor = revision
        while cursor.predecessor != GENESIS:
            if cursor.content_sha256 in visited:
                raise RequirementContractError(f"requirement {document} has a cycle")
            visited.add(cursor.content_sha256)
            cursor = by_digest[cursor.predecessor]
    successor_counts = Counter(
        revision.predecessor for revision in lineage if revision.predecessor != GENESIS
    )
    if branch := next((digest for digest, count in successor_counts.items() if count > 1), None):
        raise RequirementContractError(f"requirement {document} branches after {branch}")
    tips = set(by_digest) - set(successor_counts)
    if len(tips) != 1:
        raise RequirementContractError(f"requirement {document} has multiple tips {sorted(tips)}")
    tip = by_digest[tips.pop()]
    visited = set()
    cursor = tip
    while cursor.predecessor != GENESIS:
        visited.add(cursor.content_sha256)
        cursor = by_digest[cursor.predecessor]
    visited.add(cursor.content_sha256)
    if len(visited) != len(lineage):
        raise RequirementContractError(
            f"requirement {document} has multiple tips outside its active line"
        )
    return tip


def _verify_witness_shelf(project_root: Path, revisions: tuple[Revision, ...]) -> None:
    witness_counts = Counter(revision.witness_location for revision in revisions)
    if repeated := next(
        (location for location, count in witness_counts.items() if count > 1), None
    ):
        raise RequirementContractError(
            f"approval witness {repeated} is bound by more than one revision"
        )
    registered = {revision.witness_location for revision in revisions}
    root = project_root.resolve()
    directory = root / WITNESSES_DIRECTORY
    if directory.exists() or directory.is_symlink():
        real_directory = _real_directory(project_root, WITNESSES_DIRECTORY)
        children = tuple(real_directory.iterdir())
        if unexpected := sorted(
            path.name for path in children if WITNESS_NAME.fullmatch(path.name) is None
        ):
            raise RequirementContractError(
                f"{WITNESSES_DIRECTORY} has unexpected entries {unexpected}"
            )
        discovered = {path.relative_to(root) for path in children}
    else:
        discovered = set()
    if missing := sorted(discovered - registered):
        raise RequirementContractError(
            f"witness registry omits {', '.join(map(str, missing))}"
        )
    if absent := sorted(registered - discovered):
        raise RequirementContractError(
            f"witness registry names absent {', '.join(map(str, absent))}"
        )
    seen_comments: dict[int, Path] = {}
    for revision in revisions:
        witness = read_approval_witness(project_root, revision)
        if previous := seen_comments.get(witness.comment_id):
            raise RequirementContractError(
                f"approval comment {witness.comment_id} is bound by both {previous} and "
                f"{witness.located_in}"
            )
        seen_comments[witness.comment_id] = witness.located_in


def _read_requirement_document(
    project_root: Path, active: Revision
) -> tuple[RequirementRule, ...]:
    content = _read_bytes(project_root, active.location, MAX_REQUIREMENT_BYTES)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RequirementContractError(f"{active.location} is not UTF-8") from error
    actual = hashlib.sha256(content).hexdigest()
    if actual != active.content_sha256:
        raise RequirementContractError(
            f"{active.location} has current digest {actual}, but its sole registry tip "
            f"is {active.content_sha256}"
        )
    return _parse_strict_document(text, active.location)


def _parse_strict_document(text: str, location: Path) -> tuple[RequirementRule, ...]:
    lines = text.splitlines()
    if not lines or re.fullmatch(r"# \S.*", lines[0]) is None:
        raise RequirementContractError(f"{location} has no nonempty title")
    sections = [
        (line[3:].strip(), index) for index, line in enumerate(lines) if line.startswith("## ")
    ]
    names = tuple(name for name, _ in sections)
    if names not in (("Intent", "Rules"), ("Intent", "Rules", "Non-goals")):
        raise RequirementContractError(f"{location} has invalid sections {names}")
    if any(line.strip() for line in lines[1 : sections[0][1]]):
        raise RequirementContractError(f"{location} has content before Intent")
    ranges = {
        name: lines[start + 1 : sections[index + 1][1] if index + 1 < len(sections) else None]
        for index, (name, start) in enumerate(sections)
    }
    _nonempty_plain_section(ranges["Intent"], location, "Intent")
    if "Non-goals" in ranges:
        _nonempty_plain_section(ranges["Non-goals"], location, "Non-goals")
    return _parse_rules(ranges["Rules"], location)


def _parse_rules(lines: list[str], location: Path) -> tuple[RequirementRule, ...]:
    rules: list[RequirementRule] = []
    index = 0
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        heading = REQUIREMENT_HEADING.fullmatch(lines[index])
        if heading is None:
            raise RequirementContractError(f"{location} has unknown rule field {lines[index]!r}")
        index += 1
        body: list[str] = []
        while index < len(lines) and not lines[index].startswith("### "):
            if lines[index].strip():
                body.append(lines[index])
            index += 1
        if len(body) != 1 or SOURCE_LINE.fullmatch(body[0]) is None:
            raise RequirementContractError(
                f"{location} publishes {heading['identifier']} without exactly one "
                "Quelle grade OPERATOR or DESK and a source pointer"
            )
        rules.append(RequirementRule(heading["identifier"], location))
    if not rules:
        raise RequirementContractError(f"{location} has no requirement rule")
    return tuple(rules)


def _nonempty_plain_section(lines: list[str], location: Path, name: str) -> None:
    if not any(line.strip() for line in lines):
        raise RequirementContractError(f"{location} has empty {name}")
    if any(line.startswith("#") for line in lines):
        raise RequirementContractError(f"{location} has a heading inside {name}")


def _read_toml(project_root: Path, location: Path, maximum: int) -> dict[str, Any]:
    content = _read_bytes(project_root, location, maximum)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RequirementContractError(f"{location} is not UTF-8") from error
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise RequirementContractError(f"{location} is unreadable: {error}") from error


def _read_json_object(content: bytes, location: Path) -> dict[str, Any]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RequirementContractError(f"{location} is not UTF-8") from error

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for key, value in pairs:
            if key in parsed:
                raise RequirementContractError(f"{location} repeats JSON key {key!r}")
            parsed[key] = value
        return parsed

    def reject_constant(value: str) -> Any:
        raise RequirementContractError(f"{location} has invalid JSON constant {value}")

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as error:
        raise RequirementContractError(f"{location} is unreadable JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise RequirementContractError(f"{location} must contain one JSON object")
    return parsed


def _read_bytes(project_root: Path, location: Path, maximum: int) -> bytes:
    target = _regular_file(project_root, location)
    with target.open("rb") as stream:
        content = stream.read(maximum + 1)
    if len(content) > maximum:
        raise RequirementContractError(f"{location} exceeds the {maximum}-byte limit")
    return content


def _real_directory(project_root: Path, location: Path) -> Path:
    directory = project_root.resolve() / location
    if directory.is_symlink() or not directory.is_dir():
        raise RequirementContractError(f"{location} is not a real directory")
    return directory


def _regular_file(project_root: Path, location: Path) -> Path:
    root = project_root.resolve()
    directory = _real_directory(root, location.parent)
    target = root / location
    if target.is_symlink() or not target.is_file() or target.parent != directory:
        raise RequirementContractError(
            f"{location} is not a regular non-symlink file under {directory}"
        )
    return target


def _exact_fields(raw: dict[str, Any], expected: frozenset[str], owner: str) -> None:
    if unknown := sorted(set(raw) - expected):
        raise RequirementContractError(f"{owner} has unknown fields {unknown}")
    if missing := sorted(expected - set(raw)):
        optional = {"revision", "acceptance"}
        required_missing = [field for field in missing if field not in optional]
        if required_missing:
            raise RequirementContractError(f"{owner} lacks fields {required_missing}")


def _schema_version(raw: dict[str, Any], location: Path, supported: set[int]) -> int:
    value = raw.get("schema_version")
    if isinstance(value, bool) or not isinstance(value, int) or value not in supported:
        raise RequirementContractError(f"{location} has unsupported schema {value!r}")
    return value


def _matching_text(
    raw: dict[str, Any], field: str, pattern: re.Pattern[str], owner: str
) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise RequirementContractError(f"{owner} has invalid {field} {value!r}")
    return value


def _positive_int(raw: dict[str, Any], field: str, location: Path) -> int:
    value = raw.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RequirementContractError(f"{location} has invalid {field} {value!r}")
    return value


def _timestamp(raw: dict[str, Any], field: str, location: Path) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or GITHUB_TIMESTAMP.fullmatch(value) is None:
        raise RequirementContractError(f"{location} has invalid {field} {value!r}")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise RequirementContractError(f"{location} has invalid {field} {value!r}") from error
    return value


def _requirement_location(value: Any, document: str) -> Path:
    if not isinstance(value, str):
        raise RequirementContractError(
            f"requirement {document} has invalid registry path {value!r}"
        )
    location = Path(value)
    if (
        location.is_absolute()
        or ".." in location.parts
        or location.parent != REQUIREMENTS_DIRECTORY
        or DOCUMENT_NAME.fullmatch(location.name) is None
        or not location.name.startswith(f"{document}-")
    ):
        raise RequirementContractError(
            f"requirement {document} has invalid registry path {value!r}"
        )
    return Path(*location.parts)


def _witness_location(value: Any, document: str) -> Path:
    if not isinstance(value, str):
        raise RequirementContractError(
            f"requirement {document} has invalid witness_path {value!r}"
        )
    location = Path(value)
    if (
        location.is_absolute()
        or ".." in location.parts
        or location.parent != WITNESSES_DIRECTORY
        or WITNESS_NAME.fullmatch(location.name) is None
    ):
        raise RequirementContractError(
            f"requirement {document} has invalid witness_path {value!r}"
        )
    return Path(*location.parts)

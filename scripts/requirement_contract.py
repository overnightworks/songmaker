from __future__ import annotations

import hashlib
import re
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIREMENTS_DIRECTORY = Path("docs/requirements")
REGISTRY_LOCATION = REQUIREMENTS_DIRECTORY / "revisions.toml"
ACCEPTANCE_LOCATION = Path("docs/acceptance/acceptance.toml")
PRODUCT_LOCATION = Path("docs/PRODUCT.md")
DOCUMENT_NAME = re.compile(r"^(?P<document>\d{4})-.+\.md$")
REQUIREMENT_IDENTIFIER = re.compile(r"REQ-[A-Z0-9]+-[0-9]{2}")
REQUIREMENT_HEADING = re.compile(
    r"### (?P<identifier>REQ-[A-Z0-9]+-[0-9]{2}):\s*(?P<sentence>\S.*)"
)
SOURCE_LINE = re.compile(r"Quelle: (?:OPERATOR|DESK) — \S.*")
ACCEPTANCE_IDENTIFIER = re.compile(r"ACC-[A-Z0-9]+-[0-9]{2}")
DIGEST = re.compile(r"[0-9a-f]{64}")
GENESIS = "GENESIS"
REGISTRY_FIELDS = frozenset({"schema_version", "revision"})
REVISION_FIELDS = frozenset(
    {
        "document",
        "path",
        "content_sha256",
        "approval_comment_id",
        "approval_sha256",
        "predecessor",
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
    approval_comment_id: int
    approval_sha256: str
    predecessor: str


@dataclass(frozen=True, slots=True)
class RequirementShelf:
    document_count: int
    revision_count: int
    rules: tuple[RequirementRule, ...]


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
    raw = _read_toml(project_root, REGISTRY_LOCATION)
    _exact_fields(raw, REGISTRY_FIELDS, str(REGISTRY_LOCATION))
    _schema_version(raw, REGISTRY_LOCATION)
    entries = raw.get("revision", [])
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise RequirementContractError(f"{REGISTRY_LOCATION} revision must be an array of tables")
    revisions = tuple(_revision(item) for item in entries)
    comments = [entry.approval_comment_id for entry in revisions]
    duplicate = next((comment for comment, count in Counter(comments).items() if count > 1), None)
    if duplicate is not None:
        raise RequirementContractError(
            f"approval comment {duplicate} is bound to more than one revision"
        )
    return revisions


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

    directory = _real_directory(project_root, REQUIREMENTS_DIRECTORY)
    discovered = {
        path.relative_to(project_root.resolve())
        for path in directory.iterdir()
        if DOCUMENT_NAME.fullmatch(path.name)
    }
    registered = set(location_owners)
    if missing := sorted(discovered - registered):
        raise RequirementContractError(f"requirement registry omits {', '.join(map(str, missing))}")
    if absent := sorted(registered - discovered):
        raise RequirementContractError(
            f"requirement registry names absent {', '.join(map(str, absent))}"
        )

    rules: list[RequirementRule] = []
    for document, lineage in sorted(groups.items()):
        active = _lineage_tip(document, tuple(lineage))
        rules.extend(_read_requirement_document(project_root, active))

    seen: dict[str, Path] = {}
    for rule in rules:
        if previous := seen.get(rule.identifier):
            raise RequirementContractError(
                f"{rule.located_in} publishes {rule.identifier} again; first in {previous}"
            )
        seen[rule.identifier] = rule.located_in
    return RequirementShelf(len(groups), len(revisions), tuple(rules))


def read_acceptance_manifest(
    project_root: Path, shelf: RequirementShelf
) -> tuple[AcceptanceEntry, ...]:
    raw = _read_toml(project_root, ACCEPTANCE_LOCATION)
    _exact_fields(raw, ACCEPTANCE_ROOT_FIELDS, str(ACCEPTANCE_LOCATION))
    _schema_version(raw, ACCEPTANCE_LOCATION)
    entries = raw.get("acceptance", [])
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise RequirementContractError(
            f"{ACCEPTANCE_LOCATION} acceptance must be an array of tables"
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
    comment = raw.get("approval_comment_id")
    if isinstance(comment, bool) or not isinstance(comment, int) or comment <= 0:
        raise RequirementContractError(
            f"revision {document} has invalid approval_comment_id {comment!r}"
        )
    approval_digest = _matching_text(raw, "approval_sha256", DIGEST, f"revision {document}")
    expected = hashlib.sha256(approval_bytes(document, content_digest)).hexdigest()
    if approval_digest != expected:
        raise RequirementContractError(
            f"revision {document} has approval digest {approval_digest}; expected "
            f"{expected} for the exact approval line"
        )
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
        comment,
        approval_digest,
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
        if cursor.content_sha256 in visited:
            raise RequirementContractError(f"requirement {document} has a cycle")
        visited.add(cursor.content_sha256)
        cursor = by_digest[cursor.predecessor]
    visited.add(cursor.content_sha256)
    if len(visited) != len(lineage):
        raise RequirementContractError(
            f"requirement {document} has multiple tips outside its active line"
        )
    return tip


def _read_requirement_document(project_root: Path, active: Revision) -> tuple[RequirementRule, ...]:
    content = _read_bytes(project_root, active.location)
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


def _read_toml(project_root: Path, location: Path) -> dict[str, Any]:
    content = _read_bytes(project_root, location)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RequirementContractError(f"{location} is not UTF-8") from error
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise RequirementContractError(f"{location} is unreadable: {error}") from error


def _read_bytes(project_root: Path, location: Path) -> bytes:
    return _regular_file(project_root, location).read_bytes()


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


def _schema_version(raw: dict[str, Any], location: Path) -> None:
    value = raw.get("schema_version")
    if isinstance(value, bool) or not isinstance(value, int) or value != 1:
        raise RequirementContractError(f"{location} has unsupported schema {value!r}")


def _matching_text(raw: dict[str, Any], field: str, pattern: re.Pattern[str], owner: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise RequirementContractError(f"{owner} has invalid {field} {value!r}")
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

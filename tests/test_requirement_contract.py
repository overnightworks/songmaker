from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import re
import sys
import tomllib
from collections import Counter
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
CONTRACT_PATH = PROJECT_ROOT / "scripts/requirement_contract.py"
SPECIFICATION = importlib.util.spec_from_file_location(
    "songmaker_test_requirement_contract", CONTRACT_PATH
)
assert SPECIFICATION is not None
assert SPECIFICATION.loader is not None
CONTRACT = importlib.util.module_from_spec(SPECIFICATION)
sys.modules[SPECIFICATION.name] = CONTRACT
SPECIFICATION.loader.exec_module(CONTRACT)

ACCEPTANCE_LOCATION = CONTRACT.ACCEPTANCE_LOCATION
REGISTRY_LOCATION = CONTRACT.REGISTRY_LOCATION
WITNESSES_DIRECTORY = CONTRACT.WITNESSES_DIRECTORY
EXPECTED_OPERATOR_ID = CONTRACT.EXPECTED_OPERATOR_ID
EXPECTED_REPOSITORY_FULL_NAME = CONTRACT.EXPECTED_REPOSITORY_FULL_NAME
EXPECTED_REPOSITORY_ID = CONTRACT.EXPECTED_REPOSITORY_ID
RequirementContractError = CONTRACT.RequirementContractError
approval_bytes = CONTRACT.approval_bytes
read_acceptance_manifest = CONTRACT.read_acceptance_manifest
read_requirement_shelf = CONTRACT.read_requirement_shelf


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def strict_document(
    *,
    identifier: str = "REQ-ALBUM-01",
    sentence: str = "Every song belongs to one album.",
    source: str = "Quelle: OPERATOR — issue 41",
    intent: str = "A musician can organize a coherent release.",
    non_goals: str | None = "- It does not prescribe storage.",
) -> bytes:
    ending = "" if non_goals is None else f"\n\n## Non-goals\n\n{non_goals}\n"
    return (
        "# Albums and songs\n\n"
        f"## Intent\n\n{intent}\n\n"
        f"## Rules\n\n### {identifier}: {sentence}\n{source}"
        f"{ending}"
    ).encode("utf-8")


def revision_table(
    document: str,
    path: str,
    content_digest: str,
    *,
    predecessor: str = "GENESIS",
    comment: int = 1001,
    extra: str = "",
) -> str:
    witness = witness_bytes(document, content_digest, comment)
    return (
        "[[revision]]\n"
        f'document = "{document}"\n'
        f'path = "{path}"\n'
        f'content_sha256 = "{content_digest}"\n'
        f'witness_path = "{WITNESSES_DIRECTORY}/{comment}.json"\n'
        f'witness_sha256 = "{digest(witness)}"\n'
        f'predecessor = "{predecessor}"\n'
        f"{extra}"
    )


def witness_bytes(document: str, content_digest: str, comment: int) -> bytes:
    body = approval_bytes(document, content_digest)
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


def write_registry_witnesses(project: Path, registry_text: str) -> None:
    try:
        revisions = tomllib.loads(registry_text).get("revision", [])
    except tomllib.TOMLDecodeError:
        return
    for revision in revisions:
        document = revision.get("document")
        content_digest = revision.get("content_sha256")
        witness_path = revision.get("witness_path")
        if not all(isinstance(value, str) for value in (document, content_digest, witness_path)):
            continue
        try:
            comment = int(Path(witness_path).stem)
        except ValueError:
            continue
        target = project / witness_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(witness_bytes(document, content_digest, comment))


def replace_only_witness(project: Path, content: bytes) -> None:
    target = project / WITNESSES_DIRECTORY / "1001.json"
    target.write_bytes(content)
    registry = project / REGISTRY_LOCATION
    registry.write_text(
        re.sub(
            r'witness_sha256 = "[0-9a-f]{64}"',
            f'witness_sha256 = "{digest(content)}"',
            registry.read_text(encoding="utf-8"),
        ),
        encoding="utf-8",
    )


def empty_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / REGISTRY_LOCATION).parent.mkdir(parents=True)
    (project / ACCEPTANCE_LOCATION).parent.mkdir(parents=True)
    (project / REGISTRY_LOCATION).write_text("schema_version = 2\n", encoding="utf-8")
    (project / ACCEPTANCE_LOCATION).write_text("schema_version = 1\n", encoding="utf-8")
    return project


def active_project(
    tmp_path: Path,
    *,
    content: bytes | None = None,
    registry: str | None = None,
    acceptance: str = "schema_version = 1\n",
) -> Path:
    project = empty_project(tmp_path)
    document = strict_document() if content is None else content
    location = "docs/requirements/0001-albums.md"
    (project / location).write_bytes(document)
    registry_text = registry or (
        "schema_version = 2\n\n" + revision_table("0001", location, digest(document))
    )
    (project / REGISTRY_LOCATION).write_text(registry_text, encoding="utf-8")
    write_registry_witnesses(project, registry_text)
    (project / ACCEPTANCE_LOCATION).write_text(acceptance, encoding="utf-8")
    return project


def acceptance_table(
    *,
    identifier: str = "ACC-ALBUM-01",
    text: str = "A created song appears in its album.",
    requirements: str = '["REQ-ALBUM-01"]',
    proof_kind: str = "integration",
    critical: str = "true",
    extra: str = "",
) -> str:
    return (
        "schema_version = 1\n\n"
        "[[acceptance]]\n"
        f'id = "{identifier}"\n'
        f'text = "{text}"\n'
        f"requirements = {requirements}\n"
        f'proof_kind = "{proof_kind}"\n'
        f"critical = {critical}\n"
        f"{extra}"
    )


def test_repository_contains_one_tip_per_requirement_document() -> None:
    shelf = read_requirement_shelf(PROJECT_ROOT)
    acceptance = read_acceptance_manifest(PROJECT_ROOT, shelf)

    assert shelf.document_count == 5
    revisions_per_document = Counter(revision.document for revision in shelf.revisions)
    assert revisions_per_document == Counter(
        {"0001": 1, "0002": 1, "0003": 1, "0004": 1, "0005": 2}
    )

    identifiers = {rule.identifier for rule in shelf.rules}
    assert {
        "REQ-CATALOG-01",
        "REQ-VERSION-01",
        "REQ-GENERATION-01",
        "REQ-CURATION-01",
        "REQ-CURATION-02",
        "REQ-CURATION-03",
        "REQ-CURATION-04",
        "REQ-CURATION-05",
        "REQ-CURATION-06",
    } <= identifiers
    assert [
        (entry.identifier, entry.requirements, entry.proof_kind, entry.critical)
        for entry in acceptance
    ] == [
        ("ACC-CURATION-02", ("REQ-CURATION-02",), "integration", True),
        ("ACC-COWRITER-09", ("REQ-COWRITER-09",), "integration", True),
        ("ACC-COWRITER-11", ("REQ-COWRITER-11",), "integration", True),
        ("ACC-COWRITER-12", ("REQ-COWRITER-09",), "integration", True),
        ("ACC-COWRITER-13", ("REQ-COWRITER-11",), "integration", True),
        ("ACC-COWRITER-14", ("REQ-COWRITER-12",), "integration", True),
        ("ACC-SHARE-18", ("REQ-SHARE-18",), "integration", True),
    ]


def test_repository_contains_the_active_library_listening_contract() -> None:
    shelf = read_requirement_shelf(PROJECT_ROOT)
    acceptance = read_acceptance_manifest(PROJECT_ROOT, shelf)

    identifiers = {rule.identifier for rule in shelf.rules}
    assert {
        *(f"REQ-LIBRARY-{number:02d}" for number in range(1, 9)),
        *(f"REQ-LISTENING-{number:02d}" for number in range(1, 8)),
        "REQ-PLAYER-01",
        "REQ-PLAYER-02",
    } <= identifiers
    assert [
        (entry.identifier, entry.requirements, entry.proof_kind, entry.critical)
        for entry in acceptance
    ] == [
        ("ACC-CURATION-02", ("REQ-CURATION-02",), "integration", True),
        ("ACC-COWRITER-09", ("REQ-COWRITER-09",), "integration", True),
        ("ACC-COWRITER-11", ("REQ-COWRITER-11",), "integration", True),
        ("ACC-COWRITER-12", ("REQ-COWRITER-09",), "integration", True),
        ("ACC-COWRITER-13", ("REQ-COWRITER-11",), "integration", True),
        ("ACC-COWRITER-14", ("REQ-COWRITER-12",), "integration", True),
        ("ACC-SHARE-18", ("REQ-SHARE-18",), "integration", True),
    ]


def test_a_strict_active_requirement_and_acceptance_edge_are_readable(
    tmp_path: Path,
) -> None:
    project = active_project(tmp_path, acceptance=acceptance_table())

    shelf = read_requirement_shelf(project)
    acceptance = read_acceptance_manifest(project, shelf)

    assert tuple(rule.identifier for rule in shelf.rules) == ("REQ-ALBUM-01",)
    assert acceptance[0].requirements == ("REQ-ALBUM-01",)


@pytest.mark.parametrize("relative", (REGISTRY_LOCATION, ACCEPTANCE_LOCATION))
def test_contract_toml_must_be_utf8(tmp_path: Path, relative: Path) -> None:
    project = empty_project(tmp_path)
    (project / relative).write_bytes(b"schema_version = 1\n\xff")

    if relative == REGISTRY_LOCATION:
        with pytest.raises(RequirementContractError, match="not UTF-8"):
            read_requirement_shelf(project)
    else:
        shelf = read_requirement_shelf(project)
        with pytest.raises(RequirementContractError, match="not UTF-8"):
            read_acceptance_manifest(project, shelf)


@pytest.mark.parametrize("relative", (REGISTRY_LOCATION, ACCEPTANCE_LOCATION))
def test_contract_toml_must_be_regular_not_a_symlink(tmp_path: Path, relative: Path) -> None:
    project = empty_project(tmp_path)
    target = project / relative
    outside = tmp_path / target.name
    outside.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(outside)

    if relative == REGISTRY_LOCATION:
        with pytest.raises(RequirementContractError, match="regular non-symlink"):
            read_requirement_shelf(project)
    else:
        shelf = read_requirement_shelf(project)
        with pytest.raises(RequirementContractError, match="regular non-symlink"):
            read_acceptance_manifest(project, shelf)


@pytest.mark.parametrize(
    ("registry", "problem"),
    [
        ("schema_version = 3\n", "unsupported schema"),
        ("schema_version = true\n", "unsupported schema"),
        ("schema_version = 2.0\n", "unsupported schema"),
        ("schema_version = 2\nsurprise = true\n", "unknown fields"),
        (
            'schema_version = 2\n\n[[revision]]\ndocument = "0001"\n',
            "lacks fields",
        ),
    ],
)
def test_registry_schema_refuses_unknown_or_incomplete_data(
    tmp_path: Path, registry: str, problem: str
) -> None:
    project = empty_project(tmp_path)
    (project / REGISTRY_LOCATION).write_text(registry, encoding="utf-8")

    with pytest.raises(RequirementContractError, match=problem):
        read_requirement_shelf(project)


@pytest.mark.parametrize(
    ("old", "new", "problem"),
    [
        ('document = "0001"', "document = 1", "invalid document"),
        (
            'path = "docs/requirements/0001-albums.md"',
            "path = true",
            "invalid registry path",
        ),
        ('content_sha256 = "', 'content_sha256 = "bad#', "invalid content_sha256"),
        (
            'witness_path = "docs/requirements/witnesses/1001.json"',
            "witness_path = true",
            "invalid witness_path",
        ),
        ('witness_sha256 = "', 'witness_sha256 = "bad#', "invalid witness_sha256"),
        ('predecessor = "GENESIS"', "predecessor = true", "invalid predecessor"),
    ],
)
def test_revision_field_types_fail_closed(tmp_path: Path, old: str, new: str, problem: str) -> None:
    project = active_project(tmp_path)
    registry = project / REGISTRY_LOCATION
    registry.write_text(registry.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")

    with pytest.raises(RequirementContractError, match=problem):
        read_requirement_shelf(project)


def test_revision_entries_refuse_unknown_fields(tmp_path: Path) -> None:
    project = active_project(tmp_path)
    registry = project / REGISTRY_LOCATION
    registry.write_text(
        registry.read_text(encoding="utf-8") + "surprise = true\n", encoding="utf-8"
    )

    with pytest.raises(RequirementContractError, match="unknown fields"):
        read_requirement_shelf(project)


def test_numbered_document_without_registry_tip_is_refused(tmp_path: Path) -> None:
    project = empty_project(tmp_path)
    (project / "docs/requirements/0001-unbound.md").write_bytes(strict_document())

    with pytest.raises(RequirementContractError, match="registry omits"):
        read_requirement_shelf(project)


def test_registry_path_must_exist(tmp_path: Path) -> None:
    project = active_project(tmp_path)
    (project / "docs/requirements/0001-albums.md").unlink()

    with pytest.raises(RequirementContractError, match="names absent"):
        read_requirement_shelf(project)


@pytest.mark.parametrize(
    "path",
    (
        "../0001-albums.md",
        "/docs/requirements/0001-albums.md",
        "docs/requirements/nested/0001-albums.md",
        "docs/requirements/0002-albums.md",
    ),
)
def test_registry_paths_cannot_escape_or_misname_the_document(tmp_path: Path, path: str) -> None:
    content = strict_document()
    registry = "schema_version = 2\n\n" + revision_table("0001", path, digest(content))
    project = active_project(tmp_path, content=content, registry=registry)

    with pytest.raises(RequirementContractError, match="invalid registry path"):
        read_requirement_shelf(project)


def test_numbered_document_must_be_regular_not_a_symlink(tmp_path: Path) -> None:
    project = active_project(tmp_path)
    document = project / "docs/requirements/0001-albums.md"
    outside = tmp_path / "outside.md"
    outside.write_bytes(document.read_bytes())
    document.unlink()
    document.symlink_to(outside)

    with pytest.raises(RequirementContractError, match="regular non-symlink"):
        read_requirement_shelf(project)


def test_requirement_document_must_be_utf8(tmp_path: Path) -> None:
    content = b"# Broken\n\xff"
    project = active_project(tmp_path, content=content)

    with pytest.raises(RequirementContractError, match="not UTF-8"):
        read_requirement_shelf(project)


def test_current_document_bytes_must_match_the_tip(tmp_path: Path) -> None:
    project = active_project(tmp_path)
    document = project / "docs/requirements/0001-albums.md"
    document.write_bytes(document.read_bytes() + b"\n")

    with pytest.raises(RequirementContractError, match="sole registry tip"):
        read_requirement_shelf(project)


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        (b"", "nonempty title"),
        (b"# Title\n\n## Rules\n", "invalid sections"),
        (
            b"# Title\n\ntext\n\n## Intent\n\nI\n\n## Rules\n",
            "content before Intent",
        ),
        (
            b"# Title\n\n## Rules\n\nR\n\n## Intent\n\nI\n",
            "invalid sections",
        ),
        (
            b"# Title\n\n## Intent\n\n\n## Rules\n\n",
            "empty Intent",
        ),
        (
            b"# Title\n\n## Intent\n\nI\n\n## Rules\n\n\n",
            "no requirement rule",
        ),
        (
            strict_document(non_goals=" "),
            "empty Non-goals",
        ),
        (
            strict_document(intent="### Hidden heading"),
            "heading inside Intent",
        ),
        (
            strict_document(non_goals="### Hidden heading"),
            "heading inside Non-goals",
        ),
        (
            strict_document() + b"\n## Open questions\n\nLater.\n",
            "invalid sections",
        ),
        (
            strict_document(identifier="req-album-01"),
            "unknown rule field",
        ),
        (
            strict_document(sentence=" "),
            "unknown rule field",
        ),
        (
            strict_document(source="Quelle: ROBOT — issue 41"),
            "exactly one Quelle",
        ),
        (
            strict_document(source="Quelle: OPERATOR — "),
            "exactly one Quelle",
        ),
        (
            strict_document(source="Quelle: OPERATOR — issue 41\nQuelle: DESK — issue 41"),
            "exactly one Quelle",
        ),
        (
            strict_document(source="Quelle: OPERATOR — issue 41\nStatus: active"),
            "exactly one Quelle",
        ),
    ],
)
def test_strict_document_grammar_refuses_every_unowned_shape(
    tmp_path: Path, content: bytes, problem: str
) -> None:
    project = active_project(tmp_path, content=content)
    with pytest.raises(RequirementContractError, match=problem):
        read_requirement_shelf(project)


def test_requirement_ids_are_globally_unique(tmp_path: Path) -> None:
    project = active_project(tmp_path)
    second = strict_document(sentence="A second rule reuses the identifier.")
    second_path = "docs/requirements/0002-second.md"
    (project / second_path).write_bytes(second)
    with (project / REGISTRY_LOCATION).open("a", encoding="utf-8") as registry:
        registry.write("\n" + revision_table("0002", second_path, digest(second), comment=1002))
    target = project / WITNESSES_DIRECTORY / "1002.json"
    target.write_bytes(witness_bytes("0002", digest(second), 1002))

    with pytest.raises(RequirementContractError, match="publishes REQ-ALBUM-01 again"):
        read_requirement_shelf(project)


@pytest.mark.parametrize(
    ("registry_for", "problem"),
    [
        (
            lambda current, old: revision_table(
                "0001",
                "docs/requirements/0001-albums.md",
                current,
                predecessor=current,
            ),
            "references itself",
        ),
        (
            lambda current, old: revision_table(
                "0001",
                "docs/requirements/0001-albums.md",
                current,
                predecessor=old,
            ),
            "unknown predecessor",
        ),
        (
            lambda current, old: (
                revision_table("0001", "docs/requirements/0001-albums.md", old, comment=1000)
                + "\n"
                + revision_table(
                    "0001",
                    "docs/requirements/0001-albums.md",
                    current,
                    predecessor=old,
                    comment=1001,
                )
                + "\n"
                + revision_table(
                    "0001",
                    "docs/requirements/0001-albums.md",
                    "f" * 64,
                    predecessor=old,
                    comment=1002,
                )
            ),
            "branches",
        ),
        (
            lambda current, old: (
                revision_table("0001", "docs/requirements/0001-albums.md", old, comment=1000)
                + "\n"
                + revision_table(
                    "0001",
                    "docs/requirements/0001-albums.md",
                    current,
                    comment=1001,
                )
            ),
            "multiple tips",
        ),
    ],
)
def test_revision_history_must_be_one_complete_line(
    tmp_path: Path, registry_for, problem: str
) -> None:
    content = strict_document()
    current = digest(content)
    old = digest(b"old")
    registry = "schema_version = 2\n\n" + registry_for(current, old)
    project = active_project(tmp_path, content=content, registry=registry)

    with pytest.raises(RequirementContractError, match=problem):
        read_requirement_shelf(project)


def test_revision_history_refuses_a_repeated_digest(tmp_path: Path) -> None:
    document = strict_document()
    current = digest(document)
    registry = (
        "schema_version = 2\n\n"
        + revision_table("0001", "docs/requirements/0001-albums.md", current, comment=1001)
        + "\n"
        + revision_table("0001", "docs/requirements/0001-albums.md", current, comment=1002)
    )
    project = active_project(tmp_path, content=document, registry=registry)

    with pytest.raises(RequirementContractError, match="repeats a revision"):
        read_requirement_shelf(project)


def test_revision_history_refuses_a_cycle(tmp_path: Path) -> None:
    document = strict_document()
    first = digest(b"first")
    second = digest(document)
    registry = (
        "schema_version = 2\n\n"
        + revision_table(
            "0001",
            "docs/requirements/0001-albums.md",
            first,
            predecessor=second,
            comment=1001,
        )
        + "\n"
        + revision_table(
            "0001",
            "docs/requirements/0001-albums.md",
            second,
            predecessor=first,
            comment=1002,
        )
    )
    project = active_project(tmp_path, content=document, registry=registry)

    with pytest.raises(RequirementContractError, match="has a cycle"):
        read_requirement_shelf(project)


def test_one_document_cannot_change_paths_inside_its_lineage(tmp_path: Path) -> None:
    content = strict_document()
    current = digest(content)
    old = digest(b"old")
    registry = (
        "schema_version = 2\n\n"
        + revision_table("0001", "docs/requirements/0001-old.md", old, comment=1000)
        + "\n"
        + revision_table(
            "0001",
            "docs/requirements/0001-albums.md",
            current,
            predecessor=old,
            comment=1001,
        )
    )
    project = active_project(tmp_path, content=content, registry=registry)

    with pytest.raises(RequirementContractError, match="lineage path"):
        read_requirement_shelf(project)


def test_one_approval_comment_cannot_bind_two_revisions(tmp_path: Path) -> None:
    project = active_project(tmp_path)
    second = strict_document(identifier="REQ-SONG-01")
    second_path = "docs/requirements/0002-song.md"
    (project / second_path).write_bytes(second)
    with (project / REGISTRY_LOCATION).open("a", encoding="utf-8") as registry:
        registry.write("\n" + revision_table("0002", second_path, digest(second), comment=1001))

    with pytest.raises(RequirementContractError, match="more than one revision"):
        read_requirement_shelf(project)


def test_witness_digest_must_match_the_exact_json_bytes(tmp_path: Path) -> None:
    content = strict_document()
    correct = digest(witness_bytes("0001", digest(content), 1001))
    table = revision_table("0001", "docs/requirements/0001-albums.md", digest(content)).replace(
        correct, "0" * 64
    )
    registry = "schema_version = 2\n\n" + table
    project = active_project(tmp_path, content=content, registry=registry)

    with pytest.raises(RequirementContractError, match="has digest"):
        read_requirement_shelf(project)


@pytest.mark.parametrize(
    ("field", "value", "problem"),
    [
        ("repository_id", True, "invalid repository_id"),
        ("repository_full_name", "someone/else", "repository_full_name"),
        ("issue_id", 0, "invalid issue_id"),
        ("issue_number", False, "invalid issue_number"),
        ("comment_id", 1002, "does not match comment_id"),
        ("author_id", 1, "author_id"),
        ("created_at", "not-a-time", "invalid created_at"),
        ("updated_at", "2026-08-21T12:00:01Z", "edited approval"),
        ("body_base64", "!!!", "invalid body_base64"),
        ("body_sha256", "0" * 64, "body digest"),
    ],
)
def test_witness_identity_and_body_fields_fail_closed(
    tmp_path: Path, field: str, value: object, problem: str
) -> None:
    project = active_project(tmp_path)
    target = project / WITNESSES_DIRECTORY / "1001.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload[field] = value
    replace_only_witness(
        project,
        (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )

    with pytest.raises(RequirementContractError, match=problem):
        read_requirement_shelf(project)


@pytest.mark.parametrize(
    ("mutation", "problem"),
    [("unknown", "unknown fields"), ("missing", "lacks fields")],
)
def test_witness_has_an_exact_json_schema(
    tmp_path: Path, mutation: str, problem: str
) -> None:
    project = active_project(tmp_path)
    target = project / WITNESSES_DIRECTORY / "1001.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    if mutation == "unknown":
        payload["surprise"] = True
    else:
        payload.pop("issue_id")
    replace_only_witness(
        project,
        (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )

    with pytest.raises(RequirementContractError, match=problem):
        read_requirement_shelf(project)


def test_witness_refuses_duplicate_json_keys(tmp_path: Path) -> None:
    project = active_project(tmp_path)
    target = project / WITNESSES_DIRECTORY / "1001.json"
    content = target.read_text(encoding="utf-8").replace(
        '{"author_id":', '{"schema_version":1,"author_id":', 1
    ).encode()
    replace_only_witness(project, content)

    with pytest.raises(RequirementContractError, match="repeats JSON key"):
        read_requirement_shelf(project)


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        (b"\xff", "not UTF-8"),
        (b"{", "unreadable JSON"),
        (b'{"schema_version":1,"repository_id":NaN}', "invalid JSON constant"),
    ],
)
def test_witness_normalizes_pathological_json_errors(
    tmp_path: Path, content: bytes, problem: str
) -> None:
    project = active_project(tmp_path)
    replace_only_witness(project, content)

    with pytest.raises(RequirementContractError, match=problem):
        read_requirement_shelf(project)


def test_json_reader_normalizes_excessive_nesting() -> None:
    content = b'{"nested":' + b"[" * 10_000 + b"0" + b"]" * 10_000 + b"}"

    with pytest.raises(RequirementContractError, match="unreadable JSON"):
        CONTRACT._read_json_object(content, Path("witness.json"))


def test_witness_body_must_be_the_exact_approval_line(tmp_path: Path) -> None:
    project = active_project(tmp_path)
    target = project / WITNESSES_DIRECTORY / "1001.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    wrong_body = b"APPROVE SOMETHING ELSE"
    payload["body_base64"] = base64.b64encode(wrong_body).decode("ascii")
    payload["body_sha256"] = digest(wrong_body)
    replace_only_witness(
        project,
        (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )

    with pytest.raises(RequirementContractError, match="exact approval line"):
        read_requirement_shelf(project)


def test_unregistered_or_unexpected_witness_entries_are_refused(tmp_path: Path) -> None:
    project = active_project(tmp_path)
    (project / WITNESSES_DIRECTORY / "1002.json").write_bytes(b"{}")

    with pytest.raises(RequirementContractError, match="witness registry omits"):
        read_requirement_shelf(project)

    (project / WITNESSES_DIRECTORY / "1002.json").unlink()
    (project / WITNESSES_DIRECTORY / "README.txt").write_text("not owned\n", encoding="utf-8")
    with pytest.raises(RequirementContractError, match="unexpected entries"):
        read_requirement_shelf(project)


def test_witness_must_be_a_regular_bounded_file(tmp_path: Path) -> None:
    project = active_project(tmp_path)
    target = project / WITNESSES_DIRECTORY / "1001.json"
    outside = tmp_path / "outside.json"
    outside.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(outside)

    with pytest.raises(RequirementContractError, match="regular non-symlink"):
        read_requirement_shelf(project)

    target.unlink()
    oversized = b"{" + b" " * CONTRACT.MAX_WITNESS_BYTES + b"}"
    target.write_bytes(oversized)
    replace_only_witness(project, oversized)
    with pytest.raises(RequirementContractError, match="exceeds the 4096-byte limit"):
        read_requirement_shelf(project)


def test_contract_resource_counts_and_bytes_are_bounded(tmp_path: Path) -> None:
    project = empty_project(tmp_path)
    registry = project / REGISTRY_LOCATION
    registry.write_bytes(b"schema_version = 2\n" + b" " * CONTRACT.MAX_REGISTRY_BYTES)
    with pytest.raises(RequirementContractError, match="1048576-byte limit"):
        read_requirement_shelf(project)

    registry.write_text(
        "schema_version = 2\n" + "[[revision]]\n" * (CONTRACT.MAX_REVISIONS + 1),
        encoding="utf-8",
    )
    with pytest.raises(RequirementContractError, match="maximum is 256"):
        read_requirement_shelf(project)

    registry.write_text("schema_version = 2\n", encoding="utf-8")
    acceptance = project / ACCEPTANCE_LOCATION
    acceptance.write_bytes(b"schema_version = 1\n" + b" " * CONTRACT.MAX_ACCEPTANCE_BYTES)
    shelf = read_requirement_shelf(project)
    with pytest.raises(RequirementContractError, match="1048576-byte limit"):
        read_acceptance_manifest(project, shelf)

    acceptance.write_text(
        "schema_version = 1\n" + "[[acceptance]]\n" * (CONTRACT.MAX_ACCEPTANCE_ENTRIES + 1),
        encoding="utf-8",
    )
    with pytest.raises(RequirementContractError, match="maximum is 4096"):
        read_acceptance_manifest(project, shelf)


def test_requirement_document_bytes_are_bounded(tmp_path: Path) -> None:
    oversized = b"# Oversized\n" + b"x" * CONTRACT.MAX_REQUIREMENT_BYTES
    project = active_project(tmp_path, content=oversized)

    with pytest.raises(RequirementContractError, match="262144-byte limit"):
        read_requirement_shelf(project)


@pytest.mark.parametrize(
    ("manifest", "problem"),
    [
        ("schema_version = 2\n", "unsupported schema"),
        ("schema_version = true\n", "unsupported schema"),
        ("schema_version = 1.0\n", "unsupported schema"),
        ("schema_version = 1\nunknown = true\n", "unknown fields"),
        (
            acceptance_table(extra="surprise = true\n"),
            "unknown fields",
        ),
        (
            acceptance_table().replace("critical = true\n", ""),
            "lacks fields",
        ),
        (acceptance_table(identifier="acc-album-01"), "invalid id"),
        (acceptance_table(text=" "), "invalid text"),
        (acceptance_table(requirements="[]"), "nonempty list"),
        (acceptance_table(requirements='"REQ-ALBUM-01"'), "nonempty list"),
        (
            acceptance_table(requirements='["req-album-01"]'),
            "malformed requirement",
        ),
        (
            acceptance_table(requirements='["REQ-ALBUM-01", "REQ-ALBUM-01"]'),
            "repeats a requirement edge",
        ),
        (acceptance_table(proof_kind="manual"), "unsupported proof_kind"),
        (acceptance_table(critical="1"), "invalid critical"),
        (
            acceptance_table(requirements='["REQ-MISSING-01"]'),
            "inactive requirement",
        ),
    ],
)
def test_acceptance_schema_and_edges_fail_closed(
    tmp_path: Path, manifest: str, problem: str
) -> None:
    project = active_project(tmp_path, acceptance=manifest)
    shelf = read_requirement_shelf(project)

    with pytest.raises(RequirementContractError, match=problem):
        read_acceptance_manifest(project, shelf)


def test_acceptance_ids_are_unique(tmp_path: Path) -> None:
    manifest = acceptance_table() + acceptance_table().split("schema_version = 1\n\n", 1)[1]
    project = active_project(tmp_path, acceptance=manifest)
    shelf = read_requirement_shelf(project)

    with pytest.raises(RequirementContractError, match="declared more than once"):
        read_acceptance_manifest(project, shelf)

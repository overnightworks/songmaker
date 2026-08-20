from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
CONTRACT_PATH = PROJECT_ROOT / "scripts/requirement_contract.py"
SPECIFICATION = importlib.util.spec_from_file_location("requirement_contract", CONTRACT_PATH)
assert SPECIFICATION is not None
assert SPECIFICATION.loader is not None
CONTRACT = importlib.util.module_from_spec(SPECIFICATION)
sys.modules[SPECIFICATION.name] = CONTRACT
SPECIFICATION.loader.exec_module(CONTRACT)

ACCEPTANCE_LOCATION = CONTRACT.ACCEPTANCE_LOCATION
REGISTRY_LOCATION = CONTRACT.REGISTRY_LOCATION
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
    approval_digest = digest(approval_bytes(document, content_digest))
    return (
        "[[revision]]\n"
        f'document = "{document}"\n'
        f'path = "{path}"\n'
        f'content_sha256 = "{content_digest}"\n'
        f"approval_comment_id = {comment}\n"
        f'approval_sha256 = "{approval_digest}"\n'
        f'predecessor = "{predecessor}"\n'
        f"{extra}"
    )


def empty_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / REGISTRY_LOCATION).parent.mkdir(parents=True)
    (project / ACCEPTANCE_LOCATION).parent.mkdir(parents=True)
    (project / REGISTRY_LOCATION).write_text("schema_version = 1\n", encoding="utf-8")
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
        "schema_version = 1\n\n" + revision_table("0001", location, digest(document))
    )
    (project / REGISTRY_LOCATION).write_text(registry_text, encoding="utf-8")
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


def test_repository_starts_as_an_honest_empty_contract() -> None:
    shelf = read_requirement_shelf(PROJECT_ROOT)
    acceptance = read_acceptance_manifest(PROJECT_ROOT, shelf)

    assert shelf.document_count == 0
    assert shelf.revision_count == 0
    assert shelf.rules == ()
    assert acceptance == ()


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

    with pytest.raises(RequirementContractError, match="not UTF-8"):
        if relative == REGISTRY_LOCATION:
            read_requirement_shelf(project)
        else:
            read_acceptance_manifest(project, read_requirement_shelf(project))


@pytest.mark.parametrize("relative", (REGISTRY_LOCATION, ACCEPTANCE_LOCATION))
def test_contract_toml_must_be_regular_not_a_symlink(tmp_path: Path, relative: Path) -> None:
    project = empty_project(tmp_path)
    target = project / relative
    outside = tmp_path / target.name
    outside.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(outside)

    with pytest.raises(RequirementContractError, match="regular non-symlink"):
        if relative == REGISTRY_LOCATION:
            read_requirement_shelf(project)
        else:
            read_acceptance_manifest(project, read_requirement_shelf(project))


@pytest.mark.parametrize(
    ("registry", "problem"),
    [
        ("schema_version = 2\n", "unsupported schema"),
        ("schema_version = true\n", "unsupported schema"),
        ("schema_version = 1.0\n", "unsupported schema"),
        ("schema_version = 1\nsurprise = true\n", "unknown fields"),
        (
            'schema_version = 1\n\n[[revision]]\ndocument = "0001"\n',
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
        ("approval_comment_id = 1001", "approval_comment_id = true", "approval_comment_id"),
        ('approval_sha256 = "', 'approval_sha256 = "bad#', "invalid approval_sha256"),
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
    registry = "schema_version = 1\n\n" + revision_table("0001", path, digest(content))

    with pytest.raises(RequirementContractError, match="invalid registry path"):
        active_project(tmp_path, content=content, registry=registry)
        read_requirement_shelf(tmp_path / "project")


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
    with pytest.raises(RequirementContractError, match=problem):
        read_requirement_shelf(active_project(tmp_path, content=content))


def test_requirement_ids_are_globally_unique(tmp_path: Path) -> None:
    project = active_project(tmp_path)
    second = strict_document(sentence="A second rule reuses the identifier.")
    second_path = "docs/requirements/0002-second.md"
    (project / second_path).write_bytes(second)
    with (project / REGISTRY_LOCATION).open("a", encoding="utf-8") as registry:
        registry.write("\n" + revision_table("0002", second_path, digest(second), comment=1002))

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
    registry = "schema_version = 1\n\n" + registry_for(current, old)

    with pytest.raises(RequirementContractError, match=problem):
        read_requirement_shelf(active_project(tmp_path, content=content, registry=registry))


def test_revision_history_refuses_a_repeated_digest(tmp_path: Path) -> None:
    document = strict_document()
    current = digest(document)
    registry = (
        "schema_version = 1\n\n"
        + revision_table("0001", "docs/requirements/0001-albums.md", current, comment=1001)
        + "\n"
        + revision_table("0001", "docs/requirements/0001-albums.md", current, comment=1002)
    )

    with pytest.raises(RequirementContractError, match="repeats a revision"):
        read_requirement_shelf(active_project(tmp_path, content=document, registry=registry))


def test_revision_history_refuses_a_cycle(tmp_path: Path) -> None:
    document = strict_document()
    first = digest(b"first")
    second = digest(document)
    registry = (
        "schema_version = 1\n\n"
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

    with pytest.raises(RequirementContractError, match="has a cycle"):
        read_requirement_shelf(active_project(tmp_path, content=document, registry=registry))


def test_one_document_cannot_change_paths_inside_its_lineage(tmp_path: Path) -> None:
    content = strict_document()
    current = digest(content)
    old = digest(b"old")
    registry = (
        "schema_version = 1\n\n"
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

    with pytest.raises(RequirementContractError, match="lineage path"):
        read_requirement_shelf(active_project(tmp_path, content=content, registry=registry))


def test_one_approval_comment_cannot_bind_two_revisions(tmp_path: Path) -> None:
    project = active_project(tmp_path)
    second = strict_document(identifier="REQ-SONG-01")
    second_path = "docs/requirements/0002-song.md"
    (project / second_path).write_bytes(second)
    with (project / REGISTRY_LOCATION).open("a", encoding="utf-8") as registry:
        registry.write("\n" + revision_table("0002", second_path, digest(second), comment=1001))

    with pytest.raises(RequirementContractError, match="more than one revision"):
        read_requirement_shelf(project)


def test_approval_digest_must_match_the_exact_ascii_line(tmp_path: Path) -> None:
    content = strict_document()
    correct = digest(approval_bytes("0001", digest(content)))
    table = revision_table("0001", "docs/requirements/0001-albums.md", digest(content)).replace(
        correct, "0" * 64
    )
    registry = "schema_version = 1\n\n" + table

    with pytest.raises(RequirementContractError, match="approval digest"):
        read_requirement_shelf(active_project(tmp_path, content=content, registry=registry))


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

    with pytest.raises(RequirementContractError, match="declared more than once"):
        read_acceptance_manifest(project, read_requirement_shelf(project))

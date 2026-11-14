"""Tests for ``scripts/check_refusal_keys.py``."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_refusal_keys as checker  # noqa: E402

REPOSITORY_SOURCE = Path(__file__).resolve().parents[2] / checker.DEFAULT_SOURCE

WORDS_MODULE = """
SOURCE_LANGUAGE = "en"
WORDS = {
    "en": {
        "takeRefusal.archived": "Restore this take first.",
        "modelRefusal.unavailable": "Model '{model}' is not currently available",
        "plainSentence": "A sentence without a refusal name.",
        "pageRefusal.headers": "Sent with {headers}",
        "songCount": {"one": "{count} song", "other": "{count} songs"},
    },
}
"""

REFUSAL_IMPORT = "from songmaker_cli.refusals import Refusal\n"
WORDS_IMPORT = "from songmaker_cli.words import text\n"
WORDS_MODULE_IMPORT = "from songmaker_cli import words\n"
MESSAGE_IMPORT = "from songmaker_cli.messages import message\n"


STORED_KEYS = ("takeRefusal.archived", "modelRefusal.unavailable")
MIGRATIONS = "db/migrations/versions"


def _scan(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    source: str,
    *,
    stored: tuple[str, ...] = STORED_KEYS,
    migrations: dict[str, str] | None = None,
    extra_arguments: tuple[str, ...] = (),
) -> tuple[int, str]:
    package = tmp_path / "songmaker_cli"
    package.mkdir(exist_ok=True)
    (package / "words.py").write_text(WORDS_MODULE, encoding="utf-8")
    (package / "route.py").write_text(source, encoding="utf-8")
    versions = package / MIGRATIONS
    versions.mkdir(parents=True, exist_ok=True)
    for name, content in (migrations or {}).items():
        (versions / f"{name}.py").write_text(content, encoding="utf-8")
    stored_file = tmp_path / "stored.txt"
    stored_file.write_text("".join(f"{key}\n" for key in stored), encoding="utf-8")
    code = checker.main([str(package), "--stored-keys", str(stored_file), *extra_arguments])
    return code, capsys.readouterr().out


@pytest.mark.parametrize(
    "source",
    [
        REFUSAL_IMPORT + 'Refusal(409, "takeRefusal.archived")\n',
        REFUSAL_IMPORT + 'Refusal(404, "takeRefusal.archived")\n',
        REFUSAL_IMPORT + 'Refusal(400, "modelRefusal.unavailable", model=name)\n',
        REFUSAL_IMPORT + 'Refusal(429, "takeRefusal.archived", headers=retry_after)\n',
        REFUSAL_IMPORT + 'Refusal(400, "modelRefusal.unavailable", model=name, headers=h)\n',
        WORDS_IMPORT + 'text("en", "takeRefusal.archived")\n',
        WORDS_IMPORT.replace("text", "text as sentence") + 'sentence("en", "plainSentence")\n',
        "from songmaker_cli import words\n" + 'words.text("en", "takeRefusal.archived")\n',
        "import songmaker_cli.words as w\n" + 'w.text("en", "takeRefusal.archived")\n',
        "import songmaker_cli.words\n" + 'songmaker_cli.words.text("en", "takeRefusal.archived")\n',
        MESSAGE_IMPORT + 'message("takeRefusal.archived")\n',
        MESSAGE_IMPORT + 'message("modelRefusal.unavailable", model=name)\n',
        "from songmaker_cli import messages\n" + 'messages.message("takeRefusal.archived")\n',
    ],
    ids=[
        "refusal",
        "not-found-refusal",
        "refusal-with-gap",
        "refusal-with-headers",
        "refusal-with-gap-and-headers",
        "text-by-import",
        "text-by-alias",
        "text-on-words-module",
        "text-on-aliased-module",
        "text-on-dotted-module",
        "message-by-import",
        "message-with-gap",
        "message-on-messages-module",
    ],
)
def test_a_call_with_a_plain_key_and_its_gaps_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], source: str
) -> None:
    code, output = _scan(tmp_path, capsys, source)

    assert code == 0, output
    assert "calls=1, violations=0" in output


@pytest.mark.parametrize(
    ("source", "problem"),
    [
        (REFUSAL_IMPORT + 'Refusal(409, "takeRefusal.gone")\n', "not a plain entry"),
        (REFUSAL_IMPORT + 'Refusal(409, "songCount")\n', "not a plain entry"),
        (REFUSAL_IMPORT + "Refusal(409, key)\n", "not a string literal"),
        (REFUSAL_IMPORT + 'Refusal(409, f"take{kind}")\n', "not a string literal"),
        (REFUSAL_IMPORT + "Refusal(409)\n", "not a string literal"),
        (REFUSAL_IMPORT + 'Refusal(409, "plainSentence")\n', "does not match"),
        (REFUSAL_IMPORT + 'Refusal(code, "takeRefusal.archived")\n', "not an int literal"),
        (REFUSAL_IMPORT + 'Refusal(True, "takeRefusal.archived")\n', "not an int literal"),
        (REFUSAL_IMPORT + 'Refusal(400, "modelRefusal.unavailable")\n', "missing ['model']"),
        (
            REFUSAL_IMPORT + 'Refusal(400, "modelRefusal.unavailable", model=m, other=o)\n',
            "unexpected ['other']",
        ),
        (REFUSAL_IMPORT + 'Refusal(400, "modelRefusal.unavailable", **gaps)\n', "** spread"),
        (
            REFUSAL_IMPORT + 'Refusal(409, "takeRefusal.archived", count=2)\n',
            "unexpected ['count']",
        ),
        (
            REFUSAL_IMPORT + 'Refusal(400, "pageRefusal.headers", headers=h)\n',
            "may not be named headers",
        ),
        (WORDS_IMPORT + 'text("en", "takeRefusal.gone")\n', "not a plain entry"),
        (WORDS_IMPORT + 'text("en", key)\n', "not a string literal"),
        (WORDS_IMPORT + 'text("en", "modelRefusal.unavailable")\n', "missing ['model']"),
        (WORDS_MODULE_IMPORT + 'words.text("en", "songCount", count=2)\n', "plain entry"),
        (MESSAGE_IMPORT + "message(key)\n", "not a string literal"),
        (MESSAGE_IMPORT + 'message("takeRefusal.gone")\n', "not a plain entry"),
        (MESSAGE_IMPORT + 'message("modelRefusal.unavailable")\n', "missing ['model']"),
        (MESSAGE_IMPORT + 'message("takeRefusal.archived", count=2)\n', "unexpected ['count']"),
        (MESSAGE_IMPORT + 'message("modelRefusal.unavailable", **gaps)\n', "** spread"),
    ],
    ids=[
        "unknown-key",
        "plural-family-key",
        "non-literal-key",
        "formatted-key",
        "key-missing",
        "key-without-refusal-suffix",
        "non-literal-status",
        "bool-status",
        "missing-gap",
        "extra-gap",
        "gap-spread",
        "count-on-a-plain-key",
        "gap-named-headers",
        "text-unknown-key",
        "text-non-literal-key",
        "text-missing-gap",
        "text-plural-family-key",
        "message-non-literal-key",
        "message-unknown-key",
        "message-missing-gap",
        "message-extra-gap",
        "message-gap-spread",
    ],
)
def test_a_call_breaking_the_contract_is_reported_with_its_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], source: str, problem: str
) -> None:
    code, output = _scan(tmp_path, capsys, source)

    assert code == 1
    assert "route.py:2:" in output
    assert problem in output


def test_sqlalchemy_text_is_not_a_catalog_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = 'from sqlalchemy import text\nstatement = text("select 1")\n'

    code, output = _scan(tmp_path, capsys, source)

    assert code == 0, output
    assert "calls=0, violations=0" in output


def test_a_catalog_text_call_beside_sqlalchemy_text_is_the_only_one_counted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = (
        "from sqlalchemy import text\nfrom songmaker_cli import words\n"
        'statement = text("select 1")\nsentence = words.text("en", "plainSentence")\n'
    )

    code, output = _scan(tmp_path, capsys, source)

    assert code == 0, output
    assert "calls=1, violations=0" in output


RAW_IMPORT = "from fastapi import HTTPException\n"


def _unread_counts(output: str) -> dict[str, int]:
    tags = re.findall(r"(\w+)=(\d+)", output.split("unread:")[1])
    return {tag: int(count) for tag, count in tags}


@pytest.mark.parametrize(
    "source",
    [
        RAW_IMPORT + 'raise HTTPException(404, "Gone")  # unread: media\n',
        RAW_IMPORT + 'raise HTTPException(\n    429, "Slow",  # unread: share\n    headers=h,\n)\n',
        "import fastapi\n" + 'raise fastapi.HTTPException(401, "No")  # unread: session\n',
    ],
    ids=["one-line", "multi-line", "attribute"],
)
def test_a_marked_raw_exception_passes_and_is_counted_under_its_tag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], source: str
) -> None:
    code, output = _scan(tmp_path, capsys, source)

    assert code == 0, output
    assert "violations=0" in output
    assert sum(_unread_counts(output).values()) == 1


def test_the_summary_counts_every_tag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = RAW_IMPORT + "".join(
        f'raise HTTPException(404, "Gone")  # unread: {tag}\n' for tag in checker.UNREAD_TAGS
    )

    code, output = _scan(tmp_path, capsys, source)

    assert code == 0, output
    assert _unread_counts(output) == dict.fromkeys(checker.UNREAD_TAGS, 1)


@pytest.mark.parametrize(
    ("source", "problem"),
    [
        (RAW_IMPORT + 'raise HTTPException(404, "Gone")\n', "answers English only"),
        (RAW_IMPORT + 'raise HTTPException(404)  # unread: whatever\n', "unknown unread tag"),
        (RAW_IMPORT + 'raise HTTPException(404, "Gone")  # unread:\n', "unknown unread tag"),
        (
            RAW_IMPORT + 'raise HTTPException(  # unread: media\n    404  # unread: typo\n)\n',
            "unknown unread tag 'typo'",
        ),
        (
            RAW_IMPORT + 'raise HTTPException(\n    404, "Gone",\n)\n# unread: media\n',
            "answers English only",
        ),
        (RAW_IMPORT + 'x = 1  # unread: media\n' + 'raise HTTPException(404)  # unread: sse\n',
         "marks no raw HTTPException call"),
    ],
    ids=[
        "unmarked", "unknown-tag", "empty-tag", "second-marker-unknown",
        "marker-below-the-call", "orphan-marker",
    ],
)
def test_a_raw_exception_without_a_known_tag_or_a_marker_without_a_call_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], source: str, problem: str
) -> None:
    code, output = _scan(tmp_path, capsys, source)

    assert code == 1
    assert "route.py:2:" in output
    assert problem in output


def test_a_missing_words_module_stops_the_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = checker.main([str(tmp_path / "songmaker_cli")])

    assert code == 2
    assert "words.py does not exist" in capsys.readouterr().err


def test_the_repository_source_passes(capsys: pytest.CaptureFixture[str]) -> None:
    code = checker.main([str(REPOSITORY_SOURCE)])

    assert code == 0, capsys.readouterr().out


def _migration(revision: str, down: str | None, *, table: dict | None = None,
               retired: tuple[str, ...] | None = None) -> str:
    lines = [f'revision: str = "{revision}"', f"down_revision: str | None = {down!r}"]
    if table is not None:
        lines.append(f"STORED_MESSAGE_KEYS: dict[str, str] = {table!r}")
    if retired is not None:
        lines.append(f"RETIRED_STORED_KEYS = frozenset({set(retired)!r})")
    return "\n".join(lines) + "\n"


def test_a_message_key_missing_from_the_stored_set_is_reported_with_its_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, output = _scan(
        tmp_path, capsys, MESSAGE_IMPORT + 'message("takeRefusal.archived")\n', stored=()
    )

    assert code == 1
    assert "route.py:2:" in output
    assert "'takeRefusal.archived' is stored by message() but not in stored.txt" in output


def test_a_migration_key_missing_from_the_stored_set_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    migrations = {"a1": _migration("a1", None, table={"Wait.": "takeRefusal.archived"})}

    code, output = _scan(tmp_path, capsys, "", stored=(), migrations=migrations)

    assert code == 1
    assert "'takeRefusal.archived' is stored by the migration but not in stored.txt" in output


def test_a_migration_key_a_later_migration_retires_may_leave_the_stored_set(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    migrations = {
        "a1": _migration("a1", None, table={"Wait.": "takeRefusal.archived"}),
        "a2": _migration("a2", "a1", retired=("takeRefusal.archived",)),
    }

    code, output = _scan(tmp_path, capsys, "", stored=(), migrations=migrations)

    assert code == 0, output


def test_a_migration_key_retired_only_by_an_earlier_migration_is_still_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    migrations = {
        "a1": _migration("a1", None, retired=("takeRefusal.archived",)),
        "a2": _migration("a2", "a1", table={"Wait.": "takeRefusal.archived"}),
    }

    code, output = _scan(tmp_path, capsys, "", stored=(), migrations=migrations)

    assert code == 1
    assert "'takeRefusal.archived' is stored by the migration" in output


def test_a_writer_key_a_migration_retires_is_still_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    migrations = {"a1": _migration("a1", None, retired=("takeRefusal.archived",))}

    code, output = _scan(
        tmp_path, capsys, MESSAGE_IMPORT + 'message("takeRefusal.archived")\n',
        stored=(), migrations=migrations,
    )

    assert code == 1
    assert "'takeRefusal.archived' is stored by message()" in output


@pytest.mark.parametrize(
    ("key", "problem"),
    [
        ("ghostWait.never", "is not a plain entry of words.py"),
        ("plainSentence", "does not match <resource>(Failure|Wait|Refusal).<reason>"),
        ("songCount", "is not a plain entry of words.py"),
    ],
    ids=["unknown-key", "key-of-another-form", "plural-family"],
)
def test_a_key_of_the_stored_set_must_be_a_plain_entry_of_the_stored_form(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], key: str, problem: str
) -> None:
    code, output = _scan(tmp_path, capsys, "", stored=(key,))

    assert code == 1
    assert f"{key!r} {problem}" in output


def _git(directory: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
         *arguments],
        cwd=directory, capture_output=True, text=True, check=True,
    ).stdout.strip()


def _commit_stored_keys(directory: Path, *keys: str) -> str:
    if not (directory / ".git").exists():
        _git(directory, "init", "-q")
    (directory / "stored.txt").write_text("".join(f"{key}\n" for key in keys), encoding="utf-8")
    _git(directory, "add", "-A")
    _git(directory, "commit", "-q", "--allow-empty", "-m", "base")
    return _git(directory, "rev-parse", "HEAD")


def _scan_against(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], base_sha: str,
    *, stored: tuple[str, ...], retiring: tuple[str, ...] | None = None,
) -> tuple[int, str]:
    migrations = None
    if retiring is not None:
        migrations = {"a2": _migration("a2", "a1", retired=retiring)}
        versions = tmp_path / "songmaker_cli" / MIGRATIONS
        versions.mkdir(parents=True)
        (versions / "a2.py").write_text(migrations["a2"], encoding="utf-8")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "the pull request adds a migration")
    return _scan(
        tmp_path, capsys, "", stored=stored, migrations=migrations,
        extra_arguments=("--base-sha", base_sha),
    )


def test_a_key_dropped_from_the_set_since_the_base_is_reported_without_a_retiring_migration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _commit_stored_keys(tmp_path, *STORED_KEYS)

    code, output = _scan_against(tmp_path, capsys, base, stored=STORED_KEYS[:1])

    assert code == 1
    assert f"{STORED_KEYS[1]!r} left the set since" in output


def test_a_key_dropped_from_the_set_passes_when_a_migration_the_diff_adds_retires_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _commit_stored_keys(tmp_path, *STORED_KEYS)

    code, output = _scan_against(
        tmp_path, capsys, base, stored=STORED_KEYS[:1], retiring=STORED_KEYS[1:]
    )

    assert code == 0, output


def test_a_key_dropped_by_a_migration_the_base_already_had_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    versions = tmp_path / "songmaker_cli" / MIGRATIONS
    versions.mkdir(parents=True)
    (versions / "a2.py").write_text(
        _migration("a2", "a1", retired=STORED_KEYS[1:]), encoding="utf-8"
    )
    (tmp_path / "songmaker_cli" / "words.py").write_text(WORDS_MODULE, encoding="utf-8")
    base = _commit_stored_keys(tmp_path, *STORED_KEYS)

    code, output = _scan_against(tmp_path, capsys, base, stored=STORED_KEYS[:1])

    assert code == 1
    assert f"{STORED_KEYS[1]!r} left the set since" in output


def test_a_base_without_a_stored_set_drops_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")

    code, output = _scan_against(tmp_path, capsys, base, stored=STORED_KEYS)

    assert code == 0, output


def test_an_unresolvable_base_commit_is_red(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _commit_stored_keys(tmp_path, *STORED_KEYS)

    code, output = _scan_against(tmp_path, capsys, "0" * 40, stored=STORED_KEYS)

    assert code == 1
    assert "cannot be resolved" in output


def test_without_a_base_commit_only_the_local_rules_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, output = _scan(tmp_path, capsys, "", stored=STORED_KEYS)

    assert code == 0, output

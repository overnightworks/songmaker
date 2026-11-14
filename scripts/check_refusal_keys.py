"""CI check that every server refusal names a plain catalog key with exactly its gaps, and that
every raw `HTTPException` is one no person reads.

Run from the project root:

    python scripts/check_refusal_keys.py

It walks `src/songmaker_cli` for every `Refusal(...)` call and every call of
`songmaker_cli.words.text` and `songmaker_cli.messages.message` (by import, or as the
`words.text` and `messages.message` attributes; SQLAlchemy's `text` is another function and
is not counted). It reads the entries of the generated
`words.py` and requires, for each call:

* the key is a string literal that is a plain entry of the source language, not a plural
  family;
* the keywords are exactly the sentence's gaps, with no `**` spread.

A `Refusal` call also needs an int literal status and a key of the form
`<resource>Refusal.<reason>`. It may add the keyword `headers=` for response headers, which is
no gap, so a sentence may not name a gap `headers`.

Every `HTTPException(...)` call (by name or attribute) carries a `# unread: <tag>` comment on one
of its lines, the tag naming why no person reads its English answer. An unmarked call, an
unknown tag and a marker with no such call on its lines fail.

`words.py` (generated), `messages.py` and `refusals.py` (which forward the key of their caller
to `text` and `message`) are not walked.

A `message(...)` key is a stored one: a row of the database may hold it long after the code that
wrote it has changed. `scripts/stored_message_keys.txt` (`--stored-keys`) lists every stored key,
one per line, and the check holds three rules over it:

* (a) every key a `message(...)` call or a migration's `STORED_MESSAGE_KEYS` table (sentence to
  key) can store is in the set; a key a later migration of the chain lists in its
  `RETIRED_STORED_KEYS` is left out of the earlier migration's table;
* (b) every key in the set is a plain entry of the source language of the form
  `<resource>(Failure|Wait|Refusal).<reason>` or `coverProblem.<reason>`;
* (c) with `--base-sha` (CI passes the pull request's base commit, as the quality gate reads it;
  an unresolvable commit fails), a key the set lost since that commit is in the
  `RETIRED_STORED_KEYS` of a migration the diff adds. Locally (a) and (b) run alone.
"""
# ruff: noqa: T201 - this check reports its violations on stdout

from __future__ import annotations

import argparse
import ast
import importlib.util
import io
import re
import subprocess
import sys
import tokenize
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from string import Formatter
from typing import Final

DEFAULT_SOURCE: Final = "src/songmaker_cli"
WORDS_FILE: Final = "words.py"
REFUSALS_FILE: Final = "refusals.py"
MESSAGES_FILE: Final = "messages.py"
PACKAGE_MODULE: Final = "songmaker_cli"
WORDS_NAME: Final = "words"
TEXT_NAME: Final = "text"
MESSAGES_NAME: Final = "messages"
MESSAGE_NAME: Final = "message"
REFUSAL_NAME: Final = "Refusal"
REFUSAL_KEY_PATTERN: Final = re.compile(r"^[a-z][A-Za-z0-9]*Refusal\.[a-z][A-Za-z0-9]*$")
KEY_INDEX_OF_TEXT: Final = 1
KEY_INDEX_OF_MESSAGE: Final = 0
KEY_INDEX_OF_REFUSAL: Final = 1
STORED_KEYS_FILE: Final = Path(__file__).with_name("stored_message_keys.txt")
MIGRATIONS_DIRECTORY: Final = "db/migrations/versions"
STORED_TABLE_NAME: Final = "STORED_MESSAGE_KEYS"
RETIRED_NAME: Final = "RETIRED_STORED_KEYS"
COMMIT_ID_PATTERN: Final = r"[0-9a-f]{40}|[0-9a-f]{64}"
# why: the stored keys of a failure, a wait or a refusal, and the cover problems the page already
# words under `coverProblem`, which the cover job stores as they are.
STORED_KEY_PATTERN: Final = re.compile(
    r"^(?:[a-z][A-Za-z0-9]*(?:Failure|Wait|Refusal)|coverProblem)\.[a-z][A-Za-z0-9]*$"
)
REFUSAL_HEADERS_KEYWORD: Final = "headers"
HTTP_EXCEPTION_NAME: Final = "HTTPException"
UNREAD_MARKER: Final = re.compile(r"#\s*unread:\s*(?P<tag>\S*)")
UNREAD_TAGS: Final = (
    "share",  # public share routes, the public queue-stream build, the shared-access 429
    "media",  # media and static-file fetches
    "sse",  # EventSource streams
    "machine",  # health and internal answers
    "session",  # the 401 that ends a session
    "token",  # a body whose detail is a typed token the page words from the catalog
)


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    message: str


@dataclass(frozen=True)
class MessageKey:
    """The literal key of one `message(...)` call."""

    path: str
    line: int
    key: str


@dataclass
class FileScan:
    violations: list[Violation] = field(default_factory=list)
    checked: int = 0
    unread: Counter[str] = field(default_factory=Counter)
    message_keys: list[MessageKey] = field(default_factory=list)


def load_plain_gaps(words_file: Path) -> dict[str, frozenset[str]]:
    """Map each plain entry of the source language to the names of its gaps."""
    spec = importlib.util.spec_from_file_location("generated_words", words_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {words_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source_entries = module.WORDS[module.SOURCE_LANGUAGE]
    return {
        key: frozenset(name for _, name, _, _ in Formatter().parse(sentence) if name is not None)
        for key, sentence in source_entries.items()
        if isinstance(sentence, str)
    }


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return None if base is None else f"{base}.{node.attr}"
    return None


@dataclass(frozen=True)
class FunctionBindings:
    """The names a module binds to one function of a leaf module, and to that leaf module."""

    function: str
    functions: frozenset[str]
    modules: frozenset[str]

    def is_call(self, call: ast.Call) -> bool:
        if isinstance(call.func, ast.Name):
            return call.func.id in self.functions
        if isinstance(call.func, ast.Attribute) and call.func.attr == self.function:
            return _dotted(call.func.value) in self.modules
        return False


def _from_import_names(tree: ast.Module, module: str, name: str) -> set[str]:
    return {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == module
        for alias in node.names
        if alias.name == name
    }


def _import_names(tree: ast.Module, module: str) -> set[str]:
    return {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == module
    }


def function_bindings(tree: ast.Module, leaf: str, function: str) -> FunctionBindings:
    """The bindings of `songmaker_cli.<leaf>.<function>` in a module."""
    module = f"{PACKAGE_MODULE}.{leaf}"
    return FunctionBindings(
        function=function,
        functions=frozenset(_from_import_names(tree, module, function)),
        modules=frozenset(
            _from_import_names(tree, PACKAGE_MODULE, leaf) | _import_names(tree, module)
        ),
    )


def _is_refusal_call(call: ast.Call) -> bool:
    if isinstance(call.func, ast.Name):
        return call.func.id == REFUSAL_NAME
    return isinstance(call.func, ast.Attribute) and call.func.attr == REFUSAL_NAME


def _literal_key(call: ast.Call, key_index: int) -> str | None:
    if len(call.args) <= key_index:
        return None
    key = call.args[key_index]
    if isinstance(key, ast.Constant) and isinstance(key.value, str):
        return key.value
    return None


def _gap_problem(call: ast.Call, expected: frozenset[str], *, is_refusal: bool) -> str | None:
    if any(keyword.arg is None for keyword in call.keywords):
        return "gaps are passed with a ** spread; name each one"
    given = {keyword.arg for keyword in call.keywords}
    if is_refusal:
        if REFUSAL_HEADERS_KEYWORD in expected:
            return f"a gap may not be named {REFUSAL_HEADERS_KEYWORD}: Refusal takes it as headers"
        given.discard(REFUSAL_HEADERS_KEYWORD)
    missing, unexpected = sorted(expected - given), sorted(given - expected)
    if missing or unexpected:
        return f"gaps differ from the sentence's: missing {missing}, unexpected {unexpected}"
    return None


def _refusal_problem(call: ast.Call, key: str) -> str | None:
    status = call.args[0]
    if not (isinstance(status, ast.Constant) and type(status.value) is int):
        return "the status is not an int literal"
    if not REFUSAL_KEY_PATTERN.match(key):
        return f"{key!r} does not match <resource>Refusal.<reason>"
    return None


def call_problem(
    call: ast.Call, key_index: int, plain: dict[str, frozenset[str]], *, is_refusal: bool
) -> str | None:
    key = _literal_key(call, key_index)
    if key is None:
        return "the key is not a string literal passed as a positional argument"
    if key not in plain:
        return f"{key!r} is not a plain entry of words.py (a plural family is not a refusal key)"
    problem = _gap_problem(call, plain[key], is_refusal=is_refusal)
    if problem is not None or not is_refusal:
        return problem
    return _refusal_problem(call, key)


def _is_http_exception_call(call: ast.Call) -> bool:
    if isinstance(call.func, ast.Name):
        return call.func.id == HTTP_EXCEPTION_NAME
    return isinstance(call.func, ast.Attribute) and call.func.attr == HTTP_EXCEPTION_NAME


def _unread_markers(source: str) -> dict[int, str]:
    """Map each line holding a `# unread: <tag>` comment to its tag."""
    return {
        token.start[0]: match.group("tag")
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT and (match := UNREAD_MARKER.search(token.string))
    }


def _unread_problem(
    call: ast.Call, markers: dict[int, str]
) -> tuple[str | None, str | None]:
    """The tag a raw call is marked with, and the problem when it has none or an unknown one."""
    end_line = call.end_lineno or call.lineno
    tags = [markers[line] for line in range(call.lineno, end_line + 1) if line in markers]
    if not tags:
        return None, (
            f"a raw {HTTP_EXCEPTION_NAME} answers English only; raise a Refusal, or mark a "
            "no-reader answer with '# unread: <tag>'"
        )
    unknown = next((tag for tag in tags if tag not in UNREAD_TAGS), None)
    if unknown is not None:
        return None, f"unknown unread tag {unknown!r}; the tags are {list(UNREAD_TAGS)}"
    return tags[0], None


def _listed(value: str | None) -> list[str]:
    """The value as a list of zero or one entry."""
    return [] if value is None else [value]


def _key_problem(
    call: ast.Call,
    text_bindings: FunctionBindings,
    message_bindings: FunctionBindings,
    plain: dict[str, frozenset[str]],
) -> tuple[bool, str | None]:
    """Whether the call is a refusal, text or message call, and the problem with its key."""
    if _is_refusal_call(call):
        return True, call_problem(call, KEY_INDEX_OF_REFUSAL, plain, is_refusal=True)
    if text_bindings.is_call(call):
        return True, call_problem(call, KEY_INDEX_OF_TEXT, plain, is_refusal=False)
    if message_bindings.is_call(call):
        return True, call_problem(call, KEY_INDEX_OF_MESSAGE, plain, is_refusal=False)
    return False, None


def check_file(path: Path, shown: str, plain: dict[str, frozenset[str]]) -> FileScan:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=shown)
    text_bindings = function_bindings(tree, WORDS_NAME, TEXT_NAME)
    message_bindings = function_bindings(tree, MESSAGES_NAME, MESSAGE_NAME)
    markers = _unread_markers(source)
    scan = FileScan()
    raw_lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_http_exception_call(node):
            raw_lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
            tag, problem = _unread_problem(node, markers)
            scan.unread.update(_listed(tag))
            scan.violations.extend(Violation(shown, node.lineno, text) for text in _listed(problem))
            continue
        is_checked, problem = _key_problem(node, text_bindings, message_bindings, plain)
        if not is_checked:
            continue
        scan.checked += 1
        if problem is not None:
            scan.violations.append(Violation(shown, node.lineno, problem))
        key = _literal_key(node, KEY_INDEX_OF_MESSAGE)
        if message_bindings.is_call(node) and key is not None:
            scan.message_keys.append(MessageKey(shown, node.lineno, key))
    scan.violations.extend(
        Violation(shown, line, f"'# unread: {tag}' marks no raw {HTTP_EXCEPTION_NAME} call")
        for line, tag in markers.items()
        if line not in raw_lines
    )
    return scan


@dataclass(frozen=True)
class Migration:
    """One migration: its place in the chain and the stored keys it names."""

    path: Path
    revision: str
    down_revisions: tuple[str, ...]
    table_keys: tuple[str, ...]
    retired_keys: frozenset[str]


def _module_value(tree: ast.Module, name: str) -> ast.expr | None:
    """The value assigned to a module-level name, or None."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return node.value
        if isinstance(node, ast.AnnAssign) and _dotted(node.target) == name:
            return node.value
    return None


def _literal(tree: ast.Module, name: str) -> object:
    """The literal a module-level name is assigned, with `frozenset(...)` read as its argument."""
    value = _module_value(tree, name)
    if value is None:
        return None
    if isinstance(value, ast.Call) and _dotted(value.func) == "frozenset" and len(value.args) == 1:
        value = value.args[0]
    try:
        return ast.literal_eval(value)
    except ValueError:
        return None


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (tuple, list, set, frozenset)):
        return [item for item in value if isinstance(item, str)]
    return []


def read_migration(path: Path) -> Migration:
    """The migration's chain place and the stored keys it names, none for an ordinary migration."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    table = _literal(tree, STORED_TABLE_NAME)
    retired = _literal(tree, RETIRED_NAME)
    revision = _strings(_literal(tree, "revision"))
    return Migration(
        path=path,
        revision=revision[0] if revision else path.stem,
        down_revisions=tuple(_strings(_literal(tree, "down_revision"))),
        table_keys=tuple(_strings(list(table.values()))) if isinstance(table, dict) else (),
        retired_keys=frozenset(_strings(retired)),
    )


def _ancestors(migration: Migration, by_revision: dict[str, Migration]) -> set[str]:
    """Every revision behind a migration on the chain."""
    found: set[str] = set()
    pending = list(migration.down_revisions)
    while pending:
        revision = pending.pop()
        if revision in found:
            continue
        found.add(revision)
        if revision in by_revision:
            pending.extend(by_revision[revision].down_revisions)
    return found


def migrations_in(directory: Path) -> list[Migration]:
    if not directory.is_dir():
        return []
    return [read_migration(path) for path in sorted(directory.glob("*.py"))]


def read_stored_keys(text: str) -> set[str]:
    return {line.strip() for line in text.splitlines() if line.strip()}


def _unlisted_problems(
    keys: Iterable[MessageKey], migrations: list[Migration], stored: set[str], file_shown: str
) -> list[Violation]:
    """Rule (a): a key a writer or a migration can store, and the set lacks."""
    by_revision = {migration.revision: migration for migration in migrations}
    problems = [
        Violation(key.path, key.line, f"{key.key!r} is stored by message() but not in {file_shown}")
        for key in keys
        if key.key not in stored
    ]
    for migration in migrations:
        retired_later = {
            key
            for later in migrations
            if migration.revision in _ancestors(later, by_revision)
            for key in later.retired_keys
        }
        problems.extend(
            Violation(
                str(migration.path), 1,
                f"{key!r} is stored by the migration but not in {file_shown}",
            )
            for key in migration.table_keys
            if key not in stored and key not in retired_later
        )
    return problems


def _set_problems(
    stored: set[str], plain: dict[str, frozenset[str]], file_shown: str
) -> list[Violation]:
    """Rule (b): a key of the set that is no plain source-language entry of the stored form."""
    problems = []
    for key in sorted(stored):
        if key not in plain:
            problems.append(Violation(file_shown, 1, f"{key!r} is not a plain entry of words.py"))
        elif not STORED_KEY_PATTERN.match(key):
            problems.append(
                Violation(
                    file_shown, 1,
                    f"{key!r} does not match <resource>(Failure|Wait|Refusal).<reason> "
                    "or coverProblem.<reason>",
                )
            )
    return problems


def _commit_id(text: str) -> str | None:
    """The full commit id ``text`` spells, rebuilt from its number so no raw argument reaches git."""
    if not re.fullmatch(COMMIT_ID_PATTERN, text):
        return None
    return f"{int(text, 16):0{len(text)}x}"


def _git(directory: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed git subcommands; the only input is a full commit id
        ["git", *arguments],  # noqa: S607 - git is found on PATH like in every other CI step
        cwd=directory, capture_output=True, text=True, check=False,
    )


def _base_problems(
    base_sha: str, stored_file: Path, stored: set[str], migrations_directory: Path
) -> list[Violation]:
    """Rule (c): a key the set lost since the base commit, and no added migration retires."""
    shown = str(stored_file)
    directory = stored_file.parent
    commit_id = _commit_id(base_sha)
    if commit_id is None or _git(
        directory, "rev-parse", "--verify", "--quiet", f"{commit_id}^{{commit}}"
    ).returncode:
        problem = f"the base commit {base_sha} cannot be resolved; fetch the history"
        return [Violation(shown, 1, problem)]
    base = _git(directory, "show", f"{commit_id}:./{stored_file.name}")
    dropped = (read_stored_keys(base.stdout) if base.returncode == 0 else set()) - stored
    if not dropped:
        return []
    added = _git(
        migrations_directory, "diff", "--name-only", "--relative", "--diff-filter=A",
        commit_id, "HEAD", "--", ".",
    )
    retired = {
        key
        for name in added.stdout.split()
        if name.endswith(".py")
        for key in read_migration(migrations_directory / name).retired_keys
    }
    return [
        Violation(shown, 1, f"{key!r} left the set since {base_sha[:12]}; "
                  f"an added migration lists it in {RETIRED_NAME}")
        for key in sorted(dropped - retired)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", default=DEFAULT_SOURCE, help="package to scan")
    parser.add_argument("--stored-keys", type=Path, default=STORED_KEYS_FILE)
    parser.add_argument("--base-sha", default="", help="the pull request's base commit (CI)")
    arguments = parser.parse_args(argv)
    source = Path(arguments.source)
    words_file = source / WORDS_FILE
    if not words_file.is_file():
        print(f"error: {words_file} does not exist", file=sys.stderr)
        return 2
    plain = load_plain_gaps(words_file)
    scans = [
        check_file(path, str(path), plain)
        for path in sorted(source.rglob("*.py"))
        if path not in (words_file, source / REFUSALS_FILE, source / MESSAGES_FILE)
    ]
    violations = [violation for scan in scans for violation in scan.violations]
    unread: Counter[str] = Counter()
    for scan in scans:
        unread.update(scan.unread)
    stored_file: Path = arguments.stored_keys
    stored = read_stored_keys(stored_file.read_text(encoding="utf-8"))
    migrations_directory = source / MIGRATIONS_DIRECTORY
    violations += _unlisted_problems(
        (key for scan in scans for key in scan.message_keys),
        migrations_in(migrations_directory), stored, stored_file.name,
    )
    violations += _set_problems(stored, plain, stored_file.name)
    if arguments.base_sha:
        violations += _base_problems(arguments.base_sha, stored_file, stored, migrations_directory)
    for violation in violations:
        print(f"{violation.path}:{violation.line}: {violation.message}")
    per_tag = ", ".join(f"{tag}={unread[tag]}" for tag in UNREAD_TAGS)
    print(
        f"checked: refusal, text and message calls={sum(scan.checked for scan in scans)}, "
        f"violations={len(violations)}; unread: {per_tag}"
    )
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())

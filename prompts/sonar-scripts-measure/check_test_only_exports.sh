#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

python3 - "$@" <<'PY'
import re
import subprocess
import sys
from collections import defaultdict
from fnmatch import fnmatchcase
from pathlib import Path

export_pattern = re.compile(
    r"^export\s+(?:declare\s+)?(?:async\s+)?(?:const\s+enum|const|let|function|abstract\s+class|class|type|interface|enum)\s+([A-Za-z_$][A-Za-z0-9_$]*)",
    re.MULTILINE,
)
brace_export_pattern = re.compile(r"^export\s+(?:type\s+)?\{([^}]+)\}", re.MULTILINE)
star_export_pattern = re.compile(r"^export\s+(?:type\s+)?\*\s+from\s*['\"]", re.MULTILINE)
default_export_pattern = re.compile(r"^export\s+default\b", re.MULTILINE)
default_import_pattern = re.compile(
    r"(?:import\s+(?:[A-Za-z_$][\w$]*\s*(?:,\s*(?:\{[^}]*\}|\*\s+as\s+\w+))?"
    r"|\{[^}]*\bdefault\s+as\b[^}]*\})"
    r"|export\s+\{[^}]*\bdefault\b[^}]*\})\s+from\s*['\"]([^'\"]+)['\"]"
)


def exported_names(source):
    names = export_pattern.findall(source)
    for group in brace_export_pattern.findall(source):
        for entry in group.split(","):
            entry = re.sub(r"^\s*type\s+", "", entry).strip()
            if entry:
                names.append(re.split(r"\s+as\s+", entry)[-1].strip())
    if star_export_pattern.search(source):
        names.append("*")
    if default_export_pattern.search(source):
        names.append("default")
    return names


def default_import_paths(filename, source):
    for specifier in default_import_pattern.findall(source):
        if specifier.startswith("$lib/"):
            base = Path("frontend/src/lib") / specifier[5:]
        elif specifier.startswith("."):
            base = Path(filename).parent / specifier
        else:
            continue
        for candidate in (base, Path(f"{base}.ts"), Path(f"{base}.svelte"), base / "index.ts"):
            yield candidate.resolve()


def self_test():
    cases = [
        ("export const answer = 42;", ["answer"]),
        ("export async function run() {}", ["run"]),
        ("export abstract class Base {}", ["Base"]),
        ("export declare abstract class Base {}", ["Base"]),
        ("export * from './helpers';", ["*"]),
        ("export type * from './types';", ["*"]),
        ("export enum State { Ready }", ["State"]),
        ("export const enum State { Ready }", ["State"]),
        ("const a = 1;\nexport { a as b };", ["b"]),
        ("export {\n a, b as c,\n};", ["a", "c"]),
        ("export type { A, B as C } from './types';", ["A", "C"]),
        ("export { type A, type B as C };", ["A", "C"]),
        ("export default function helper() {}", ["default"]),
        ("export default class Helper {}", ["default"]),
        ("export default 42;", ["default"]),
        ("const answer = 42;", []),
    ]
    for source, expected in cases:
        actual = exported_names(source)
        if actual != expected:
            sys.exit(f"Export regression: {source!r}: {actual!r} != {expected!r}")
    for source in (
        "import helper from './helper';",
        "import helper, { named } from './helper';",
        "import { default as helper } from './helper';",
        "export { default as helper } from './helper';",
    ):
        paths = set(default_import_paths("frontend/src/caller.ts", source))
        if Path("frontend/src/helper.ts").resolve() not in paths:
            sys.exit(f"Default import regression: {source!r}")
    if list(default_import_paths("frontend/src/caller.ts", "import { named } from './helper';")):
        sys.exit("A named import must not keep a default export alive")
    print("Export form regressions passed (21 cases).")


self_test()
if sys.argv[1:] == ["--self-test"]:
    sys.exit(0)


word_pattern = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
paths = subprocess.check_output(
    ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "frontend/src"],
    text=True,
).split("\0")
references = defaultdict(set)
exports = []
default_consumers = defaultdict(set)
for filename in sorted(set(paths)):
    path = Path(filename)
    if (
        path.suffix not in (".ts", ".svelte")
        or path.name.endswith((".test.ts", ".spec.ts", "-test-fixtures.ts"))
        or "tests" in path.parts
        or "test-utils" in path.parts
        or filename == "frontend/src/lib/api/types.ts"
        or not path.is_file()
    ):
        continue
    source = path.read_text()
    exports.extend((filename, name) for name in exported_names(source))
    for imported_path in default_import_paths(filename, source):
        default_consumers[imported_path].add(filename)
    for word in set(word_pattern.findall(source)):
        references[word].add(filename)

allow = []
for number, line in enumerate(Path("scripts/dead-exports.allow").read_text().splitlines(), 1):
    pattern, _, reason = line.partition("#")
    pattern = pattern.strip()
    if not pattern:
        continue
    if not reason.strip():
        sys.exit(f"scripts/dead-exports.allow:{number}: exception needs a reason")
    allow.append(pattern)

unexpected = [
    f"{filename}:{name}"
    for filename, name in exports
    if not (
        default_consumers[Path(filename).resolve()] - {filename}
        if name == "default"
        else references[name] - {filename}
    )
    and not any(fnmatchcase(f"{filename}:{name}", pattern) for pattern in allow)
]
for entry in unexpected:
    print(f"test-only-alive export: {entry}")
if unexpected:
    sys.exit(1)
print("No unapproved test-only-alive exports.")
PY

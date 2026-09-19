#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

python3 - <<'PY'
from collections import defaultdict
from fnmatch import fnmatchcase
from pathlib import Path
import re
import subprocess
import sys

export_pattern = re.compile(
    r"^export (?:async )?(?:const|let|function|class|type|interface) ([A-Za-z_$][A-Za-z0-9_$]*)",
    re.MULTILINE,
)
word_pattern = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
paths = subprocess.check_output(
    ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "frontend/src"],
    text=True,
).split("\0")
references = defaultdict(set)
exports = []
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
    exports.extend((filename, name) for name in export_pattern.findall(source))
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
    if len(references[name]) == 1
    and not any(fnmatchcase(f"{filename}:{name}", pattern) for pattern in allow)
]
for entry in unexpected:
    print(f"test-only-alive export: {entry}")
if unexpected:
    sys.exit(1)
print("No unapproved test-only-alive exports.")
PY

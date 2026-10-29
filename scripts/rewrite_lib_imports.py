#!/usr/bin/env python3
"""Rewrite `$lib/...` import specifiers in frontend/ to Node subpath imports `#lib/...`.

SvelteKit 3 drops the `$lib` alias; `#lib/*` is declared in frontend/package.json
`imports` and resolves to `src/lib/*` with the target's real extension. A merge
conflict with this rewrite is resolved by running this script again, never by hand.
The script formats what it touched with prettier and is idempotent. A specifier whose target does not exist fails loudly.
"""

import re
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
LIB_DIRECTORY = REPOSITORY_ROOT / "frontend" / "src" / "lib"
SOURCE_SUFFIXES = (".ts", ".js", ".svelte")
# eslint.config.js states `$lib` inside regular expressions and messages, not as imports.
HAND_MAINTAINED = {"frontend/eslint.config.js"}
SPECIFIER = re.compile(r"""(?<=['"`])\$lib/([A-Za-z0-9_./@+\[\]-]+)(?=['"`])""")
# A path in a comment names the module without being an import: only the prefix changes.
MENTION = re.compile(r"\$lib/(?=[A-Za-z])")
RESOLUTION_SUFFIXES = (".ts", ".js", ".svelte", ".svelte.ts", ".svelte.js")


def resolve_target(relative: str) -> str:
    """Return the path below src/lib that the specifier names, with its real extension."""
    base = LIB_DIRECTORY / relative
    candidates = [base] if base.is_file() else []
    candidates += [Path(f"{base}{suffix}") for suffix in RESOLUTION_SUFFIXES]
    candidates.append(base / "index.ts")
    existing = [candidate for candidate in candidates if candidate.is_file()]
    if len(existing) != 1:
        raise SystemExit(f"$lib/{relative}: expected exactly one target, found {existing}")
    return existing[0].relative_to(LIB_DIRECTORY).as_posix()


def rewrite(source: str) -> str:
    imports_rewritten = SPECIFIER.sub(lambda match: f"#lib/{resolve_target(match.group(1))}", source)
    return MENTION.sub("#lib/", imports_rewritten)


def tracked_frontend_sources() -> list[Path]:
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--", "frontend"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    names = [name for name in listing.split("\0") if name.endswith(SOURCE_SUFFIXES)]
    return [REPOSITORY_ROOT / name for name in names if name not in HAND_MAINTAINED]


def format_with_prettier(paths: list[Path]) -> None:
    """A changed specifier changes line widths, so prettier decides the final layout."""
    if paths:
        command = ["pnpm", "exec", "prettier", "--write", "--log-level", "warn", *map(str, paths)]
        subprocess.run(command, cwd=REPOSITORY_ROOT / "frontend", check=True)


def main() -> int:
    changed = []
    for path in tracked_frontend_sources():
        original = path.read_text(encoding="utf-8")
        rewritten = rewrite(original)
        if rewritten != original:
            path.write_text(rewritten, encoding="utf-8")
            changed.append(path)
    format_with_prettier(changed)
    return 0


if __name__ == "__main__":
    sys.exit(main())

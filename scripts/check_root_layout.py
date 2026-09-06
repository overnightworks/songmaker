"""CI guard for the repository-root layout rule (operator ruling 06.09.2026).

The repository root holds only what a tool must find there by default lookup
(package manifest and lockfile, container files, scanner configuration, the
licence) and the entry documents README.md, AGENTS.md, CLAUDE.md. Everything
else belongs in the directory of its owner — a helper under scripts/, a
fixture next to its test, a CI-only config next to the workflow step that
reads it. No catch-all directory (tooling/, misc/).

Run from the project root:

    python scripts/check_root_layout.py

Checks both tracked files and untracked-but-not-gitignored files, so a stray
file never slips past the rule just because nobody ran ``git add`` on it yet.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

ALLOWED_ROOT_FILES: frozenset[str] = frozenset(
    {
        "README.md",
        "AGENTS.md",
        "CLAUDE.md",
        "LICENSE",
        "pyproject.toml",
        "uv.lock",
        "alembic.ini",
        "sonar-project.properties",
        "docker-compose.yml",
        "Dockerfile",
        ".dockerignore",
        ".gitignore",
        ".gitmodules",
        ".importlinter",
        ".python-version",
    }
)

ALLOWED_ROOT_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".github",
        "docker",
        "docs",
        "frontend",
        "monitoring",
        "plans",
        "prompts",
        "scripts",
        "src",
        "tests",
        "vendor",
    }
)

PLACEMENT_GUIDANCE = (
    "belongs in the directory of its owner, not the repository root — a "
    "helper under scripts/, a fixture next to its test, a container file "
    "under docker/, or a CI-only config next to the workflow step that "
    "reads it (operator ruling 06.09.2026)"
)


def list_root_entries(repository_root: Path) -> list[str]:
    """Returns the top-level names of tracked and untracked-but-not-ignored files."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=repository_root,
        capture_output=True,
        check=True,
        text=True,
    )
    top_level_names = {
        relative_path.split("/", 1)[0]
        for relative_path in result.stdout.split("\0")
        if relative_path
    }
    return sorted(top_level_names)


def find_violations(repository_root: Path) -> list[str]:
    """Returns the root-level names that are outside the layout allowlist."""
    violations = []
    for name in list_root_entries(repository_root):
        if (repository_root / name).is_dir():
            if name not in ALLOWED_ROOT_DIRS:
                violations.append(name)
        elif name not in ALLOWED_ROOT_FILES:
            violations.append(name)
    return violations


def main(repository_root: Path = REPOSITORY_ROOT) -> int:
    violations = find_violations(repository_root)
    if not violations:
        print(f"Repository root layout is clean: only allowlisted entries in {repository_root}.")
        return 0

    for name in violations:
        print(f"Repository root layout violation: '{name}' {PLACEMENT_GUIDANCE}.", file=sys.stderr)
    print(f"\n{len(violations)} root layout violation(s).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

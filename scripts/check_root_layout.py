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

ALLOWED_ROOT_ENTRIES: dict[str, str] = {
    ".agent-claim": "agent-claim looks for its board configuration in the repository root",
    "README.md": "entry document",
    "AGENTS.md": "entry document",
    "CLAUDE.md": "entry document",
    "LICENSE": "entry document",
    "pyproject.toml": "uv/pip resolve the project root by its presence",
    "uv.lock": "uv resolves the lockfile next to pyproject.toml",
    "alembic.ini": "alembic's default `-c`-less lookup from the CWD; Dockerfile COPYs it to /app",
    "sonar-project.properties": "the SonarCloud scan action's default projectBaseDir lookup",
    "docker-compose.yml": "`docker compose` (no -f) default lookup, used bare in README/CLAUDE.md",
    "Dockerfile": "docker-compose.yml's `dockerfile: Dockerfile` plus Docker's own root convention",
    ".dockerignore": "Docker's default ignore-file lookup at the build context root",
    ".gitignore": "git's top-level ignore file covers the whole tree",
    ".gitmodules": "git's own submodule registration requires it at the repo root",
    ".importlinter": "import-linter's default `lint-imports` (no -c) lookup from the CWD",
    ".python-version": "uv/pyenv read it from the CWD by default",
    ".git": "git's own repository metadata directory",
    ".github": "GitHub Actions only discovers workflows under this path",
    "docker": "per-service Dockerfiles, compose overrides, and container scripts",
    "docs": "product and architecture documentation",
    "frontend": "the SvelteKit application",
    "monitoring": "Grafana/Prometheus/Alertmanager configuration",
    "plans": "live multi-session coordination notes",
    "prompts": "review prompt templates",
    "scripts": "operational and CI helper scripts",
    "src": "the Python application source",
    "tests": "the Python test suite",
    "vendor": "the vendored ACE-Step submodule",
}


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
    """Returns the root-level names that carry no recorded reason to sit at the root."""
    return [
        name
        for name in list_root_entries(repository_root)
        if name not in ALLOWED_ROOT_ENTRIES
    ]


def placement_sentence(name: str) -> str:
    """Names where a root-layout violator belongs, citing the operator ruling."""
    return (
        f"'{name}' has no recorded reason to sit at the repository root — move it "
        "next to its owner instead (a helper under scripts/, a fixture next to its "
        "test, a container file under docker/, or a CI-only config next to the "
        "workflow step that reads it; operator ruling 06.09.2026)."
    )


def precedent_reference() -> str:
    """Lists today's root exceptions and why each earns its spot, from ALLOWED_ROOT_ENTRIES."""
    precedents = "; ".join(
        f"{name} ({reason})" for name, reason in sorted(ALLOWED_ROOT_ENTRIES.items())
    )
    return f"Today's root entries and why each earns its spot: {precedents}."


def main(repository_root: Path = REPOSITORY_ROOT) -> int:
    violations = find_violations(repository_root)
    if not violations:
        print(f"Repository root layout is clean: only allowlisted entries in {repository_root}.")
        return 0

    for name in violations:
        print(f"Repository root layout violation: {placement_sentence(name)}", file=sys.stderr)
    print(f"\n{len(violations)} root layout violation(s). {precedent_reference()}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

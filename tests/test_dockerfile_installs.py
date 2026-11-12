"""Every Dockerfile installs from a lock: frozen syncs, hashed or own-project pip installs."""

from __future__ import annotations

import re
import shlex
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from support.dockerfile_stages import dockerfile_instructions
from support.repository_root import REPOSITORY_ROOT

COMMAND_SEPARATORS = frozenset({"&&", "||", ";", "|", "(", ")"})
SUBSTITUTION = re.compile(r"\$\(([^()]*)\)")
OWN_PROJECT = "."


def _repository_dockerfiles() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "--", "Dockerfile", "*Dockerfile"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [REPOSITORY_ROOT / line for line in listed.splitlines()]


def _words(shell_text: str) -> Iterator[str]:
    """The words of a shell line; a quoted command substitution becomes commands of its own."""
    lexer = shlex.shlex(shell_text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    for word in lexer:
        yield word
        for substitution in SUBSTITUTION.findall(word):
            yield ";"
            yield from _words(substitution)
            yield ";"


def _uv_commands(dockerfile: Path) -> list[list[str]]:
    """Each ``uv`` invocation of the file, from ``uv`` to the next shell operator."""
    commands: list[list[str]] = []
    for instruction in dockerfile_instructions(dockerfile):
        if not instruction.upper().startswith("RUN "):
            continue
        current: list[str] = []
        for word in [*_words(instruction.split(maxsplit=1)[1]), ";"]:
            if word not in COMMAND_SEPARATORS:
                current.append(word)
                continue
            program = [part for part in current if "=" not in part]
            if program[:1] == ["uv"]:
                commands.append(program)
            current = []
    return commands


def _installs_only_the_own_project(command: list[str]) -> bool:
    """``--no-deps --editable .`` and nothing else to install."""
    arguments = iter(command[command.index("install") + 1 :])
    flags: set[str] = set()
    editable_targets: list[str | None] = []
    requirements: list[str] = []
    for argument in arguments:
        if argument == "--python":
            next(arguments, None)
        elif argument in {"--editable", "-e"}:
            editable_targets.append(next(arguments, None))
        elif argument.startswith("-"):
            flags.add(argument)
        else:
            requirements.append(argument)
    return "--no-deps" in flags and editable_targets == [OWN_PROJECT] and not requirements


def _unlocked_installs(dockerfile: Path) -> list[str]:
    unlocked: list[str] = []
    for command in _uv_commands(dockerfile):
        flags = {word for word in command if word.startswith("-")}
        subcommands = [word for word in command[1:] if not word.startswith("-")]
        if subcommands[:1] == ["sync"] and "--frozen" not in flags:
            unlocked.append(" ".join(command))
        if subcommands[:2] == ["pip", "install"] and not (
            "--require-hashes" in flags or _installs_only_the_own_project(command)
        ):
            unlocked.append(" ".join(command))
    return unlocked


@pytest.mark.parametrize(
    "dockerfile",
    _repository_dockerfiles(),
    ids=lambda dockerfile: dockerfile.relative_to(REPOSITORY_ROOT).as_posix(),
)
def test_dockerfile_installs_only_from_a_lock(dockerfile: Path) -> None:
    assert _unlocked_installs(dockerfile) == []


@pytest.mark.parametrize(
    ("instruction", "unlocked_count"),
    [
        ("RUN uv sync --no-dev", 1),
        ("RUN uv sync --frozen --no-dev", 0),
        ("RUN x=$(uv sync --no-dev) && uv sync --frozen", 1),
        ('RUN x="$(uv sync --no-dev)" && uv sync --frozen', 1),
        ("RUN uv venv .venv && uv pip install --python .venv/bin/python torch", 1),
        ("RUN uv --no-config pip install --require-hashes -r requirements.txt", 0),
        ("RUN uv pip install --no-deps --editable .", 0),
        ("RUN uv pip install --python .venv/bin/python --no-deps --no-build --editable .", 0),
        ("RUN uv pip install --no-deps --editable . torch", 1),
        ("RUN uv pip install --no-deps torch --editable .", 1),
        ("RUN uv pip install --no-deps --editable torch", 1),
        ("RUN uv pip install --no-deps --editable . --editable ./other", 1),
        ("RUN uv pip install --no-deps .", 1),
        ("RUN uv pip install --editable .", 1),
        ("RUN uv sync --frozen && uv pip install torch && uv sync", 2),
        ("RUN uv sync --no-dev # why: a comment names uv sync again", 1),
        ("RUN echo uv sync", 0),
        ("COPY uv sync /bin/", 0),
    ],
)
def test_the_rule_flags_exactly_the_unlocked_installs(
    tmp_path: Path, instruction: str, unlocked_count: int
) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(f"FROM scratch\n{instruction}\n")

    assert len(_unlocked_installs(dockerfile)) == unlocked_count

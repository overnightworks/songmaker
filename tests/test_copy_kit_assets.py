"""The kit copy replaces the target whole; the kit wheel stays out of every image."""

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
from copy_kit_assets import replace_with_copy  # noqa: E402

KIT_GROUP_FLAGS = re.compile(r"--group[ =]frontend|--all-groups|--only-group[ =]frontend")


def test_a_file_removed_from_the_source_is_gone_after_the_next_copy(tmp_path: Path) -> None:
    source = tmp_path / "static"
    (source / "fonts").mkdir(parents=True)
    (source / "appkit.css").write_text("a")
    (source / "fonts" / "old.woff2").write_text("old")
    target = tmp_path / "kit-assets"

    replace_with_copy(source, target)
    (source / "fonts" / "old.woff2").unlink()
    replace_with_copy(source, target)

    assert sorted(path.relative_to(target).as_posix() for path in target.rglob("*")) == [
        "appkit.css",
        "fonts",
    ]


def test_frontend_group_is_not_a_default_group() -> None:
    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text())

    assert "frontend" in pyproject["dependency-groups"]
    assert "default-groups" not in pyproject["tool"]["uv"]


def kit_installing_instructions(dockerfile_text: str) -> list[str]:
    logical_text = re.sub(r"\\[ \t]*\n\s*", " ", dockerfile_text)
    return [
        line
        for line in logical_text.splitlines()
        if re.search(r"uv (sync|export)", line) and KIT_GROUP_FLAGS.search(line)
    ]


@pytest.mark.parametrize(
    "instruction",
    [
        "RUN uv sync --group frontend",
        "RUN uv export --all-groups",
        "RUN uv sync --extra server \\\n    --extra image --group frontend # why",
        "RUN uv export --frozen \\\n    --all-groups",
        "RUN uv sync \\ \t\n    --group frontend",
    ],
)
def test_a_frontend_group_flag_is_found_on_a_continuation_line(instruction: str) -> None:
    assert kit_installing_instructions(instruction)


def test_a_sync_without_the_frontend_group_is_not_flagged() -> None:
    assert not kit_installing_instructions("RUN uv sync --extra server \\\n    --extra image")


@pytest.mark.parametrize(
    "dockerfile",
    [
        REPOSITORY_ROOT / name
        for name in subprocess.run(
            ["git", "ls-files", "*Dockerfile*"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
    ],
    ids=lambda path: path.relative_to(REPOSITORY_ROOT).as_posix(),
)
def test_no_image_sync_or_export_includes_the_frontend_group(dockerfile: Path) -> None:
    assert not kit_installing_instructions(dockerfile.read_text())

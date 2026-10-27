"""The kit copy replaces the target whole; the kit wheel stays out of every image."""

import re
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


@pytest.mark.parametrize(
    "dockerfile",
    sorted(REPOSITORY_ROOT.glob("**/*Dockerfile"))
    + sorted(REPOSITORY_ROOT.glob("**/Dockerfile.*")),
    ids=lambda path: path.relative_to(REPOSITORY_ROOT).as_posix(),
)
def test_no_image_sync_or_export_includes_the_frontend_group(dockerfile: Path) -> None:
    if "vendor" in dockerfile.parts or "node_modules" in dockerfile.parts:
        pytest.skip("third-party tree")
    lines = [
        line for line in dockerfile.read_text().splitlines() if re.search(r"uv (sync|export)", line)
    ]

    assert not [line for line in lines if KIT_GROUP_FLAGS.search(line)]

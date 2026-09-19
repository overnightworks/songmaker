"""Integration checks for the standalone helper-duplication gate."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def ratchet_tree(tmp_path: Path) -> Path:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(
        Path(__file__).parents[1] / "scripts/test_helper_ratchet.sh",
        scripts / "test_helper_ratchet.sh",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "frontend/src").mkdir(parents=True)
    return tmp_path


def run_ratchet(root: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(root / "scripts/test_helper_ratchet.sh"), *arguments],
        cwd=root.parent, capture_output=True, text=True, check=False,
    )


@pytest.mark.parametrize(
    ("directory", "suffix", "definition", "expected"),
    [
        ("tests", ".py", "def _helper():\n    pass\n", "1 0\n"),
        ("tests", ".py", "async def _helper():\n    pass\n", "1 0\n"),
        ("frontend/src", ".test.ts", "function helper() {}\n", "0 1\n"),
        ("frontend/src", ".test.ts", "export async function helper() {}\n", "0 1\n"),
        ("frontend/src", ".test.ts", "const helper = () => 1;\n", "0 1\n"),
        ("frontend/src", ".test.ts", "const helper = async (value: number) => value;\n", "0 1\n"),
        ("frontend/src", ".test.ts", "const helper = function () {};\n", "0 1\n"),
    ],
)
def test_counts_each_helper_name_once_across_files(
    ratchet_tree: Path, directory: str, suffix: str, definition: str, expected: str,
) -> None:
    for name in ("first", "second", "third"):
        (ratchet_tree / directory / f"{name}{suffix}").write_text(definition)

    result = run_ratchet(ratchet_tree, "--update")

    assert result.returncode == 0, result.stderr
    assert (ratchet_tree / "scripts/test_helper_ratchet.txt").read_text() == expected


def test_calls_and_duplicates_in_one_file_do_not_count(ratchet_tree: Path) -> None:
    (ratchet_tree / "tests/first.py").write_text("def _helper():\n    pass\n" * 2)
    (ratchet_tree / "tests/second.py").write_text("_helper()\n" * 2)
    (ratchet_tree / "frontend/src/first.test.ts").write_text("function helper() {}\n" * 2)
    (ratchet_tree / "frontend/src/second.test.ts").write_text(
        "helper();\nconst result = helper();\n"
        "const err = (await helper().catch((e: unknown) => e)) as Error;\n",
    )
    (ratchet_tree / "frontend/src/third.test.ts").write_text(
        "const err = (await helper().catch((e: unknown) => e)) as Error;\n",
    )

    result = run_ratchet(ratchet_tree, "--update")

    assert result.returncode == 0, result.stderr
    assert (ratchet_tree / "scripts/test_helper_ratchet.txt").read_text() == "0 0\n"


@pytest.mark.parametrize("arguments", [(), ("--update",)])
@pytest.mark.parametrize("tree", ["backend", "frontend"])
def test_growth_fails_without_changing_either_limit(
    ratchet_tree: Path, arguments: tuple[str, ...], tree: str,
) -> None:
    baseline = ratchet_tree / "scripts/test_helper_ratchet.txt"
    baseline.write_text("0 0\n")
    for name in ("first", "second"):
        if tree == "backend":
            (ratchet_tree / f"tests/{name}.py").write_text("def _helper():\n    pass\n")
        else:
            (ratchet_tree / f"frontend/src/{name}.test.ts").write_text("function helper() {}\n")

    result = run_ratchet(ratchet_tree, *arguments)

    assert result.returncode != 0
    assert baseline.read_text() == "0 0\n"


def test_only_update_lowers_the_baseline(ratchet_tree: Path) -> None:
    baseline = ratchet_tree / "scripts/test_helper_ratchet.txt"
    baseline.write_text("2 3\n")

    assert run_ratchet(ratchet_tree).returncode == 0
    assert baseline.read_text() == "2 3\n"
    assert run_ratchet(ratchet_tree, "--update").returncode == 0
    assert baseline.read_text() == "0 0\n"

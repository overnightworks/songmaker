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
        Path(__file__).parents[2] / "scripts/test_helper_ratchet.sh",
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
        ("tests", ".py", "def _helper():\n    pass\n", "backend _helper 3\n"),
        ("tests", ".py", "async def _helper():\n    pass\n", "backend _helper 3\n"),
        ("frontend/src", ".test.ts", "function helper() {}\n", "frontend helper 3\n"),
        ("frontend/src", ".test.ts", "export async function helper() {}\n", "frontend helper 3\n"),
        ("frontend/src", ".test.ts", "const helper = () => 1;\n", "frontend helper 3\n"),
        (
            "frontend/src", ".test.ts",
            "const helper = async (value: number) => value;\n", "frontend helper 3\n",
        ),
        ("frontend/src", ".test.ts", "const helper = function () {};\n", "frontend helper 3\n"),
        pytest.param(
            "frontend/src", ".test.ts", "const helper = { value: 1 };\n", "frontend helper 3\n",
            id="defect:#1519-object-literal-constant",
        ),
        pytest.param(
            "frontend/src", ".test.ts",
            "export const helper: Shape = {\n\tvalue: 1\n};\n", "frontend helper 3\n",
            id="defect:#1519-typed-multiline-object-literal-constant",
        ),
    ],
)
def test_counts_each_helper_name_once_across_files(
    ratchet_tree: Path, directory: str, suffix: str, definition: str, expected: str,
) -> None:
    for name in ("first", "second", "third"):
        (ratchet_tree / directory / f"{name}{suffix}").write_text(definition)

    baseline = ratchet_tree / "scripts/test_helper_ratchet.txt"
    baseline.write_text(expected)

    result = run_ratchet(ratchet_tree)

    assert result.returncode == 0, result.stderr
    assert "stale" not in result.stdout


def test_calls_and_duplicates_in_one_file_do_not_count(ratchet_tree: Path) -> None:
    """defect:#1519 -- an indented object constant and a call that takes one are no definitions."""
    (ratchet_tree / "tests/first.py").write_text("def _helper():\n    pass\n" * 2)
    (ratchet_tree / "tests/second.py").write_text("_helper()\n" * 2)
    (ratchet_tree / "frontend/src/first.test.ts").write_text("function helper() {}\n" * 2)
    (ratchet_tree / "frontend/src/second.test.ts").write_text(
        "helper();\nconst result = helper();\n"
        "const err = (await helper().catch((e: unknown) => e)) as Error;\n"
        "  const helper = { value: 1 };\n",
    )
    (ratchet_tree / "frontend/src/third.test.ts").write_text(
        "const err = (await helper().catch((e: unknown) => e)) as Error;\n"
        "const helper = makeHelper({});\n",
    )

    (ratchet_tree / "scripts/test_helper_ratchet.txt").write_text("")

    result = run_ratchet(ratchet_tree)

    assert result.returncode == 0, result.stderr
    assert "0 duplicated helper names" in result.stdout


@pytest.mark.parametrize("arguments", [(), ("--update",)])
@pytest.mark.parametrize("tree", ["backend", "frontend"])
def test_growth_fails_without_changing_the_baseline(
    ratchet_tree: Path, arguments: tuple[str, ...], tree: str,
) -> None:
    baseline = ratchet_tree / "scripts/test_helper_ratchet.txt"
    baseline.write_text("")
    for module in ("first", "second"):
        define_helper(ratchet_tree, tree, module)

    result = run_ratchet(ratchet_tree, *arguments)

    assert result.returncode != 0
    assert baseline.read_text() == ""


def define_helper(root: Path, tree: str, module: str, name: str = "helper") -> None:
    if tree == "backend":
        (root / f"tests/{module}.py").write_text(f"def _{name}():\n    pass\n")
    else:
        (root / f"frontend/src/{module}.test.ts").write_text(f"function {name}() {{}}\n")


@pytest.mark.parametrize("tree", ["backend", "frontend"])
def test_unchanged_tree_passes_without_rewriting(ratchet_tree: Path, tree: str) -> None:
    baseline = ratchet_tree / "scripts/test_helper_ratchet.txt"
    name = "_helper" if tree == "backend" else "helper"
    baseline.write_text(f"{tree} {name} 2\n")
    for module in ("first", "second"):
        define_helper(ratchet_tree, tree, module)

    assert run_ratchet(ratchet_tree).returncode == 0
    assert baseline.read_text() == f"{tree} {name} 2\n"


def test_new_duplicated_name_fails_even_when_another_name_fell(ratchet_tree: Path) -> None:
    baseline = ratchet_tree / "scripts/test_helper_ratchet.txt"
    baseline.write_text("backend _old 3\n")
    for module in ("first", "second"):
        define_helper(ratchet_tree, "backend", module, "new")

    result = run_ratchet(ratchet_tree)

    assert result.returncode != 0
    assert "backend _new: stored 0, current 2" in result.stdout + result.stderr
    assert "backend _old: stored 3, current 0 (stale)" in result.stdout + result.stderr


def test_name_defined_in_more_modules_fails_naming_both_counts(ratchet_tree: Path) -> None:
    baseline = ratchet_tree / "scripts/test_helper_ratchet.txt"
    baseline.write_text("frontend helper 2\n")
    for module in ("first", "second", "third"):
        define_helper(ratchet_tree, "frontend", module)

    result = run_ratchet(ratchet_tree)

    assert result.returncode != 0
    assert "frontend helper: stored 2, current 3" in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("modules", "stored", "expected"),
    [(2, "backend _helper 3\n", "backend _helper 2\n"), (1, "backend _helper 2\n", "")],
    ids=["fewer modules", "no longer duplicated"],
)
def test_fallen_entry_fails_as_stale_and_passes_after_update(
    ratchet_tree: Path, modules: int, stored: str, expected: str,
) -> None:
    baseline = ratchet_tree / "scripts/test_helper_ratchet.txt"
    baseline.write_text(stored)
    for module in ("first", "second")[:modules]:
        define_helper(ratchet_tree, "backend", module)

    stale = run_ratchet(ratchet_tree)
    assert stale.returncode != 0
    assert "stale" in stale.stdout + stale.stderr
    assert baseline.read_text() == stored

    assert run_ratchet(ratchet_tree, "--update").returncode == 0
    assert baseline.read_text() == expected


@pytest.mark.parametrize("stored", ["", "backend _helper 2\n"], ids=["add", "raise"])
def test_update_never_raises_or_adds_an_entry(ratchet_tree: Path, stored: str) -> None:
    baseline = ratchet_tree / "scripts/test_helper_ratchet.txt"
    baseline.write_text(stored)
    for module in ("first", "second", "third"):
        define_helper(ratchet_tree, "backend", module)

    assert run_ratchet(ratchet_tree, "--update").returncode != 0
    assert baseline.read_text() == stored


@pytest.mark.parametrize(
    "stored",
    [
        "invalid\n", "backend _helper x\n", "other _helper 2\n", "backend _helper 1\n",
        "backend _helper 2\nbackend _helper 3\n",
    ],
)
def test_invalid_baseline_fails_loudly(ratchet_tree: Path, stored: str) -> None:
    baseline = ratchet_tree / "scripts/test_helper_ratchet.txt"
    baseline.write_text(stored)

    assert run_ratchet(ratchet_tree, "--update").returncode != 0
    assert baseline.read_text() == stored


@pytest.mark.parametrize("arguments", [(), ("--update",)])
def test_missing_baseline_fails_and_is_not_created(
    ratchet_tree: Path, arguments: tuple[str, ...],
) -> None:
    result = run_ratchet(ratchet_tree, *arguments)

    assert result.returncode != 0
    assert "Missing baseline" in result.stderr
    assert not (ratchet_tree / "scripts/test_helper_ratchet.txt").exists()

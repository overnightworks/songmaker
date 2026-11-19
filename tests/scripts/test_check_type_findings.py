"""Checks for the mypy and ANN401 ratchet over its baseline."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts/check_type_findings.py"
KNOWN = "src/a.py :: return :: Missing return"


class Ratchet:
    """The script's `main` over a temporary root, with fake mypy and ruff output."""

    def __init__(self, module, root: Path) -> None:
        self.module = module
        self.root = root
        self.baseline = root / "baseline.txt"

    def write_source(self, name: str, source: str) -> None:
        path = self.root / "src" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)

    def run(self, mypy_output: str = "", ruff_items: list | None = None, *baseline: str):
        self.baseline.write_text("".join(f"{line}\n" for line in baseline))

        def fake_tool(command, cwd) -> subprocess.CompletedProcess[str]:
            output = mypy_output if "mypy" in command else json.dumps(ruff_items or [])
            return subprocess.CompletedProcess(command, 0, output, "")

        return self.module.main([], self.root, self.baseline, fake_tool)


@pytest.fixture
def ratchet(tmp_path: Path) -> Ratchet:
    spec = importlib.util.spec_from_file_location("type_check_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return Ratchet(module, tmp_path)


def mypy_line(number: int, message: str = "Missing return") -> str:
    return f"src/a.py:{number}: error: {message}  [return]"


@pytest.mark.parametrize(
    ("mypy_output", "baseline", "exit_code", "printed"),
    [
        (mypy_line(3), [KNOWN], 0, "all in the baseline"),
        (mypy_line(3), [], 1, f"NEW {KNOWN}"),
        ("", [KNOWN], 1, "FIXED but still in the baseline"),
        (mypy_line(90), [KNOWN], 0, "all in the baseline"),
        (
            mypy_line(5, "Defined on line 12"),
            ["src/a.py :: return :: Defined on line N"],
            0,
            "all in the baseline",
        ),
        (mypy_line(3) + "\n" + mypy_line(8), [KNOWN], 1, f"NEW {KNOWN}"),
    ],
    ids=[
        "finding in the baseline",
        "finding missing from the baseline",
        "baseline entry no longer found",
        "moved finding",
        "line reference in a message",
        "second occurrence",
    ],
)
def test_ratchet_compares_findings_with_the_baseline(
    ratchet: Ratchet, capsys, mypy_output: str, baseline: list[str], exit_code: int, printed: str
):
    assert ratchet.run(mypy_output, None, *baseline) == exit_code
    assert printed in capsys.readouterr().out


def test_ann401_finding_is_compared_without_its_line(ratchet: Ratchet):
    item = {"filename": str(ratchet.root / "src/b.py"), "code": "ANN401", "message": "Any"}

    assert ratchet.run("", [item], "src/b.py :: ANN401 :: Any") == 0


NESTED_FINDING = "src/m.py :: nested-any :: dict[str, Any] in `{scope}`"


@pytest.mark.parametrize(
    ("source", "scope"),
    [
        ("def f(x: dict[str, Any]) -> None: ...", "f"),
        ("def f() -> dict[str, Any]: ...", "f"),
        ("def f() -> list[dict[str, Any]]: ...", "f"),
        ("def f(x: dict[str, dict[str, Any]]) -> None: ...", "f"),
        ("class C:\n    field: dict[str, Any]", "C"),
        ("class C:\n    def m(self) -> dict[str, typing.Any]: ...", "C.m"),
        ("Provider = Callable[[], dict[str, Any]]", "module"),
    ],
    ids=["parameter", "return", "inside list", "inside dict", "field", "qualified Any", "alias"],
)
def test_new_nested_dict_of_any_is_red(ratchet: Ratchet, capsys, source: str, scope: str):
    ratchet.write_source("m.py", source)

    assert ratchet.run() == 1
    assert f"NEW {NESTED_FINDING.format(scope=scope)}" in capsys.readouterr().out


def test_nested_dict_of_any_in_the_baseline_is_green(ratchet: Ratchet):
    ratchet.write_source("m.py", "def f(x: dict[str, Any]) -> None: ...")

    assert ratchet.run("", None, NESTED_FINDING.format(scope="f")) == 0


def test_removed_nested_dict_of_any_stays_in_the_baseline_as_an_orphan(ratchet: Ratchet, capsys):
    ratchet.write_source("m.py", "def f(x: int) -> None: ...")

    assert ratchet.run("", None, NESTED_FINDING.format(scope="f")) == 1
    assert "FIXED but still in the baseline" in capsys.readouterr().out


@pytest.mark.parametrize(
    "source",
    ["def f(x: dict[str, int]) -> None: ...", "def f(x: Any) -> None: ...", ""],
    ids=["dict without Any", "direct Any", "empty module"],
)
def test_other_annotations_are_not_findings(ratchet: Ratchet, source: str):
    ratchet.write_source("m.py", source)

    assert ratchet.run() == 0

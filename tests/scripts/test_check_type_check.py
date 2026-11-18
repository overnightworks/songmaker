"""Checks for the mypy and ANN401 ratchet over its baseline."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts/type_check/check.py"
KNOWN = "src/a.py :: return :: Missing return"


class Ratchet:
    """The script's `main` over a temporary root, with fake mypy and ruff output."""

    def __init__(self, module, root: Path) -> None:
        self.module = module
        self.root = root
        self.baseline = root / "baseline.txt"

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

"""Checks for the mypy and ANN401 ratchet over its baseline."""

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts/type_check/check.py"


@pytest.fixture
def check(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    spec = importlib.util.spec_from_file_location("type_check_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "BASELINE", tmp_path / "baseline.txt")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["check.py"])
    return module


def fake_tools(monkeypatch, check, mypy_output: str = "", ruff_items: list | None = None):
    def run(command, **_):
        output = mypy_output if "mypy" in command else json.dumps(ruff_items or [])
        return type("Done", (), {"returncode": 0, "stdout": output, "stderr": ""})()

    monkeypatch.setattr(check.subprocess, "run", run)


def mypy_line(number: int, message: str = "Missing return") -> str:
    return f"src/a.py:{number}: error: {message}  [return]"


def write_baseline(check, *lines: str) -> None:
    check.BASELINE.write_text("".join(f"{line}\n" for line in lines))


def test_finding_in_the_baseline_is_green(monkeypatch, check, capsys):
    fake_tools(monkeypatch, check, mypy_line(3))
    write_baseline(check, "src/a.py :: return :: Missing return")

    assert check.main() == 0
    assert "all in the baseline" in capsys.readouterr().out


def test_finding_missing_from_the_baseline_is_red(monkeypatch, check, capsys):
    fake_tools(monkeypatch, check, mypy_line(3))
    write_baseline(check)

    assert check.main() == 1
    assert "NEW src/a.py :: return :: Missing return" in capsys.readouterr().out


def test_baseline_entry_no_longer_found_is_red(monkeypatch, check, capsys):
    fake_tools(monkeypatch, check)
    write_baseline(check, "src/a.py :: return :: Missing return")

    assert check.main() == 1
    assert "FIXED but still in the baseline" in capsys.readouterr().out


def test_moved_finding_stays_in_the_baseline(monkeypatch, check):
    fake_tools(monkeypatch, check, mypy_line(90))
    write_baseline(check, "src/a.py :: return :: Missing return")

    assert check.main() == 0


def test_line_reference_in_a_message_is_normalized(monkeypatch, check):
    fake_tools(monkeypatch, check, mypy_line(5, "Defined on line 12"))
    write_baseline(check, "src/a.py :: return :: Defined on line N")

    assert check.main() == 0


def test_second_occurrence_of_a_finding_is_red(monkeypatch, check):
    fake_tools(monkeypatch, check, mypy_line(3) + "\n" + mypy_line(8))
    write_baseline(check, "src/a.py :: return :: Missing return")

    assert check.main() == 1


def test_ann401_finding_is_compared_without_its_line(monkeypatch, check, tmp_path):
    item = {"filename": str(tmp_path / "src/b.py"), "code": "ANN401", "message": "Any"}
    fake_tools(monkeypatch, check, ruff_items=[item])
    write_baseline(check, "src/b.py :: ANN401 :: Any")

    assert check.main() == 0
    assert Counter(check.ann401_findings()) == Counter(["src/b.py :: ANN401 :: Any"])

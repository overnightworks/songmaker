"""Behavior of the production-reference gate."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

CHECKER = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/check_dead_symbols.py"))


@pytest.fixture
def run_gate(tmp_path, monkeypatch, capsys):
    source = tmp_path / "src"
    source.mkdir()
    allow = tmp_path / "dead-symbols.allow"

    def run(files, exemptions=""):
        for relative, text in files.items():
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        allow.write_text(exemptions)
        monkeypatch.setattr(sys, "argv", ["gate", "--source", str(source), "--allow", str(allow)])
        status = CHECKER["main"]()
        return status, capsys.readouterr().out

    return run


@pytest.mark.parametrize(
    "definition, same_file_use",
    [
        ("def orphan(): pass", "orphan()"),
        ("async def orphan(): pass", "callback = orphan"),
        ("class orphan: pass", "instance = orphan()"),
        ("ORPHAN = 1", "value = ORPHAN"),
        ("ORPHAN: int = 1", "value = ORPHAN"),
    ],
)
@pytest.mark.parametrize("used_locally", [True, False])
def test_same_file_use_keeps_alive_but_test_only_use_does_not(
    run_gate, definition, same_file_use, used_locally
):
    status, output = run_gate(
        {
            "owner.py": f"{definition}\n{same_file_use if used_locally else ''}\n",
            "tests/consumer.py": "from owner import orphan, ORPHAN\n",
            "test_owner.py": "from owner import orphan, ORPHAN\n",
        }
    )
    assert status == (0 if used_locally else 1)
    assert ("owner.py:" in output) is not used_locally


@pytest.mark.parametrize(
    "consumer",
    [
        "from owner import alive as alias\nalias()",
        "import owner\nowner.alive()",
        "callback = alive",
        "annotation: 'alive'",
        "getattr(owner, 'alive')",
    ],
)
def test_external_production_reference_keeps_symbol_alive(run_gate, consumer):
    assert run_gate({"owner.py": "def alive(): pass", "consumer.py": consumer})[0] == 0


def test_a_definition_or_comment_in_another_file_is_not_a_reference(run_gate):
    status, output = run_gate(
        {
            "one.py": "def unused(): pass",
            "two.py": "def unused(): pass\n# unused",
        }
    )
    assert status == 1
    assert "one.py:unused" in output
    assert "two.py:unused" in output


def test_allow_entry_is_exact_and_requires_a_reason(run_gate):
    status, output = run_gate(
        {"routes.py": "@router.get('/')\ndef endpoint(): pass", "other.py": "def endpoint(): pass"},
        "routes.py:endpoint # FastAPI route dispatcher\n",
    )
    assert status == 1
    assert "other.py:endpoint" in output
    assert "No production reference: routes.py:endpoint" not in output


@pytest.mark.parametrize("allow", ["owner.py:unused", "owner.py:unused # ", "*:unused # wildcard"])
def test_unjustified_or_nonmatching_exemption_does_not_pass(run_gate, allow):
    assert run_gate({"owner.py": "def unused(): pass"}, allow)[0] == 1


def test_class_methods_and_nested_functions_are_outside_the_module_rule(run_gate):
    assert (
        run_gate(
            {
                "owner.py": "class Live:\n def method(self):\n  def local(): pass\n",
                "consumer.py": "from owner import Live",
            }
        )[0]
        == 0
    )


@pytest.mark.parametrize("files", [{}, {"bad.py": "def broken("}])
def test_empty_or_invalid_source_tree_fails(run_gate, files):
    assert run_gate(files)[0] == 1


def test_duplicate_allow_entries_fail(run_gate):
    status, output = run_gate(
        {"owner.py": "def callback(): pass"},
        "owner.py:callback # protocol\nowner.py:callback # duplicate\n",
    )
    assert status == 1
    assert "expected unique path:name # reason" in output


@pytest.mark.parametrize("use", ['"unused"', "text = 'unused'", "getattr(owner, 'unused')"])
def test_same_file_strings_and_docstrings_do_not_keep_a_symbol_alive(run_gate, use):
    status, output = run_gate({"owner.py": f"{use}\ndef unused(): pass\n"})
    assert status == 1
    assert "owner.py:unused" in output


def test_same_file_attribute_reference_keeps_a_symbol_alive(run_gate):
    assert run_gate({"owner.py": "def alive(): pass\nowner.alive()\n"})[0] == 0

"""Tests for ``scripts/check_no_silent_fallbacks.py``."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_no_silent_fallbacks as checker  # noqa: E402

LINE_REGEX_RULES = (
    "env-read-outside-settings",
    "next-iter-fallback",
    "dict-get-domain-fallback",
    "optional-on-default-utcnow-column",
    "engine-isolation-violation",
)


def _seed(tmp_path: Path, files: dict[str, str]) -> Path:
    src = tmp_path / "src"
    for rel, content in files.items():
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return src


def _run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *args: str) -> int:
    monkeypatch.chdir(tmp_path)
    return checker.main(list(args) if args else ["src/"])


def _checked_site_count(output: str, rule_name: str) -> int:
    match = re.search(rf"{re.escape(rule_name)}=(\d+)", output)
    assert match is not None, output
    return int(match.group(1))


def test_clean_codebase_returns_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(tmp_path, {"foo/bar.py": "x = 1\n"})
    rc = _run(monkeypatch, tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert "No silent-fallback smells" in out
    assert f"{checker.CHECKED_LABEL}:" in out


@pytest.mark.parametrize(("statement", "is_read"), [
    ("value = os.environ.get('FOO')", True),
    ("value = os.environ.pop('FOO', None)", True),
    ("value = os.environ.setdefault('FOO', 'fallback')", True),
    ("value = os.getenv('FOO')", True),
    ("value = os.environ['FOO']", True),
    ("if os.environ['FOO'] == 'on':", True),
    ("os.environ['FOO'] = 'value'", False),
    ("del os.environ['FOO']", False),
    ("del  os.environ['FOO']", False),
    ("del\tos.environ['FOO']", False),
    ("os.environ['PATH'] += ':/opt/bin'", False),
    ("child_env = os.environ.copy()", False),
])
def test_only_reads_of_the_environment_are_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str], statement: str, is_read: bool,
) -> None:
    """Reading configuration belongs in Settings; changing process state
    does not, so writes and deletes pass."""
    _seed(tmp_path, {"songmaker_cli/foo.py": f"import os\n{statement}\n"})
    rc = _run(monkeypatch, tmp_path)
    out = capsys.readouterr().out
    assert rc == (1 if is_read else 0)
    if is_read:
        assert "env-read-outside-settings" in out
        assert "songmaker_cli/foo.py:2" in out


@pytest.mark.parametrize("rel_path", [
    "songmaker_cli/settings.py",
    "acestep_worker/settings.py",
    "songmaker_cli/db/migrations/env.py",
    "songmaker_cli/env_override.py",
])
def test_env_owning_roles_may_read_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rel_path: str,
) -> None:
    _seed(tmp_path, {rel_path: "import os\nos.environ.get('X')\n"})
    assert _run(monkeypatch, tmp_path) == 0


def test_a_settings_named_api_model_is_not_an_env_owner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(tmp_path, {
        "songmaker_cli/api_models/settings.py": "import os\nos.environ.get('X')\n",
    })
    rc = _run(monkeypatch, tmp_path)
    assert rc == 1
    assert "env-read-outside-settings" in capsys.readouterr().out


@pytest.mark.parametrize(("rel_path", "line"), [
    ("songmaker_cli/api_models/songs.py", "    expires_at: str | None = None"),
    ("songmaker_cli/api_models/settings.py", "    updated_at: str | None = None"),
    ("acestep_worker/task_store.py", "def complete(self, r: dict[str, Any]) -> None: ..."),
    ("songmaker_cli/claude/provider.py", "x = os.getenv('FOO')"),
])
def test_no_file_or_line_buys_an_exemption(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str], rel_path: str, line: str,
) -> None:
    """Every path that used to sit in the allowlist is now judged like
    any other file — the only way out is fixing the code."""
    _seed(tmp_path, {rel_path: "\n" * 200 + line + "\n"})
    rc = _run(monkeypatch, tmp_path)
    assert rc == 1
    assert rel_path in capsys.readouterr().out


def test_next_iter_caught(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(tmp_path, {"songmaker_cli/m.py": "d = {'a': 1}\nfirst = next(iter(d))\n"})
    rc = _run(monkeypatch, tmp_path)
    out = capsys.readouterr().out
    assert rc == 1
    assert "next-iter-fallback" in out


def test_dict_get_domain_fallback_caught(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(tmp_path, {
        "songmaker_cli/m.py": "x = generation_params.get('bpm', 120)\n",
    })
    rc = _run(monkeypatch, tmp_path)
    out = capsys.readouterr().out
    assert rc == 1
    assert "dict-get-domain-fallback" in out


@pytest.mark.parametrize("signature", [
    "def f(x: dict[str, Any]) -> None: ...",
    "def f(x: dict[str, Any], /) -> None: ...",
    "def f(*, x: dict[str, Any]) -> None: ...",
    "def f(*x: dict[str, Any]) -> None: ...",
    "def f(**x: dict[str, Any]) -> None: ...",
    "def f(x: Dict[str, Any]) -> None: ...",
    "async def f(x: dict[str, Any]) -> None: ...",
])
def test_dict_any_in_signature_caught(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str], signature: str,
) -> None:
    _seed(tmp_path, {
        "songmaker_cli/m.py": f"from typing import Any\n{signature}\n",
    })
    rc = _run(monkeypatch, tmp_path)
    out = capsys.readouterr().out
    assert rc == 1
    assert checker.DICT_ANY_IN_SIGNATURE in out


def test_multiline_dict_any_parameter_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(tmp_path, {
        "songmaker_cli/m.py": (
            "from typing import Any\n"
            "def f(\n"
            "    x: dict[str, Any],\n"
            ") -> None: ...\n"
        ),
    })
    rc = _run(monkeypatch, tmp_path)
    out = capsys.readouterr().out
    assert rc == 1
    assert checker.DICT_ANY_IN_SIGNATURE in out
    assert "songmaker_cli/m.py:3" in out


def test_dict_any_outside_a_parameter_is_not_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(tmp_path, {
        "songmaker_cli/m.py": (
            "from typing import Any\n"
            "class C:\n"
            "    config: dict[str, Any]\n"
            "def f(\n"
            "    x: dict[str, str],\n"
            ") -> dict[str, Any]:\n"
            "    nested: list[dict[str, Any]] = []\n"
            "    return {}\n"
        ),
    })
    rc = _run(monkeypatch, tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert f"[{checker.DICT_ANY_IN_SIGNATURE}]" not in out
    assert f"{checker.CHECKED_LABEL}:" in out


def test_getattr_literal_default_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(tmp_path, {
        "songmaker_cli/m.py": 'value = getattr(obj, "status", "ok")\n',
    })
    rc = _run(monkeypatch, tmp_path)
    out = capsys.readouterr().out
    assert rc == 1
    assert checker.GETATTR_LITERAL_DEFAULT in out
    assert "songmaker_cli/m.py:1" in out


@pytest.mark.parametrize("source", [
    'value = getattr(obj, "status")\n',
    'value = getattr(obj, "status", None)\n',
    'DEFAULT = "ok"\nvalue = getattr(obj, "status", DEFAULT)\n',
])
def test_getattr_without_a_literal_default_is_not_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str], source: str,
) -> None:
    _seed(tmp_path, {"songmaker_cli/m.py": source})
    rc = _run(monkeypatch, tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert f"[{checker.GETATTR_LITERAL_DEFAULT}]" not in out


def test_optional_timestamp_caught(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(tmp_path, {
        "songmaker_cli/m.py": "class R:\n    created_at: str | None = None\n",
    })
    rc = _run(monkeypatch, tmp_path)
    out = capsys.readouterr().out
    assert rc == 1
    assert "optional-on-default-utcnow-column" in out


def test_engine_isolation_caught(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(tmp_path, {
        "acestep_engine/leak.py": "from songmaker_cli.constants import APP_NAME\n",
    })
    rc = _run(monkeypatch, tmp_path)
    out = capsys.readouterr().out
    assert rc == 1
    assert "engine-isolation-violation" in out


def test_engine_isolation_does_not_fire_on_songmaker_cli_itself(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _seed(tmp_path, {
        "songmaker_cli/m.py": "from songmaker_cli.constants import APP_NAME\n",
    })
    rc = _run(monkeypatch, tmp_path)
    assert rc == 0


def test_real_codebase_passes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Line-regex rules stay clean on the real src/ tree. AST rules may
    still report; their checked-site counts must be non-zero."""
    project_root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(project_root)
    checker.main(["src/"])
    out = capsys.readouterr().out
    for name in LINE_REGEX_RULES:
        assert f"[{name}]" not in out
    assert f"{checker.CHECKED_LABEL}:" in out
    assert _checked_site_count(out, checker.DICT_ANY_IN_SIGNATURE) > 0
    assert _checked_site_count(out, checker.GETATTR_LITERAL_DEFAULT) > 0


def test_missing_root_returns_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    assert checker.main(["nonexistent/"]) == 2

"""Tests for ``scripts/check_no_silent_fallbacks.py``."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_no_silent_fallbacks as checker  # noqa: E402


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


def test_clean_codebase_returns_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(tmp_path, {"foo/bar.py": "x = 1\n"})
    rc = _run(monkeypatch, tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert "No silent-fallback smells" in out


def test_env_read_outside_settings_caught(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(tmp_path, {
        "songmaker_cli/foo.py": "import os\nx = os.environ.get('FOO')\n",
    })
    rc = _run(monkeypatch, tmp_path)
    out = capsys.readouterr().out
    assert rc == 1
    assert "env-read-outside-settings" in out
    assert "songmaker_cli/foo.py:2" in out


def test_env_read_in_settings_allowlisted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _seed(tmp_path, {
        "songmaker_cli/settings.py": "import os\nos.environ.get('X')\n",
    })
    rc = _run(monkeypatch, tmp_path)
    assert rc == 0


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


def test_dict_any_in_signature_caught(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(tmp_path, {
        "songmaker_cli/m.py": (
            "from typing import Any\n"
            "def f(x: dict[str, Any]) -> None: ...\n"
        ),
    })
    rc = _run(monkeypatch, tmp_path)
    out = capsys.readouterr().out
    assert rc == 1
    assert "dict-any-in-signature" in out


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


def test_real_codebase_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The actual src/ directory should be clean — this is the
    invariant the rest of the no-silent-fallbacks-v2 work guarantees."""
    project_root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(project_root)
    assert checker.main(["src/"]) == 0


def test_missing_root_returns_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    assert checker.main(["nonexistent/"]) == 2

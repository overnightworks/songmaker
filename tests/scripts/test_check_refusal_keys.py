"""Tests for ``scripts/check_refusal_keys.py``."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_refusal_keys as checker  # noqa: E402

REPOSITORY_SOURCE = Path(__file__).resolve().parents[2] / checker.DEFAULT_SOURCE

WORDS_MODULE = """
SOURCE_LANGUAGE = "en"
WORDS = {
    "en": {
        "takeRefusal.archived": "Restore this take first.",
        "modelRefusal.unavailable": "Model '{model}' is not currently available",
        "plainSentence": "A sentence without a refusal name.",
        "songCount": {"one": "{count} song", "other": "{count} songs"},
    },
}
"""

REFUSAL_IMPORT = "from songmaker_cli.refusals import Refusal\n"
WORDS_IMPORT = "from songmaker_cli.words import text\n"


def _scan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], source: str
) -> tuple[int, str]:
    package = tmp_path / "songmaker_cli"
    package.mkdir(exist_ok=True)
    (package / "words.py").write_text(WORDS_MODULE, encoding="utf-8")
    (package / "route.py").write_text(source, encoding="utf-8")
    code = checker.main([str(package)])
    return code, capsys.readouterr().out


@pytest.mark.parametrize(
    "source",
    [
        REFUSAL_IMPORT + 'Refusal(409, "takeRefusal.archived")\n',
        REFUSAL_IMPORT + 'Refusal(400, "modelRefusal.unavailable", model=name)\n',
        WORDS_IMPORT + 'text("en", "takeRefusal.archived")\n',
        WORDS_IMPORT.replace("text", "text as sentence") + 'sentence("en", "plainSentence")\n',
        "from songmaker_cli import words\n" + 'words.text("en", "takeRefusal.archived")\n',
        "import songmaker_cli.words as w\n" + 'w.text("en", "takeRefusal.archived")\n',
        "import songmaker_cli.words\n" + 'songmaker_cli.words.text("en", "takeRefusal.archived")\n',
    ],
    ids=[
        "refusal",
        "refusal-with-gap",
        "text-by-import",
        "text-by-alias",
        "text-on-words-module",
        "text-on-aliased-module",
        "text-on-dotted-module",
    ],
)
def test_a_call_with_a_plain_key_and_its_gaps_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], source: str
) -> None:
    code, output = _scan(tmp_path, capsys, source)

    assert code == 0, output
    assert "calls=1, violations=0" in output


@pytest.mark.parametrize(
    ("source", "problem"),
    [
        (REFUSAL_IMPORT + 'Refusal(409, "takeRefusal.gone")\n', "not a plain entry"),
        (REFUSAL_IMPORT + 'Refusal(409, "songCount")\n', "not a plain entry"),
        (REFUSAL_IMPORT + "Refusal(409, key)\n", "not a string literal"),
        (REFUSAL_IMPORT + 'Refusal(409, f"take{kind}")\n', "not a string literal"),
        (REFUSAL_IMPORT + "Refusal(409)\n", "not a string literal"),
        (REFUSAL_IMPORT + 'Refusal(409, "plainSentence")\n', "does not match"),
        (REFUSAL_IMPORT + 'Refusal(404, "takeRefusal.archived")\n', "404"),
        (REFUSAL_IMPORT + 'Refusal(code, "takeRefusal.archived")\n', "not an int literal"),
        (REFUSAL_IMPORT + 'Refusal(True, "takeRefusal.archived")\n', "not an int literal"),
        (REFUSAL_IMPORT + 'Refusal(400, "modelRefusal.unavailable")\n', "missing ['model']"),
        (
            REFUSAL_IMPORT + 'Refusal(400, "modelRefusal.unavailable", model=m, other=o)\n',
            "unexpected ['other']",
        ),
        (REFUSAL_IMPORT + 'Refusal(400, "modelRefusal.unavailable", **gaps)\n', "** spread"),
        (REFUSAL_IMPORT + 'Refusal(409, "takeRefusal.archived", count=2)\n', "unexpected ['count']"),
        (WORDS_IMPORT + 'text("en", "takeRefusal.gone")\n', "not a plain entry"),
        (WORDS_IMPORT + 'text("en", key)\n', "not a string literal"),
        (WORDS_IMPORT + 'text("en", "modelRefusal.unavailable")\n', "missing ['model']"),
        ("from songmaker_cli import words\n" + 'words.text("en", "songCount", count=2)\n', "plain entry"),
    ],
    ids=[
        "unknown-key",
        "plural-family-key",
        "non-literal-key",
        "formatted-key",
        "key-missing",
        "key-without-refusal-suffix",
        "status-404",
        "non-literal-status",
        "bool-status",
        "missing-gap",
        "extra-gap",
        "gap-spread",
        "count-on-a-plain-key",
        "text-unknown-key",
        "text-non-literal-key",
        "text-missing-gap",
        "text-plural-family-key",
    ],
)
def test_a_call_breaking_the_contract_is_reported_with_its_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], source: str, problem: str
) -> None:
    code, output = _scan(tmp_path, capsys, source)

    assert code == 1
    assert "route.py:2:" in output
    assert problem in output


def test_sqlalchemy_text_is_not_a_catalog_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = 'from sqlalchemy import text\nstatement = text("select 1")\n'

    code, output = _scan(tmp_path, capsys, source)

    assert code == 0, output
    assert "calls=0, violations=0" in output


def test_a_catalog_text_call_beside_sqlalchemy_text_is_the_only_one_counted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = (
        "from sqlalchemy import text\nfrom songmaker_cli import words\n"
        'statement = text("select 1")\nsentence = words.text("en", "plainSentence")\n'
    )

    code, output = _scan(tmp_path, capsys, source)

    assert code == 0, output
    assert "calls=1, violations=0" in output


def test_a_missing_words_module_stops_the_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = checker.main([str(tmp_path / "songmaker_cli")])

    assert code == 2
    assert "words.py does not exist" in capsys.readouterr().err


def test_the_repository_source_passes(capsys: pytest.CaptureFixture[str]) -> None:
    code = checker.main([str(REPOSITORY_SOURCE)])

    assert code == 0, capsys.readouterr().out

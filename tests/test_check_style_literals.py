"""Detection and monotone baseline behavior of the frontend style gate."""

import runpy
import sys
from pathlib import Path

import pytest

CHECKER = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/check_style_literals.py")
)


@pytest.fixture
def gate(tmp_path, monkeypatch, capsys):
    source = tmp_path / "frontend/src"
    source.mkdir(parents=True)
    baseline = tmp_path / "style-literals.txt"

    def run(files, *, limit="0\n", update=False):
        for relative, content in files.items():
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        if limit is not None:
            baseline.write_text(limit)
        arguments = ["gate", "--source", str(source), "--baseline", str(baseline)]
        monkeypatch.setattr(sys, "argv", arguments + (["--update"] if update else []))
        status = CHECKER["main"]()
        output = capsys.readouterr().out
        return status, output, baseline.read_text() if baseline.exists() else None

    return run


@pytest.mark.parametrize(
    "literal, kind",
    [
        *[(f"color: {color};", "hex") for color in ("#abc", "#ABCD", "#123456", "#12345678")],
        *[(f"color: {color};", "functional") for color in
          ("rgb(1 2 3)", "rgba(1, 2, 3, .5)", "hsl(12 20% 30%)", "HSLA(12, 20%, 30%, .2)")],
        ("border-radius: 4px;", "border-radius"),
        ("border-radius: var(--radius) 2.5px / 10%;", "border-radius"),
        ("font-size: 14px;", "font-size"),
        ("font-size: 1rem;", "font-size"),
        ("font-size: .7em;", "font-size"),
        ("font-size: 90%;", "font-size"),
        ("font-size: large;", "font-size"),
        ("box-shadow: 0 2px 3px black;", "box-shadow"),
        ("box-shadow: var(--shadow), 0 0 2px currentColor;", "box-shadow"),
        ("box-shadow:\n  inset 0 0 0 1px var(--border);", "box-shadow"),
    ],
)
@pytest.mark.parametrize("filename", ["nested/Card.svelte", "styles.css", "styles.ts"])
def test_each_literal_kind_fails_with_its_location(gate, literal, kind, filename):
    status, output, baseline = gate({filename: f"\n{literal}"})
    assert status == 1
    assert f"{filename}:2: {kind}:" in output
    assert "Style literals: 1 (limit 0)" in output
    assert baseline == "0\n"


@pytest.mark.parametrize("pixels", [22, 15, 13, 12, 11, 10])
@pytest.mark.parametrize("unit", ["px", "rem"])
def test_vocabulary_font_scale_passes(gate, pixels, unit):
    size = pixels / 16 if unit == "rem" else pixels
    assert gate({"type.css": f"font-size: {size}{unit};"})[0] == 0


@pytest.mark.parametrize(
    "text",
    [
        "color: var(--text); border-radius: var(--radius); font-size: var(--font-12);",
        "border-radius: 50%; box-shadow: var(--shadow);",
        "box-shadow: var(--shadow) !important; font-size: 12px !important;",
        "box-shadow: none; box-shadow: inherit; font-size: inherit;",
        "color: #12; color: #12345; color: #1234567; color: #123456789; color: #abcdefg;",
    ],
)
def test_tokens_resets_and_non_color_hashes_pass(gate, text):
    assert gate({"styles.css": text})[0] == 0


def test_only_frontend_source_extensions_are_scanned_and_app_css_is_exempt(gate):
    status, output, _ = gate({"app.css": "color: #fff;", "notes.md": "#abc", "empty.ts": ""})
    assert status == 0
    assert "Style literals: 0" in output


@pytest.mark.parametrize(
    "filename, text, line",
    [
        ("card.css", "/* #abc\n font-size: 14px; */\ncolor: #def;", 3),
        ("card.ts", "// #abc\n/* box-shadow: 0 0 2px; */\nconst color = '#def';", 3),
        ("Card.svelte", "<!-- #abc\n border-radius: 2px; -->\n<style>p {color: #def;}</style>", 3),
        ("Card.svelte", "<script>\n// #abc\nconst color = '#def';\n</script>", 3),
        ("card.ts", "const url = 'https://example.test'; const color = '#def';", 1),
        ("card.css", 'p { background: url(https://example.test); color: #def; }', 1),
        ("card.ts", 'const css = `p {background: url("https://example.test"); color: #def;}`;', 1),
        ("card.ts", 'const css = `/* #abc */\ncolor: #def;`;', 2),
    ],
)
def test_comments_are_ignored_without_losing_line_numbers_or_urls(gate, filename, text, line):
    status, output, _ = gate({filename: text})
    assert status == 1
    assert "Style literals: 1 (limit 0)" in output
    assert f"{filename}:{line}: hex: #def" in output


def test_color_inside_a_shadow_counts_both_literal_kinds(gate):
    status, output, _ = gate({"card.css": "box-shadow: 0 0 4px #abc;"})
    assert status == 1
    assert "Style literals: 2 (limit 0); box-shadow=1, hex=1" in output


def test_baseline_caps_the_combined_file_count(gate):
    status, output, baseline = gate({"a.css": "color: #abc;", "b.ts": "'#def'"}, limit="1\n")
    assert status == 1
    assert "Style literals: 2 (limit 1)" in output
    assert "a.css:1: hex: #abc" in output
    assert "b.ts:1: hex: #def" in output
    assert baseline == "1\n"


@pytest.mark.parametrize("limit", ["1\n", "2\n"])
def test_normal_check_accepts_equal_or_lower_count_without_rewriting(gate, limit):
    status, output, baseline = gate({"card.css": "color: #abc;"}, limit=limit)
    assert status == 0
    assert baseline == limit
    assert "card.css: 1 style literals" in output


@pytest.mark.parametrize("update", [False, True])
def test_growth_fails_even_with_update_and_keeps_baseline(gate, update):
    status, output, baseline = gate({"card.css": "color: #abc;"}, update=update)
    assert status == 1
    assert "Style literals increased" in output
    assert "card.css:1: hex: #abc" in output
    assert baseline == "0\n"


@pytest.mark.parametrize("limit", [None, "1\n", "2\n"])
def test_update_initializes_or_lowers_baseline(gate, limit):
    status, _, baseline = gate({"card.css": "color: #abc;"}, limit=limit, update=True)
    assert status == 0
    assert baseline == "1\n"


@pytest.mark.parametrize("limit", [None, "", "-1", "1 2", "invalid"])
def test_missing_or_invalid_baseline_fails_loudly(gate, limit):
    status, output, baseline = gate({"card.css": ""}, limit=limit)
    assert status == 1
    assert "Expected one nonnegative count" in output
    assert baseline == limit


def test_invalid_baseline_cannot_be_overwritten_with_update(gate):
    assert gate({"card.css": ""}, limit="invalid", update=True)[0] == 1


def test_empty_source_tree_fails_loudly(gate):
    status, output, _ = gate({})
    assert status == 1
    assert "No frontend source files found" in output

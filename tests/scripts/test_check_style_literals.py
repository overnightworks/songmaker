"""Detection and monotone baseline behavior of the frontend style gate."""

import runpy
from pathlib import Path

import pytest

CHECKER = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts/check_style_literals.py")
)


@pytest.fixture
def gate(tmp_path, capsys):
    source = tmp_path / "frontend/src"
    source.mkdir(parents=True)
    baseline_path = tmp_path / "style-literals.txt"
    appkit_path = tmp_path / "node_modules/appkit.css"

    def run(files, *, baseline="", update=False, appkit=":root { --appkit-gap: 4px; }"):
        for relative, content in files.items():
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        if baseline is not None:
            baseline_path.write_text(baseline)
        if appkit is not None:
            appkit_path.parent.mkdir(parents=True, exist_ok=True)
            appkit_path.write_text(appkit)
        status = CHECKER["run"](source, baseline_path, appkit_path, update=update)
        output = capsys.readouterr().out
        return status, output, baseline_path.read_text() if baseline_path.exists() else None

    return run


@pytest.mark.parametrize(
    "literal, kind",
    [
        *[(f"color: {color};", "hex") for color in ("#abc", "#ABCD", "#123456", "#12345678")],
        *[(f"color: {color};", "functional") for color in
          ("rgb(1 2 3)", "rgba(1, 2, 3, .5)", "hsl(12 20% 30%)", "HSLA(12, 20%, 30%, .2)")],
        ("border-radius: 4px;", "border-radius"),
        ("border-bottom-right-radius: 2px;", "border-bottom-right-radius"),
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
    status, output, written = gate({filename: f"\n{literal}"})
    assert status == 1
    assert f"{filename}:2: {kind}:" in output
    assert "Style literals: 1;" in output
    assert written == ""


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
        "border-bottom-right-radius: var(--radius);",
        "box-shadow: var(--a),\n var(--b);",
        "box-shadow: var(--shadow) !important; font-size: 12px !important;",
        "box-shadow: none; box-shadow: inherit; font-size: inherit;",
        "color: #12; color: #12345; color: #1234567; color: #123456789; color: #abcdefg;",
    ],
)
def test_tokens_resets_and_non_color_hashes_pass(gate, text):
    tokens = ":root { --text: 0; --radius: 0; --font-12: 0; --shadow: 0; --a: 0; --b: 0; }"
    assert gate({"styles.css": text}, appkit=tokens)[0] == 0


@pytest.mark.parametrize(
    "declaration, literal",
    [
        ("box-shadow: 0 0 2px !important;", "0 0 2px"),
        ("box-shadow: 0 0 2px   \n\t!IMPORTANT;", "0 0 2px"),
        ("box-shadow: 0 0 2px!important;", "0 0 2px"),
        ("box-shadow: 0 1px !important 2px !important;", "0 1px 2px"),
        ("box-shadow: 0 0 2px !importantly;", "0 0 2px !importantly"),
        ("box-shadow: 0 0 2px ! important;", "0 0 2px ! important"),
        ("box-shadow: 0 0\u00a0!important 2px;", "0 0 2px"),
    ],
)
def test_important_flag_and_the_space_before_it_are_not_part_of_the_literal(declaration, literal):
    """defect:#1498 -- the S8786-safe split strips !important and the space before it."""
    assert [found.literal for found in CHECKER["findings"](declaration, ".css")] == [literal]


@pytest.mark.parametrize(
    "declaration, kinds",
    [
        ("font-size: 12px;", []),
        ("font-size: 12.0px;", []),
        ("font-size: .75rem;", []),
        ("font-size: 0.6875rem;", []),
        ("font-size: 12.5px;", ["font-size"]),
        ("font-size: 12.px;", ["font-size"]),
        ("font-size: -12px;", ["font-size"]),
        ("font-size: 1.5rem;", ["font-size"]),
        ("border-radius: .5px;", ["border-radius"]),
        ("border-radius: 1.5.5px;", ["border-radius"]),
        ("border-radius: 12.%;", []),
        ("border-radius: -2px;", ["border-radius"]),
    ],
)
def test_number_shapes_decide_which_dimensions_are_style_literals(declaration, kinds):
    """defect:#1498 -- the S8786-safe number matching keeps the same dimension shapes."""
    assert [found.kind for found in CHECKER["findings"](declaration, ".css")] == kinds


def test_only_frontend_source_extensions_are_scanned_and_app_css_is_exempt(gate):
    status, output, _ = gate({"app.css": "color: #fff;", "notes.md": "#abc", "empty.ts": ""})
    assert status == 0
    assert "Style literals: 0" in output


@pytest.mark.parametrize("suffix", ["test", "spec"])
def test_issue_references_in_test_files_are_not_style_literals(gate, suffix):
    status, output, _ = gate({
        f"nested/card.{suffix}.ts": "describe('card (#973)', () => {});",
        "card.ts": "const color = '#abc';",
    }, baseline="card.ts 1\n")
    assert status == 0
    assert "Style literals: 1; hex=1" in output
    assert f"card.{suffix}.ts" not in output


@pytest.mark.parametrize(
    "filename, text, line",
    [
        ("card.css", "/* #abc\n font-size: 14px; */\ncolor: #def;", 3),
        ("card.ts", "// #abc\n/* box-shadow: 0 0 2px; */\nconst color = '#def';", 3),
        ("Card.svelte", "<!-- #abc\n border-radius: 2px; -->\n<style>p {color: #def;}</style>", 3),
        ("Card.svelte", "<script>\n// #abc\nconst color = '#def';\n</script>", 3),
        ("Card.svelte", "<SCRIPT lang=\"ts\">\n// #abc\nconst color = '#def';\n</script >", 3),
        ("card.ts", "const url = 'https://example.test'; const color = '#def';", 1),
        ("card.css", 'p { background: url(https://example.test); color: #def; }', 1),
        ("card.ts", 'const css = `p {background: url("https://example.test"); color: #def;}`;', 1),
        ("card.ts", 'const css = `/* #abc */\ncolor: #def;`;', 2),
    ],
)
def test_comments_are_ignored_without_losing_line_numbers_or_urls(gate, filename, text, line):
    status, output, _ = gate({filename: text})
    assert status == 1
    assert "Style literals: 1;" in output
    assert f"{filename}:{line}: hex: #def" in output


def test_color_inside_a_shadow_counts_both_literal_kinds(gate):
    status, output, _ = gate({"card.css": "box-shadow: 0 0 4px #abc;"})
    assert status == 1
    assert "Style literals: 2; box-shadow=1, hex=1" in output


def test_a_literal_added_in_a_second_file_fails_even_when_another_file_shrank(gate):
    status, output, written = gate(
        {"a.css": "", "b.ts": "'#def'"}, baseline="a.css 1\n",
    )
    assert status == 1
    assert "b.ts: stored 0, current 1" in output
    assert "b.ts:1: hex: #def" in output
    assert "a.css: stored 1, current 0 (stale)" in output
    assert written == "a.css 1\n"


def test_growth_in_a_listed_file_names_the_file_with_both_counts(gate):
    status, output, _ = gate({"a.css": "color: #abc; color: #def;"}, baseline="a.css 1\n")
    assert status == 1
    assert "a.css: stored 1, current 2" in output
    assert "a.css:1: hex: #def" in output


def test_unchanged_tree_passes_without_rewriting(gate):
    status, output, written = gate({"card.css": "color: #abc;"}, baseline="card.css 1\n")
    assert status == 0
    assert written == "card.css 1\n"
    assert "Style literals: 1;" in output


@pytest.mark.parametrize(
    "files, baseline, expected",
    [
        ({"a.css": "color: #abc;"}, "a.css 2\n", "a.css 1\n"),
        ({"a.css": ""}, "a.css 1\n", ""),
        ({"b.css": "color: #abc;"}, "a.css 1\nb.css 1\n", "b.css 1\n"),
    ],
    ids=["fallen", "none left", "vanished"],
)
def test_stale_entry_fails_until_update_writes_the_smaller_baseline(
    gate, files, baseline, expected,
):
    status, output, written = gate(files, baseline=baseline)
    assert status == 1
    assert "stale" in output
    assert written == baseline
    status, _, written = gate({}, baseline=None, update=True)
    assert status == 0
    assert written == expected


@pytest.mark.parametrize(
    "files, baseline",
    [
        ({"a.css": "color: #abc; color: #def;"}, "a.css 1\n"),
        ({"a.css": "color: #abc;", "b.css": "color: #abc;"}, "a.css 1\n"),
        ({"a.css": "color: #abc;", "b.css": ""}, "b.css 1\n"),
    ],
    ids=["raise", "add", "add while another fell"],
)
def test_update_never_raises_or_adds_an_entry(gate, files, baseline):
    status, _, written = gate(files, baseline=baseline, update=True)
    assert status == 1
    assert written == baseline


@pytest.mark.parametrize(
    "baseline", [None, "invalid", "a.css -1", "a.css x", "a.css 0", "a.css 1 2"],
)
def test_missing_or_invalid_baseline_fails_loudly(gate, baseline):
    status, output, written = gate({"card.css": ""}, baseline=baseline)
    assert status == 1
    assert "Expected" in output or "Missing baseline" in output
    assert written == baseline


def test_invalid_baseline_cannot_be_overwritten_with_update(gate):
    assert gate({"card.css": ""}, baseline="invalid", update=True)[0] == 1


def test_missing_baseline_fails_under_update_without_being_created(gate):
    status, output, written = gate({"a.css": "color: #abc;"}, baseline=None, update=True)
    assert status == 1
    assert "Missing baseline" in output
    assert written is None


def test_empty_source_tree_fails_loudly(gate):
    status, output, _ = gate({})
    assert status == 1
    assert "No frontend source files found" in output


def test_gate_takes_no_path_from_the_command_line(monkeypatch):
    monkeypatch.setattr("sys.argv", ["gate", "--source", "/etc", "--baseline", "/etc/passwd"])
    with pytest.raises(SystemExit) as exit_info:
        CHECKER["main"]()
    assert exit_info.value.code == 2


@pytest.mark.parametrize(
    "files",
    [
        {"app.css": ":root { --accent: red; }", "card.css": "a { color: var(--accent); }"},
        {"Card.svelte": "<style>p { --gap: 1px; }</style>\n<p style=\"margin: var(--gap)\"></p>"},
        {"Card.svelte": "<p style=\"--gap: 1px\"></p>\n<style>p { margin: var(--gap); }</style>"},
        {"Card.svelte": "<p style:--gap={gap}></p>\n<style>p { margin: var(--gap); }</style>"},
        {"card.ts": "node.style.setProperty('--gap', '1px');",
         "a.css": "p { margin: var(--gap); }"},
        {"card.ts": 'node.style.setProperty( "--gap", 1);',
         "a.css": "p { margin: var(--gap); }"},
        {"a.css": "p { margin: var(--appkit-gap); }"},
        {"a.css": "p { margin: var( --appkit-gap , 0); }"},
    ],
    ids=["app.css", "component css", "inline style", "style directive", "setProperty single",
         "setProperty double", "appkit", "appkit spaced"],
)
def test_use_of_a_declared_token_passes(gate, files):
    status, output, _ = gate(files)
    assert status == 0
    assert "Undefined" not in output


@pytest.mark.parametrize(
    "use", ["var(--ghost)", "var(--ghost, 0px)", "var( --ghost , var(--other, 1px))"],
)
def test_use_of_an_undefined_token_fails_with_its_location_also_with_a_fallback(gate, use):
    status, output, _ = gate({"nested/card.css": f"\np {{ margin: {use}; }}"})
    assert status == 1
    assert "nested/card.css:2 --ghost" in output


def test_token_declared_only_in_a_comment_does_not_define_it(gate):
    status, output, _ = gate({
        "card.css": "/* --ghost: 1px; */\np { margin: var(--ghost); }",
        "card.ts": "// node.style.setProperty('--ghost', 1);",
    })
    assert status == 1
    assert "card.css:2 --ghost" in output


def test_declaration_in_a_test_file_does_not_define_a_token(gate):
    status, output, _ = gate({
        "card.test.ts": "el.style.setProperty('--ghost', 1);",
        "card.css": "p { margin: var(--ghost); }",
    })
    assert status == 1
    assert "card.css:1 --ghost" in output


def test_missing_appkit_stylesheet_fails_naming_its_path(gate, tmp_path):
    status, output, _ = gate({"card.css": ""}, appkit=None)
    assert status == 1
    assert f"Missing {tmp_path / 'node_modules/appkit.css'}" in output
    assert "pnpm install" in output

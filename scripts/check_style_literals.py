"""Hold style literals outside app.css per file and fail on a var(--x) no declaration defines."""
# ruff: noqa: T201 - this check reports style literal counts and locations

import argparse
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

FONT_SCALE = {22, 15, 13, 12, 11, 10}
ROOT_FONT_PX = 16
QUOTED = r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`'''
COMMENTS = r"/\*.*?\*/|<!--.*?-->"
COLORS = re.compile(
    r"(?P<hex>\#[0-9a-f]{8}(?![\w-])|\#[0-9a-f]{6}(?![\w-])"
    r"|\#[0-9a-f]{4}(?![\w-])|\#[0-9a-f]{3}(?![\w-]))"
    r"|(?P<functional>\b(?:rgba?|hsla?)\s*\()", re.IGNORECASE,
)
DECLARATIONS = re.compile(
    r'''\b(?P<property>border(?:-[a-z]+)*-radius|font-size|box-shadow)\s*:\s*(?P<value>[^;{}"'`]+)''',
    re.IGNORECASE,
)
DIMENSIONS = re.compile(r"(?<![\w-])(-?(?:\d+(?:\.\d+)?|\.\d+))([a-z%]*)", re.IGNORECASE)
IMPORTANT = re.compile(r"!important\b", re.IGNORECASE)
TOKEN = re.compile(r"var\(\s*--[\w-]+\s*\)", re.IGNORECASE)
TOKEN_USE = re.compile(r"var\(\s*(?P<name>--[\w-]+)", re.IGNORECASE)
TOKEN_DECLARATION = re.compile(
    r"(?<![\w-])(?P<declared>--[\w-]+)(?=\s*:)|(?<=style:)(?P<directive>--[\w-]+)"
    r"|[\"'`](?P<quoted>--[\w-]+)[\"'`]")
DESIGN_STYLESHEET = Path("node_modules/overnightworks-design/src/design/static/design.css")
RESET_VALUES = {"none", "inherit", "initial", "unset", "revert", "revert-layer"}
FONT_KEYWORDS = {"xx-small", "x-small", "small", "medium", "large", "x-large", "xx-large",
                 "xxx-large", "smaller", "larger", "math"}


@dataclass(frozen=True)
class Finding:
    line: int
    kind: str
    literal: str


Sites = list[tuple[Path, list[Finding]]]


def without_comments(text: str, *, javascript: bool) -> str:
    pattern = f"{QUOTED}|(?P<comment>{COMMENTS}" + (r"|//[^\n]*" if javascript else "") + ")"
    text = re.sub(pattern, lambda m: re.sub(r"[^\n]", " ", m[0]) if m["comment"] else m[0],
                  text, flags=re.DOTALL)
    return re.sub(COMMENTS, lambda m: re.sub(r"[^\n]", " ", m[0]), text, flags=re.DOTALL)


# Not one re.sub: a pattern that eats the space before the flag backtracks polynomially (S8786).
def without_important(value: str) -> str:
    *kept, last = IMPORTANT.split(value)
    return "".join(part.rstrip() for part in kept) + last


def code_without_comments(text: str, suffix: str) -> str:
    if suffix == ".svelte":
        text = re.sub(r"(<script\b[^>]*>)(.*?)(</script\b[^>]*>)",
                      lambda m: m[1] + without_comments(m[2], javascript=True) + m[3],
                      text, flags=re.DOTALL | re.IGNORECASE)
    return without_comments(text, javascript=suffix == ".ts")


def findings(text: str, suffix: str) -> list[Finding]:
    text = code_without_comments(text, suffix)
    found = [Finding(text.count("\n", 0, m.start()) + 1, m.lastgroup, m[0])
             for m in COLORS.finditer(text)]
    for match in DECLARATIONS.finditer(text):
        kind = match["property"].lower()
        value = without_important(match["value"]).strip()
        dimensions = DIMENSIONS.findall(TOKEN.sub("", value))
        if kind.startswith("border-"):
            forbidden = any(unit.lower() == "px" for _, unit in dimensions)
        elif kind == "font-size":
            forbidden = value.lower() in FONT_KEYWORDS or any(
                unit.lower() not in {"px", "rem"} or
                float(number) * (ROOT_FONT_PX if unit.lower() == "rem" else 1)
                not in FONT_SCALE for number, unit in dimensions)
        else:
            remainder = re.sub(r"[,\s]", "", TOKEN.sub("", value))
            forbidden = bool(remainder) and value.lower() not in RESET_VALUES
        if forbidden:
            found.append(Finding(text.count("\n", 0, match.start()) + 1, kind, value))
    return sorted(found, key=lambda finding: finding.line)


def frontend_sources(source: Path) -> list[Path]:
    paths = sorted(path for path in source.rglob("*")
                   if path.suffix in {".svelte", ".ts", ".css"}
                   and not path.name.endswith((".test.ts", ".spec.ts")))
    if not source.is_dir() or not paths:
        raise ValueError(f"No frontend source files found in {source}")
    return paths


def style_sources(source: Path) -> list[Path]:
    return [path for path in frontend_sources(source) if path.name != "app.css"]


def declared_tokens(code: str) -> set[str]:
    return {match["declared"] or match["directive"] or match["quoted"]
            for match in TOKEN_DECLARATION.finditer(code)}


def undefined_uses(source: Path, design_stylesheet: Path) -> list[str]:
    if not design_stylesheet.is_file():
        raise ValueError(f"Missing {design_stylesheet}; install the frontend: cd frontend && pnpm install")
    codes = {path.relative_to(source): code_without_comments(path.read_text(), path.suffix)
             for path in frontend_sources(source)}
    defined = declared_tokens(code_without_comments(design_stylesheet.read_text(), ".css")).union(
        *map(declared_tokens, codes.values()))
    return [f"{path}:{code.count(chr(10), 0, use.start()) + 1} {use['name']}"
            for path, code in codes.items() for use in TOKEN_USE.finditer(code)
            if use["name"] not in defined]


def read_baseline(baseline: Path) -> dict[str, int]:
    if not baseline.exists():
        raise ValueError(f"Missing baseline {baseline}")
    entries: dict[str, int] = {}
    for line in baseline.read_text().splitlines():
        fields = line.split()
        valid = len(fields) == 2 and fields[1].isdecimal() and int(fields[1]) > 0
        if not valid or fields[0] in entries:
            raise ValueError(f"Expected one 'path count' line per file in {baseline}: {line!r}")
        entries[fields[0]] = int(fields[1])
    return entries


def print_summary(sites: Sites, counts: Counter[str]) -> None:
    for path, entries in sites:
        if entries:
            print(f"{path}: {len(entries)} style literals")
    print(f"Style literals: {counts.total()}; "
          + ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items())))


def print_locations(sites: Sites, paths: set[str]) -> None:
    for path, entries in sites:
        for entry in entries:
            if str(path) in paths:
                print(f"{path}:{entry.line}: {entry.kind}: {entry.literal}")


def drift(stored: dict[str, int], current: dict[str, int]) -> tuple[set[str], set[str]]:
    grown = {path for path, count in current.items() if count > stored.get(path, 0)}
    stale = {path for path, count in stored.items() if current.get(path, 0) < count}
    return grown, stale


def print_drift(stored: dict[str, int], current: dict[str, int], grown: set[str], stale: set[str]) -> None:
    for path in sorted(grown):
        print(f"{path}: stored {stored.get(path, 0)}, current {current[path]}")
    for path in sorted(stale):
        print(f"{path}: stored {stored[path]}, current {current.get(path, 0)} (stale)")


def check_literals(source: Path, baseline: Path, *, update: bool) -> int:
    sites = [(path.relative_to(source), findings(path.read_text(), path.suffix))
             for path in style_sources(source)]
    counts = Counter(finding.kind for _, entries in sites for finding in entries)
    current = {str(path): len(entries) for path, entries in sites if entries}
    print_summary(sites, counts)
    stored = read_baseline(baseline)
    grown, stale = drift(stored, current)
    print_drift(stored, current, grown, stale)
    if grown:
        print("Style literals increased; replace them with tokens. Locations in those files:")
        print_locations(sites, grown)
        return 1
    if stale and not update:
        print("Style literals fell; run scripts/check_style_literals.py --update.")
        return 1
    if update and stale:
        baseline.write_text("".join(f"{path} {count}\n" for path, count in sorted(current.items())))
        print("Updated style literal baseline.")
    return 0


def check(source: Path, baseline: Path, design_stylesheet: Path, *, update: bool) -> int:
    literals_status = check_literals(source, baseline, update=update)
    undefined = undefined_uses(source, design_stylesheet)
    if undefined:
        print("Undefined custom properties; define the token or use another "
              "(a token set only through a computed setProperty name is not seen):")
        print("\n".join(undefined))
    return 1 if undefined else literals_status


def run(source: Path, baseline: Path, design_stylesheet: Path, *, update: bool) -> int:
    try:
        return check(source, baseline, design_stylesheet, update=update)
    except (OSError, ValueError) as error:
        print(error)
        return 1


def main() -> int:
    repository = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    return run(repository / "frontend/src", repository / "scripts/style-literals.txt",
               repository / "frontend" / DESIGN_STYLESHEET,
               update=args.update)


if __name__ == "__main__":
    raise SystemExit(main())

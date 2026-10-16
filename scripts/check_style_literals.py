"""Cap style literals outside app.css; only --update may lower the baseline."""

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


def findings(text: str, suffix: str) -> list[Finding]:
    if suffix == ".svelte":
        text = re.sub(r"(<script\b[^>]*>)(.*?)(</script\b[^>]*>)",
                      lambda m: m[1] + without_comments(m[2], javascript=True) + m[3],
                      text, flags=re.DOTALL | re.IGNORECASE)
    text = without_comments(text, javascript=suffix == ".ts")
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


def style_sources(source: Path) -> list[Path]:
    paths = sorted(path for path in source.rglob("*")
                   if path.suffix in {".svelte", ".ts", ".css"} and path.name != "app.css"
                   and not path.name.endswith((".test.ts", ".spec.ts")))
    if not source.is_dir() or not paths:
        raise ValueError(f"No frontend source files found in {source}")
    return paths


def read_baseline(baseline: Path) -> str | None:
    if not baseline.exists():
        return None
    return baseline.read_text().strip()  # NOSONAR(S8707) Operator-named CLI path.


def baseline_limit(previous: str | None, baseline: Path, total: int, *, update: bool) -> int:
    if previous is None and update:
        return total
    if previous is None or not previous.isdecimal():
        raise ValueError(f"Expected one nonnegative count in {baseline}; initialize with --update")
    return int(previous)


def print_summary(sites: Sites, counts: Counter[str], limit: int) -> None:
    for path, entries in sites:
        if entries:
            print(f"{path}: {len(entries)} style literals")
    print(f"Style literals: {counts.total()} (limit {limit}); "
          + ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items())))


def print_locations(sites: Sites) -> None:
    print("Style literals increased; replace literals with tokens before updating baseline.")
    print("Current locations (the count-only baseline does not identify which are new):")
    for path, entries in sites:
        for entry in entries:
            print(f"{path}:{entry.line}: {entry.kind}: {entry.literal}")


def check(source: Path, baseline: Path, *, update: bool) -> int:
    sites = [(path.relative_to(source), findings(path.read_text(), path.suffix))
             for path in style_sources(source)]
    counts = Counter(finding.kind for _, entries in sites for finding in entries)
    total = counts.total()
    previous = read_baseline(baseline)
    limit = baseline_limit(previous, baseline, total, update=update)
    print_summary(sites, counts, limit)
    if total > limit:
        print_locations(sites)
        return 1
    if update and (previous is None or total < limit):
        baseline.write_text(f"{total}\n")  # NOSONAR(S8707) Operator-named CLI path.
        print("Updated style literal baseline.")
    return 0


def main() -> int:
    repository = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=repository / "frontend/src")
    parser.add_argument("--baseline", type=Path, default=repository / "scripts/style-literals.txt")
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    try:
        return check(args.source, args.baseline, update=args.update)
    except (OSError, ValueError) as error:
        print(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

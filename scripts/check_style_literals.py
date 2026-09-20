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
DIMENSIONS = re.compile(r"(?<![\w-])(-?(?:\d*\.)?\d+)([a-z%]*)", re.IGNORECASE)
TOKEN = re.compile(r"var\(\s*--[\w-]+\s*\)", re.IGNORECASE)
RESET_VALUES = {"none", "inherit", "initial", "unset", "revert", "revert-layer"}
FONT_KEYWORDS = {"xx-small", "x-small", "small", "medium", "large", "x-large", "xx-large",
                 "xxx-large", "smaller", "larger", "math"}


@dataclass(frozen=True)
class Finding:
    line: int
    kind: str
    literal: str


def without_comments(text: str, *, javascript: bool) -> str:
    pattern = f"{QUOTED}|(?P<comment>{COMMENTS}" + (r"|//[^\n]*" if javascript else "") + ")"
    text = re.sub(pattern, lambda m: re.sub(r"[^\n]", " ", m[0]) if m["comment"] else m[0],
                  text, flags=re.DOTALL)
    return re.sub(COMMENTS, lambda m: re.sub(r"[^\n]", " ", m[0]), text, flags=re.DOTALL)


def findings(text: str, suffix: str) -> list[Finding]:
    if suffix == ".svelte":
        text = re.sub(r"(<script\b[^>]*>)(.*?)(</script>)",
                      lambda m: m[1] + without_comments(m[2], javascript=True) + m[3],
                      text, flags=re.DOTALL | re.IGNORECASE)
    text = without_comments(text, javascript=suffix == ".ts")
    found = [Finding(text.count("\n", 0, m.start()) + 1, m.lastgroup, m[0])
             for m in COLORS.finditer(text)]
    for match in DECLARATIONS.finditer(text):
        kind = match["property"].lower()
        value = re.sub(r"\s*!important\b", "", match["value"], flags=re.IGNORECASE).strip()
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


def check(source: Path, baseline: Path, *, update: bool) -> int:
    paths = sorted(path for path in source.rglob("*")
                   if path.suffix in {".svelte", ".ts", ".css"} and path.name != "app.css"
                   and not path.name.endswith((".test.ts", ".spec.ts")))
    if not source.is_dir() or not paths:
        raise ValueError(f"No frontend source files found in {source}")
    sites = [(path.relative_to(source), findings(path.read_text(), path.suffix)) for path in paths]
    counts = Counter(finding.kind for _, entries in sites for finding in entries)
    total = counts.total()
    previous = baseline.read_text().strip() if baseline.exists() else None
    if previous is None and update:
        limit = total
    elif previous is None or not previous.isdecimal():
        raise ValueError(f"Expected one nonnegative count in {baseline}; initialize with --update")
    else:
        limit = int(previous)
    for path, entries in sites:
        if entries:
            print(f"{path}: {len(entries)} style literals")
    print(f"Style literals: {total} (limit {limit}); "
          + ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items())))
    if total > limit:
        print("Style literals increased; replace literals with tokens before updating baseline.")
        print("Current locations (the count-only baseline does not identify which are new):")
        for path, entries in sites:
            for entry in entries:
                print(f"{path}:{entry.line}: {entry.kind}: {entry.literal}")
        return 1
    if update and (previous is None or total < limit):
        baseline.write_text(f"{total}\n")
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

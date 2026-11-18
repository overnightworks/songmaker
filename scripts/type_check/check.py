"""Run mypy and ruff's ANN401 over src/ against the committed baseline of today's findings.

A finding is `path :: code :: message`, without its line number, so edits above it do not
change it; a repeated finding repeats its line. The check is red on a finding the baseline
lacks and on a baseline entry no longer found, so the baseline only shrinks.
"""
# ruff: noqa: T201 - this check reports its findings on stdout

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).with_name("baseline.txt")
REGENERATE = "python scripts/type_check/check.py --regenerate"
SEPARATOR = " :: "
MYPY_LINE = re.compile(r"^(?P<path>[^:]+):\d+: error: (?P<message>.*)  \[(?P<code>[\w-]+)\]$")
LINE_REFERENCE = re.compile(r"\bline \d+")


def mypy_findings() -> list[str]:
    done = subprocess.run(
        [sys.executable, "-m", "mypy", "--no-error-summary", "--show-error-codes", "--no-pretty"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if done.returncode not in (0, 1):
        sys.exit(f"mypy failed to run:\n{done.stdout}{done.stderr}")
    findings = []
    for line in done.stdout.splitlines():
        match = MYPY_LINE.match(line)
        if match:
            message = LINE_REFERENCE.sub("line N", match["message"])
            findings.append(SEPARATOR.join((match["path"], match["code"], message)))
    return findings


def ann401_findings() -> list[str]:
    done = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "ANN401"]
        + ["--output-format=json", "src/"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if done.returncode not in (0, 1):
        sys.exit(f"ruff failed to run:\n{done.stdout}{done.stderr}")
    return [
        SEPARATOR.join(
            (str(Path(item["filename"]).relative_to(ROOT)), item["code"], item["message"])
        )
        for item in json.loads(done.stdout)
    ]


def current_findings() -> Counter[str]:
    return Counter(mypy_findings() + ann401_findings())


def baseline_findings() -> Counter[str]:
    return Counter(BASELINE.read_text().splitlines())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--regenerate", action="store_true", help="rewrite the baseline from today's findings"
    )
    found = current_findings()
    if parser.parse_args().regenerate:
        BASELINE.write_text("".join(f"{line}\n" for line in sorted(found.elements())))
        print(f"type_check: baseline holds {found.total()} findings")
        return 0
    known = baseline_findings()
    new, fixed = found - known, known - found
    for line in sorted(new.elements()):
        print(f"type_check: NEW {line}")
    for line in sorted(fixed.elements()):
        print(f"type_check: FIXED but still in the baseline {line}")
    if new or fixed:
        print(f"type_check: fix the new findings; after a real fix run: {REGENERATE}")
        return 1
    print(f"type_check: {found.total()} findings, all in the baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())

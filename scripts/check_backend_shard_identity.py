"""CI guard: the backend shards together ran every collected test exactly once.

Each junit record carries its node id (tests/support/node_id_record.py), so the node ids the
shards' reports hold are compared by identity with the listing of `pytest --collect-only -q`.
A skipped, expected-to-fail or failed case is reported like any other; whether the cases passed
stays with each shard's own result.

Run from the project root, with the expected number of reports and the reports' paths:

    python scripts/check_backend_shard_identity.py collected.txt 4 reports/shard-*.xml
"""
# ruff: noqa: T201 - this check reports the shards' differences on stderr

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "tests"))
from support.node_id_record import NODE_ID_PROPERTY  # noqa: E402

MAX_NAMED_IDS = 10
NODE_ID_SEPARATOR = "::"
JUNIT_ROOT_TAGS = frozenset({"testsuites", "testsuite"})


@dataclass(frozen=True)
class ShardReport:
    """The node ids one readable report holds, one per record that carries one."""

    name: str
    node_ids: tuple[str, ...]
    records_without_node_id: int


@dataclass(frozen=True)
class UnreadableReport:
    name: str
    reason: str


def parse_listing(text: str) -> list[str]:
    """The node ids `pytest --collect-only -q` prints: the lines before its first blank line."""
    node_ids = []
    for line in text.splitlines():
        if not line.strip():
            break
        if NODE_ID_SEPARATOR not in line:
            message = f"line is not a node id: {line!r}"
            raise ValueError(message)
        node_ids.append(line)
    return node_ids


def parse_report(name: str, text: str) -> ShardReport | UnreadableReport:
    try:
        root = ET.fromstring(text)  # noqa: S314 - the report of this CI run's own shard
    except ET.ParseError as error:
        return UnreadableReport(name, f"not XML ({error})")
    if root.tag not in JUNIT_ROOT_TAGS:
        return UnreadableReport(name, f"not a junit report (root element {root.tag!r})")
    node_ids: list[str] = []
    without_node_id = 0
    for case in root.iter("testcase"):
        recorded = [
            prop.attrib.get("value", "")
            for prop in case.iterfind("properties/property")
            if prop.attrib.get("name") == NODE_ID_PROPERTY
        ]
        recorded = [value for value in recorded if value]
        node_ids.extend(recorded)
        without_node_id += not recorded
    return ShardReport(name, tuple(node_ids), without_node_id)


def _named(heading: str, node_ids: Iterable[str]) -> str:
    ordered = sorted(node_ids)
    lines = [f"{len(ordered)} {heading}:", *(f"  {node_id}" for node_id in ordered[:MAX_NAMED_IDS])]
    if len(ordered) > MAX_NAMED_IDS:
        lines.append(f"  ... and {len(ordered) - MAX_NAMED_IDS} more")
    return "\n".join(lines)


def _report_problems(reports: Sequence[ShardReport | UnreadableReport]) -> list[str]:
    problems = []
    for report in reports:
        if isinstance(report, UnreadableReport):
            problems.append(f"cannot read report {report.name}: {report.reason}")
        elif not report.node_ids and not report.records_without_node_id:
            problems.append(f"report {report.name} has no record")
        elif report.records_without_node_id:
            problems.append(
                f"report {report.name} has {report.records_without_node_id} "
                "records without a node id"
            )
    return problems


def _collection_problems(collected: Sequence[str]) -> list[str]:
    if not collected:
        return ["the collected listing holds no node id"]
    listed_twice = [node_id for node_id, count in Counter(collected).items() if count > 1]
    if listed_twice:
        return [_named("node ids listed twice in the collected listing", listed_twice)]
    return []


def find_problems(
    collected: Sequence[str],
    reports: Sequence[ShardReport | UnreadableReport],
    expected_reports: int,
) -> list[str]:
    """Every way the reports fail to hold each collected node id exactly once."""
    problems = _collection_problems(collected)
    if len(reports) != expected_reports:
        problems.append(f"expected {expected_reports} reports, got {len(reports)}")
    problems += _report_problems(reports)
    reported = Counter(
        node_id
        for report in reports
        if isinstance(report, ShardReport)
        for node_id in report.node_ids
    )
    for heading, node_ids in (
        ("node ids reported more than once", [i for i, n in reported.items() if n > 1]),
        ("node ids reported but not collected", reported.keys() - set(collected)),
        ("collected node ids in no report", set(collected) - reported.keys()),
    ):
        if node_ids:
            problems.append(_named(heading, node_ids))
    return problems


def _read_report(path: Path) -> ShardReport | UnreadableReport:
    try:
        return parse_report(str(path), path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        return UnreadableReport(str(path), str(error))


def _expected_reports(text: str) -> int:
    count = int(text)
    if count < 1:
        message = f"must be at least 1, got {count}"
        raise argparse.ArgumentTypeError(message)
    return count


def main(arguments: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog=Path(__file__).name, description=__doc__.splitlines()[0])
    parser.add_argument("listing", type=Path, help="the output of pytest --collect-only -q")
    parser.add_argument("expected_reports", type=_expected_reports)
    parser.add_argument("reports", nargs="*", type=Path, help="the shards' junit reports")
    options = parser.parse_args(arguments)
    try:
        collected = parse_listing(options.listing.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"cannot read the collected listing {options.listing}: {error}", file=sys.stderr)
        return 1
    reports = [_read_report(path) for path in options.reports]
    problems = find_problems(collected, reports, options.expected_reports)
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print(f"{len(collected)} collected tests, each in one of {len(reports)} reports")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

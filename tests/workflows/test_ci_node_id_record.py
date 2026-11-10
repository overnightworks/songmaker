"""The shards are compared with the collected tests by the node id each junit record carries."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from support.node_id_record import NODE_ID_PROPERTY

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

SAMPLE_CONFTEST = """
pytest_plugins = ["support.node_id_record"]
"""

SAMPLE_TESTS = """
import pytest


def test_plain():
    pass


class TestGroup:
    def test_inside_a_class(self):
        pass


@pytest.mark.parametrize("value", ["with space", "a::b", "[bracket]", "dotted.name"])
def test_parametrised(value):
    pass


@pytest.mark.skip(reason="not run")
def test_skipped():
    pass
"""


def collected_node_ids(suite: pytest.Pytester) -> list[str]:
    result = suite.runpytest_subprocess("--collect-only", "-q", "-p", "no:cacheprovider")
    return [line for line in result.outlines if "::" in line]


def recorded_node_ids(report: Path) -> list[list[str]]:
    return [
        [
            prop.attrib["value"]
            for prop in case.iter("property")  # noqa: S314 - the test's own junit report
            if prop.attrib["name"] == NODE_ID_PROPERTY
        ]
        for case in ET.parse(report).iter("testcase")  # noqa: S314 - the test's own junit report
    ]


@pytest.mark.parametrize("workers", [[], ["-n", "2"]], ids=["one process", "two workers"])
def test_each_junit_record_carries_its_node_id_as_collect_only_prints_it(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, workers: list[str]
):
    monkeypatch.setenv("PYTHONPATH", str(REPOSITORY_ROOT / "tests"))
    pytester.makeconftest(SAMPLE_CONFTEST)
    pytester.makepyfile(test_sample=SAMPLE_TESTS)
    report = pytester.path / "junit.xml"

    pytester.runpytest_subprocess("-p", "no:cacheprovider", f"--junitxml={report}", *workers)

    recorded = recorded_node_ids(report)
    assert all(len(values) == 1 for values in recorded)
    assert sorted(values[0] for values in recorded) == sorted(collected_node_ids(pytester))

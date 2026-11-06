"""CI learns which cases are database cases from the junit record, not from module names."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

pytest_plugins = ["pytester"]

SAMPLE_CONFTEST = """
import pytest

pytest_plugins = ["support.database_case_record"]


@pytest.fixture(scope="session")
def postgresql_databases():
    return object()


@pytest.fixture
def world_through_a_helper(postgresql_databases):
    return postgresql_databases
"""

SAMPLE_TESTS = """
def test_uses_the_database_through_a_helper(world_through_a_helper):
    pass


def test_needs_no_database():
    pass
"""


def test_a_case_reaching_the_database_fixture_through_a_helper_is_recorded(
    pytester: pytest.Pytester,
):
    pytester.makeconftest(SAMPLE_CONFTEST)
    pytester.makepyfile(test_sample=SAMPLE_TESTS)
    report = pytester.path / "junit.xml"

    pytester.runpytest_inprocess(f"--junitxml={report}")

    recorded = {
        case.attrib["name"]: [prop.attrib["name"] for prop in case.iter("property")]
        for case in ET.parse(report).iter("testcase")
    }
    assert recorded == {
        "test_uses_the_database_through_a_helper": ["database_case"],
        "test_needs_no_database": [],
    }

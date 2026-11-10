"""The backend shards' reports pass only when together they hold every collected test once.

The collection and the reports come from pytest itself: a small suite is collected once and run in
two parts through the repository's own shard selection, and each refusal is a damaged copy of them.
"""

from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts" / "check_backend_shard_identity.py"
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
import check_backend_shard_identity as checker  # noqa: E402

SHARDS = 2

SUITE_CONFTEST = f"""
import importlib.util

pytest_plugins = ["support.node_id_record"]

_spec = importlib.util.spec_from_file_location(
    "repository_conftest", {str(REPOSITORY_ROOT / "tests" / "conftest.py")!r}
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
pytest_collection_modifyitems = _module.pytest_collection_modifyitems
pytest_configure = _module.pytest_configure
"""

SUITE_TESTS = """
import pytest


def test_plain():
    pass


class TestGroup:
    def test_inside_a_class(self):
        pass

    def test_inside_a_class_again(self):
        pass


@pytest.mark.parametrize("value", ["with space", "a::b", "[bracket]", "dotted.name", 1, 2, 3, 4])
def test_parametrised(value):
    pass


@pytest.mark.skip(reason="not run")
def test_skipped():
    pass


@pytest.mark.xfail(reason="expected to fail")
def test_expected_to_fail():
    assert False


def test_failing():
    assert False
"""


@dataclass(frozen=True)
class Scenario:
    """What the script is given: the listing text, the reports' texts and the count it expects."""

    listing: str
    reports: tuple[str, ...]
    expected_reports: int = SHARDS


@pytest.fixture(scope="module")
def pytest_output(tmp_path_factory: pytest.TempPathFactory) -> Scenario:
    """The real collection and the real reports of the small suite, written once."""
    suite = tmp_path_factory.mktemp("suite")
    (suite / "conftest.py").write_text(SUITE_CONFTEST)
    (suite / "test_sample.py").write_text(SUITE_TESTS)
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("TEST_SHARD")
    }
    environment["PYTHONPATH"] = f"{REPOSITORY_ROOT / 'tests'}:{REPOSITORY_ROOT / 'src'}"

    def run_pytest(*arguments: str, **shard_variables: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - the interpreter running this test
            [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *arguments],
            cwd=suite,
            env=environment | shard_variables,
            capture_output=True,
            text=True,
            check=False,
        )

    listing = run_pytest("--collect-only", "-q").stdout
    reports = []
    for shard in range(1, SHARDS + 1):
        report = suite / f"junit-{shard}.xml"
        run_pytest(f"--junitxml={report}", TEST_SHARD=str(shard), TEST_SHARDS=str(SHARDS))
        reports.append(report.read_text())
    return Scenario(listing, tuple(reports))


def damaged(report: str, damage: Callable[[ET.Element], None]) -> str:
    root = ET.fromstring(report)  # noqa: S314 - a report pytest wrote for this test
    damage(root)
    return ET.tostring(root, encoding="unicode")


def cases_of(root: ET.Element) -> list[ET.Element]:
    return list(root.iter("testcase"))


def node_id_of(case: ET.Element) -> str:
    return case.find("properties/property").attrib["value"]  # type: ignore[union-attr]


def remove_a_case(root: ET.Element) -> None:
    suite = root.find("testsuite")
    suite.remove(cases_of(root)[0])  # type: ignore[union-attr]


def remove_every_case(root: ET.Element) -> None:
    for case in cases_of(root):
        root.find("testsuite").remove(case)  # type: ignore[union-attr]


def remove_the_property_of_a_case(root: ET.Element) -> None:
    case = cases_of(root)[0]
    case.remove(case.find("properties"))  # type: ignore[arg-type]


def repeat_a_case(root: ET.Element) -> None:
    root.find("testsuite").append(cases_of(root)[0])  # type: ignore[union-attr]


def rename_a_node_id(root: ET.Element) -> None:
    cases_of(root)[0].find("properties/property").set("value", "tests/gone.py::test_gone")  # type: ignore[union-attr]


def with_a_case_of(report: str, other: str) -> str:
    foreign_case = cases_of(ET.fromstring(other))[0]  # noqa: S314 - a real report
    return damaged(report, lambda root: root.find("testsuite").append(foreign_case))  # type: ignore[union-attr]


def with_report(scenario: Scenario, index: int, report: str) -> tuple[str, ...]:
    reports = list(scenario.reports)
    reports[index] = report
    return tuple(reports)


def first_node_id(report: str) -> str:
    return node_id_of(cases_of(ET.fromstring(report))[0])  # noqa: S314 - the test's own report


# Each refusal: a damaged copy of the real output, the cause the script names, and the id it names.
REFUSALS: dict[str, Callable[[Scenario], tuple[Scenario, str, str | None]]] = {
    "fewer reports than expected": lambda real: (
        Scenario(real.listing, real.reports[:1]),
        "expected 2 reports, got 1",
        None,
    ),
    "more reports than expected": lambda real: (
        Scenario(real.listing, real.reports + real.reports[:1]),
        "expected 2 reports, got 3",
        None,
    ),
    "a report that is no XML": lambda real: (
        Scenario(real.listing, with_report(real, 0, real.reports[0][:200])),
        "cannot read report",
        None,
    ),
    "a report without a record": lambda real: (
        Scenario(real.listing, with_report(real, 0, damaged(real.reports[0], remove_every_case))),
        "has no record",
        None,
    ),
    "a record without the node id": lambda real: (
        Scenario(
            real.listing,
            with_report(real, 0, damaged(real.reports[0], remove_the_property_of_a_case)),
        ),
        "records without a node id",
        None,
    ),
    "an id in two records of one report": lambda real: (
        Scenario(real.listing, with_report(real, 0, damaged(real.reports[0], repeat_a_case))),
        "reported more than once",
        first_node_id(real.reports[0]),
    ),
    "an id in two reports": lambda real: (
        Scenario(
            real.listing,
            with_report(real, 1, with_a_case_of(real.reports[1], real.reports[0])),
        ),
        "reported more than once",
        first_node_id(real.reports[0]),
    ),
    "an id that was not collected": lambda real: (
        Scenario(real.listing, with_report(real, 0, damaged(real.reports[0], rename_a_node_id))),
        "reported but not collected",
        "tests/gone.py::test_gone",
    ),
    "a collected id in no report": lambda real: (
        Scenario(real.listing, with_report(real, 0, damaged(real.reports[0], remove_a_case))),
        "in no report",
        first_node_id(real.reports[0]),
    ),
    "an empty listing": lambda real: (
        Scenario("", real.reports),
        "holds no node id",
        None,
    ),
    "an id twice in the listing": lambda real: (
        Scenario(first_node_id(real.reports[0]) + "\n" + real.listing, real.reports),
        "listed twice",
        first_node_id(real.reports[0]),
    ),
}


def run_script(
    tmp_path: Path, scenario: Scenario, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str]:
    listing = tmp_path / "collected.txt"
    listing.write_text(scenario.listing)
    paths = []
    for index, report in enumerate(scenario.reports):
        paths.append(tmp_path / f"report-{index}.xml")
        paths[-1].write_text(report)
    status = checker.main([str(listing), str(scenario.expected_reports), *map(str, paths)])
    return status, capsys.readouterr().err


def test_the_reports_of_all_parts_pass(pytest_output, tmp_path, capsys):
    status, problems = run_script(tmp_path, pytest_output, capsys)

    assert (status, problems) == (0, "")


def test_a_skipped_an_expected_to_fail_and_a_failed_case_count_as_reported(pytest_output):
    reported = [
        child.tag
        for report in pytest_output.reports
        for case in ET.fromstring(report).iter("testcase")  # noqa: S314 - a real report
        for child in case
    ]

    assert {"skipped", "failure"} <= set(reported)


@pytest.mark.parametrize("refusal", REFUSALS)
def test_a_damaged_input_fails_and_names_its_cause(pytest_output, tmp_path, capsys, refusal):
    scenario, cause, node_id = REFUSALS[refusal](pytest_output)

    status, problems = run_script(tmp_path, scenario, capsys)

    assert status != 0
    assert cause in problems
    assert node_id is None or node_id in problems


def test_a_missing_report_file_fails_and_names_it(pytest_output, tmp_path, capsys):
    status, _ = run_script(tmp_path, pytest_output, capsys)
    assert status == 0

    missing = tmp_path / "missing.xml"
    status = checker.main(
        [str(tmp_path / "collected.txt"), "2", str(tmp_path / "report-0.xml"), str(missing)]
    )

    assert status != 0
    assert str(missing) in capsys.readouterr().err


def test_a_missing_listing_fails_and_names_it(pytest_output, tmp_path, capsys):
    missing = tmp_path / "missing.txt"

    status = checker.main([str(missing), "1"])

    assert status != 0
    assert str(missing) in capsys.readouterr().err


def test_the_ids_it_names_are_bounded(pytest_output, tmp_path, capsys):
    invented = [f"tests/invented.py::test_{number}" for number in range(checker.MAX_NAMED_IDS * 3)]
    scenario = Scenario("\n".join(invented) + "\n" + pytest_output.listing, pytest_output.reports)

    _, problems = run_script(tmp_path, scenario, capsys)

    assert sum(node_id in problems for node_id in invented) == checker.MAX_NAMED_IDS
    assert f"{len(invented) - checker.MAX_NAMED_IDS} more" in problems


@pytest.mark.parametrize("refusal", ["fewer reports than expected", None])
def test_the_command_exits_with_the_verdict(pytest_output, tmp_path, refusal):
    scenario = pytest_output if refusal is None else REFUSALS[refusal](pytest_output)[0]
    (tmp_path / "collected.txt").write_text(scenario.listing)
    paths = []
    for index, report in enumerate(scenario.reports):
        paths.append(tmp_path / f"report-{index}.xml")
        paths[-1].write_text(report)

    result = subprocess.run(  # noqa: S603 - the interpreter running this test
        [
            sys.executable,
            str(SCRIPT),
            str(tmp_path / "collected.txt"),
            str(scenario.expected_reports),
            *map(str, paths),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert (result.returncode == 0) == (refusal is None)

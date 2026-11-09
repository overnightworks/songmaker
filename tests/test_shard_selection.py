"""A run with TEST_SHARD and TEST_SHARDS keeps one stable share of the collection."""

from __future__ import annotations

import re
from itertools import combinations
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
SHARD_VARIABLE = "TEST_SHARD"
SHARDS_VARIABLE = "TEST_SHARDS"

REPOSITORY_CONFTEST = str(REPOSITORY_ROOT / "tests" / "conftest.py")
LOAD_REPOSITORY_CONFTEST = f"""
import importlib.util

_spec = importlib.util.spec_from_file_location("repository_conftest", {REPOSITORY_CONFTEST!r})
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
pytest_collection_modifyitems = _module.pytest_collection_modifyitems
pytest_configure = _module.pytest_configure
"""


@pytest.fixture
def small_suite(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    """A collection of forty-odd tests in three files that loads the repository's conftest hook."""
    monkeypatch.delenv(SHARD_VARIABLE, raising=False)
    monkeypatch.delenv(SHARDS_VARIABLE, raising=False)
    monkeypatch.setenv("PYTHONPATH", f"{REPOSITORY_ROOT / 'tests'}:{REPOSITORY_ROOT / 'src'}")
    pytester.makeconftest(LOAD_REPOSITORY_CONFTEST)
    body = (
        "import pytest\n\n"
        "@pytest.mark.parametrize('value', range(15))\n"
        "def test_case(value):\n    pass\n\n"
        "def test_plain():\n    pass\n"
    )
    for name in ("test_first.py", "test_second.py", "test_third.py"):
        pytester.makepyfile(**{name.removesuffix(".py"): body})
    return pytester


def run_suite(
    suite: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    shard: str | None,
    shards: str | None,
    *arguments: str,
):
    for variable, value in ((SHARD_VARIABLE, shard), (SHARDS_VARIABLE, shards)):
        if value is not None:
            monkeypatch.setenv(variable, value)
    return suite.runpytest_subprocess("-q", "-p", "no:cacheprovider", "-rp", *arguments)


def passed_node_ids(result: pytest.RunResult) -> set[str]:
    return set(re.findall(r"^PASSED (\S+)", result.stdout.str(), flags=re.MULTILINE))


def test_without_the_variables_everything_is_selected(small_suite, monkeypatch):
    result = run_suite(small_suite, monkeypatch, None, None)

    assert result.ret == 0
    assert len(passed_node_ids(result)) == 48


@pytest.mark.parametrize("shards", [2, 3])
def test_the_shards_are_disjoint_and_together_the_whole_collection(
    small_suite, monkeypatch, shards
):
    whole = passed_node_ids(run_suite(small_suite, monkeypatch, None, None))

    parts = []
    for index in range(1, shards + 1):
        result = run_suite(small_suite, monkeypatch, str(index), str(shards))
        assert result.ret == 0
        parts.append(passed_node_ids(result))

    assert all(parts)
    assert all(first.isdisjoint(second) for first, second in combinations(parts, 2))
    assert set().union(*parts) == whole


def test_a_node_id_lands_in_the_same_shard_in_two_runs_and_under_xdist(small_suite, monkeypatch):
    first = passed_node_ids(run_suite(small_suite, monkeypatch, "2", "3"))
    second = passed_node_ids(run_suite(small_suite, monkeypatch, "2", "3"))
    parallel = passed_node_ids(run_suite(small_suite, monkeypatch, "2", "3", "-n", "2"))

    assert first
    assert first == second == parallel


def test_deselected_tests_are_reported(small_suite, monkeypatch):
    result = run_suite(small_suite, monkeypatch, "1", "2")

    kept = len(passed_node_ids(result))
    assert re.search(rf"{48 - kept} deselected", result.stdout.str())


@pytest.mark.parametrize("worker_arguments", [(), ("-n", "2")], ids=["serial", "xdist"])
@pytest.mark.parametrize(
    ("shard", "shards", "variable"),
    [
        ("1", None, SHARDS_VARIABLE),
        (None, "2", SHARD_VARIABLE),
        ("one", "2", SHARD_VARIABLE),
        ("1", "two", SHARDS_VARIABLE),
        ("1", "0", SHARDS_VARIABLE),
        ("0", "2", SHARD_VARIABLE),
        ("3", "2", SHARD_VARIABLE),
    ],
)
def test_a_malformed_setting_ends_the_run_before_any_test_runs(
    small_suite, monkeypatch, shard, shards, variable, worker_arguments
):
    result = run_suite(small_suite, monkeypatch, shard, shards, *worker_arguments)

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "INTERNALERROR" not in result.stdout.str() + result.stderr.str()
    assert passed_node_ids(result) == set()
    assert re.search(rf"ERROR: .*{variable}", result.stderr.str() + result.stdout.str())

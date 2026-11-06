"""Which GitHub workflow runs auto-deploy leaves out of its judgement of a release commit.

Dependabot update runs and Release runs judge nothing about the commit they
are attached to; every other run still decides.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from auto_deploy_harness import (
    Checkout,
)
from auto_deploy_support import (
    CHECK_RUN_APPEARANCE_GRACE_SECONDS,
    DEPENDABOT_UPDATES_WORKFLOW_PATH,
    UPDATE_CHECK_SUITE_ID,
)

RELEASE_WORKFLOW_PATH = ".github/workflows/release.yml"
CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
CODE_SCANNING_WORKFLOW_PATH = "dynamic/github-code-scanning/codeql"
OTHER_CHECK_SUITE_ID = "3000"
IGNORED_JOB_NAME = "Ignored run job"

PASSED_CI = ("completed", "success")
FAILED_CI = ("completed", "failure")
IGNORED_RUN = ("github-actions", IGNORED_JOB_NAME)
FAILED_IGNORED_RUN = (*IGNORED_RUN, "completed", "failure", UPDATE_CHECK_SUITE_ID)
PASSED_IGNORED_RUN = (*IGNORED_RUN, "completed", "success", UPDATE_CHECK_SUITE_ID)
RUNNING_IGNORED_RUN = (*IGNORED_RUN, "in_progress", "", UPDATE_CHECK_SUITE_ID)
# The path of the ignored kind under test, filled in by the test.
IGNORED_SUITE = (UPDATE_CHECK_SUITE_ID, None)


@pytest.fixture
def checkout(tmp_path: Path) -> Checkout:
    """A deploy checkout that has adopted its starting commit as running."""
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    return checkout


@pytest.mark.parametrize(
    "ignored_path",
    [DEPENDABOT_UPDATES_WORKFLOW_PATH, RELEASE_WORKFLOW_PATH],
    ids=["dependabot-update", "release"],
)
@pytest.mark.parametrize(
    ("check_runs", "workflow_runs", "grace_elapsed", "outcome"),
    [
        pytest.param([PASSED_CI, FAILED_IGNORED_RUN], [IGNORED_SUITE], False, "deploys", id="D1"),
        pytest.param([FAILED_CI, PASSED_IGNORED_RUN], [IGNORED_SUITE], False, "failed", id="D2"),
        pytest.param([PASSED_IGNORED_RUN], [IGNORED_SUITE], False, "waiting", id="D3"),
        pytest.param([PASSED_IGNORED_RUN], [IGNORED_SUITE], True, "failed", id="D4"),
        pytest.param(
            [PASSED_IGNORED_RUN, ("completed", "skipped"), ("completed", "neutral")],
            [IGNORED_SUITE],
            False,
            "failed",
            id="D4a",
        ),
        pytest.param(
            [PASSED_IGNORED_RUN, ("in_progress", "")],
            [IGNORED_SUITE],
            False,
            "waiting",
            id="D4b",
        ),
        pytest.param(
            [PASSED_IGNORED_RUN, ("unheard_of", "")],
            [IGNORED_SUITE],
            False,
            "refused",
            id="D4c",
        ),
        pytest.param(
            [PASSED_CI, RUNNING_IGNORED_RUN],
            [IGNORED_SUITE],
            False,
            "deploys",
            id="D5",
        ),
        pytest.param(
            [PASSED_CI, (*IGNORED_RUN, "completed", "failure")],
            [IGNORED_SUITE],
            False,
            "failed",
            id="D6",
        ),
        pytest.param(
            [PASSED_CI, ("github-actions", "CodeQL", "completed", "failure", OTHER_CHECK_SUITE_ID)],
            [(OTHER_CHECK_SUITE_ID, CODE_SCANNING_WORKFLOW_PATH)],
            False,
            "failed",
            id="D7",
        ),
        pytest.param([PASSED_CI, ("completed", "failure")], [], False, "failed", id="D9"),
        pytest.param([PASSED_CI], [], False, "deploys", id="D9-green"),
    ],
)
def test_only_the_check_suites_of_ignored_runs_leave_the_deploy_guard(
    checkout: Checkout,
    ignored_path: str,
    check_runs: list[tuple[str, ...]],
    workflow_runs: list[tuple[str, str | None]],
    grace_elapsed: bool,
    outcome: str,
) -> None:
    """An ignored run never decides, it never loosens either."""

    checkout.move_main_forward()
    candidate = checkout.remote_main_sha()
    checkout.set_check_runs(*check_runs)
    checkout.set_workflow_runs(*[(suite, path or ignored_path) for suite, path in workflow_runs])
    if grace_elapsed:
        assert checkout.tick().returncode == 0
        checkout.advance_clock(CHECK_RUN_APPEARANCE_GRACE_SECONDS)

    result = checkout.tick()

    assert result.returncode == 0
    assert (checkout.deployed_sha_file.read_text() == candidate) == (outcome == "deploys")
    assert ("cannot determine GitHub check status" in checkout.journal) == (outcome == "refused")
    waited = outcome == "waiting" or grace_elapsed
    assert (f"{candidate} is not green: waiting" in checkout.journal) == waited
    assert (f"{candidate} is not green: failed" in checkout.journal) == (outcome == "failed")


@pytest.mark.parametrize(
    ("event", "path"),
    [
        ("workflow_dispatch", CI_WORKFLOW_PATH),
        ("workflow_dispatch", ".github/workflows/e2e.yml"),
        ("push", CI_WORKFLOW_PATH),
        ("workflow_dispatch", ".github/workflows/release-notes.yml"),
        ("workflow_dispatch", ".github/workflows/release.yml.bak"),
        ("workflow_dispatch", "x/.github/workflows/release.yml"),
    ],
    ids=[
        "dispatched-ci",
        "dispatched-e2e",
        "pushed-ci",
        "release-lookalike",
        "release-suffixed",
        "release-prefixed",
    ],
)
def test_a_failed_run_of_another_workflow_is_judged_whatever_started_it(
    checkout: Checkout,
    event: str,
    path: str,
) -> None:
    """Only the Release workflow's own path leaves the judgement, never an event."""

    checkout.move_main_forward()
    candidate = checkout.remote_main_sha()
    checkout.set_check_runs(
        PASSED_CI,
        ("github-actions", "Job", "completed", "failure", OTHER_CHECK_SUITE_ID),
    )
    checkout.set_workflow_runs_raw_response(
        '{"total_count":1,"workflow_runs":'
        f'[{{"check_suite_id":{OTHER_CHECK_SUITE_ID},"path":"{path}","event":"{event}"}}]}}',
    )

    result = checkout.tick()

    assert result.returncode == 0
    assert checkout.deployed_sha_file.read_text() != candidate
    assert f"{candidate} is not green: failed" in checkout.journal


@pytest.mark.parametrize("other_run_listed", [False, True], ids=["unlisted", "ci-run"])
def test_a_check_run_named_like_a_release_job_in_another_suite_is_judged(
    checkout: Checkout,
    other_run_listed: bool,
) -> None:
    """A suite leaves the judgement by its workflow run, never by a job name."""

    checkout.move_main_forward()
    candidate = checkout.remote_main_sha()
    checkout.set_check_runs(
        PASSED_CI,
        ("github-actions", "Release", "completed", "failure", OTHER_CHECK_SUITE_ID),
    )
    listed = [(UPDATE_CHECK_SUITE_ID, RELEASE_WORKFLOW_PATH)]
    if other_run_listed:
        listed.append((OTHER_CHECK_SUITE_ID, CI_WORKFLOW_PATH))
    checkout.set_workflow_runs(*listed)

    result = checkout.tick()

    assert result.returncode == 0
    assert checkout.deployed_sha_file.read_text() != candidate
    assert f"{candidate} is not green: failed" in checkout.journal

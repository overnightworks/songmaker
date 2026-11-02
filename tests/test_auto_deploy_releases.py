"""Which commit scripts/auto-deploy.sh puts live: only a release tag, never a main tip.

The script is driven as a real subprocess against a throwaway checkout and its
own origin (see ``auto_deploy_harness``). A landing on main deploys nothing;
a tag ``vYYYY.MM.DD.N`` on a green main commit does, checked out detached.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest
from auto_deploy_harness import (
    Checkout,
)
from auto_deploy_support import (
    CHECK_RUN_APPEARANCE_GRACE_SECONDS,
    DEPENDABOT_UPDATES_WORKFLOW_PATH,
    FAILURE_ALERT_THRESHOLD,
    UPDATE_CHECK_SUITE_ID,
    git,
    git_output,
)

CODE_SCANNING_WORKFLOW_PATH = "dynamic/github-code-scanning/codeql"
OTHER_CHECK_SUITE_ID = "3000"
UPDATE_RUN = ("github-actions", "Dependabot", "completed", "failure", UPDATE_CHECK_SUITE_ID)
UPDATE_SUITE = (UPDATE_CHECK_SUITE_ID, DEPENDABOT_UPDATES_WORKFLOW_PATH)
PASSED_UPDATE_RUN = ("github-actions", "Dependabot", "completed", "success", UPDATE_CHECK_SUITE_ID)
PASSED_CI = ("completed", "success")
FAILED_CI = ("completed", "failure")

OFF_GRAMMAR_TAGS = ["v1.0", "v2026.1.5.1", "v2026.10.25.01", "v2026.02.30.1"]


@pytest.fixture
def checkout(tmp_path: Path) -> Checkout:
    """A deploy checkout that has adopted its starting commit as running."""
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    return checkout


def _deployed_sha(checkout: Checkout) -> str:
    return checkout.deployed_sha_file.read_text()


def _failure_count(checkout: Checkout) -> str:
    path = checkout.failure_count_file
    return path.read_text() if path.exists() else "0"


def _is_detached(checkout: Checkout) -> bool:
    return not (checkout.root / ".git" / "HEAD").read_text().startswith("ref:")


def test_a_landing_on_main_without_a_tag_deploys_nothing(checkout: Checkout) -> None:
    """defect:#1880 cell T1 -- main moves without a tag, nothing deploys."""

    before = checkout.head
    checkout.move_main_forward(release=False)

    result = checkout.tick()

    assert result.returncode == 0
    assert checkout.build_and_recreate_calls == []
    assert checkout.head == before
    assert _deployed_sha(checkout) == before
    assert _failure_count(checkout) == "0"


def test_a_release_tag_deploys_its_commit_detached_and_the_journal_names_the_tag(
    checkout: Checkout,
) -> None:
    """defect:#1880 cell T2 -- a tag deploys its commit detached and the journal names the tag."""

    checkout.move_main_forward()
    tag = "v2026.10.25.1"
    commit = checkout.commit_of(tag)

    result = checkout.tick()

    assert result.returncode == 0
    assert checkout.head == commit
    assert _is_detached(checkout)
    assert "image inspect" in checkout.docker_calls
    assert any("compose build" in call for call in checkout.build_and_recreate_calls)
    assert any(call.startswith("compose up") for call in checkout.build_and_recreate_calls)
    assert _deployed_sha(checkout) == commit
    assert any(tag in line and commit in line for line in checkout.journal.splitlines())


def test_the_tick_builds_and_recreates_with_the_release_tag_and_commit_it_deploys(
    checkout: Checkout,
) -> None:
    """defect:#2009 -- compose build and compose up see the tag and its full commit."""

    checkout.move_main_forward()
    tag = "v2026.10.25.1"
    commit = checkout.commit_of(tag)

    result = checkout.tick()

    runs = checkout.release_env_of_build_and_recreate_calls
    assert result.returncode == 0
    assert any("compose build" in call for call in runs)
    assert any(call.startswith("compose up") for call in runs)
    assert set(runs.values()) == {(tag, commit)}


def test_untagged_commits_after_a_release_do_not_deploy(checkout: Checkout) -> None:
    """defect:#1880 cell T3 -- the tag's commit deploys, not the tip of main."""

    checkout.move_main_forward()
    released = checkout.commit_of("v2026.10.25.1")
    checkout.move_main_forward(release=False)
    checkout.move_main_forward(release=False)

    result = checkout.tick()

    assert result.returncode == 0
    assert checkout.head == released
    assert _deployed_sha(checkout) == released


def test_a_tag_on_a_side_branch_is_skipped_and_named_and_the_older_release_deploys(
    checkout: Checkout,
) -> None:
    """defect:#1880 cell T4 -- a side-branch tag is skipped and named once."""

    checkout.move_main_forward()
    released = checkout.commit_of("v2026.10.25.1")
    pusher = checkout.root.parent / "pusher"
    git(pusher, "checkout", "-b", "side")
    (pusher / "side.txt").write_text("side\n")
    git(pusher, "add", "side.txt")
    git(pusher, "commit", "-m", "side commit")
    checkout.cut_release(pusher, name="v2026.10.25.2")
    git(pusher, "checkout", "main")

    first = checkout.tick()
    second = checkout.tick()

    assert first.returncode == second.returncode == 0
    assert checkout.head == released
    skipped = [
        line for line in checkout.journal.splitlines() if "skipping tag v2026.10.25.2:" in line
    ]
    assert len(skipped) == 1


def test_a_skipped_red_release_is_named_once_across_ticks(checkout: Checkout) -> None:
    """defect:#1880 cell T7 -- a skipped release is named once across ticks."""

    checkout.move_main_forward()
    green_release = checkout.remote_main_sha()
    checkout.move_main_forward()
    checkout.set_check_runs_for_commit(checkout.remote_main_sha(), ("completed", "failure"))
    checkout.set_check_runs_for_commit(green_release, ("completed", "success"))
    assert checkout.tick().returncode == 0
    journal_after_deploy = checkout.journal

    assert checkout.tick().returncode == 0

    second_tick = checkout.journal[len(journal_after_deploy) :]
    assert "skipping deploy candidate" not in second_tick
    assert "selected newest" not in second_tick


def test_only_grammatical_tags_count_and_the_newest_is_ordered_by_date_then_number(
    checkout: Checkout,
) -> None:
    """defect:#1880 cell T5 -- off-grammar tags are named once; .10 is newer than .9."""

    checkout.move_main_forward(release=False)
    older = checkout.cut_release(name="v2026.10.25.9")
    checkout.move_main_forward(release=False)
    newest = checkout.cut_release(name="v2026.10.25.10")
    checkout.move_main_forward(release=False)
    for tag in OFF_GRAMMAR_TAGS:
        checkout.cut_release(name=tag)

    first = checkout.tick()
    second = checkout.tick()

    assert first.returncode == second.returncode == 0
    assert checkout.head == checkout.commit_of(newest)
    assert checkout.commit_of(older) != checkout.head
    for tag in OFF_GRAMMAR_TAGS:
        named = [line for line in checkout.journal.splitlines() if f"skipping tag {tag}:" in line]
        assert len(named) == 1


def test_local_only_tags_and_a_shadowing_local_tag_are_ignored(checkout: Checkout) -> None:
    """defect:#1880 cell T6 -- local-only and shadowing local tags are ignored."""

    checkout.move_main_forward()
    released = checkout.commit_of("v2026.10.25.1")
    checkout.move_main_forward(release=False)
    untagged = git_output(checkout.root.parent / "pusher", "rev-parse", "HEAD")
    git(checkout.root, "fetch", "--no-tags", "origin", "main")
    git(checkout.root, "tag", "v2026.10.25.99", untagged)
    git(checkout.root, "tag", "--force", "v2026.10.25.1", untagged)

    result = checkout.tick()

    assert result.returncode == 0
    assert checkout.head == released


@pytest.mark.parametrize(
    ("older_is_running", "expected_builds"),
    [(False, 1), (True, 0)],
    ids=["older green release is newer than running", "older green release is running"],
)
def test_a_red_newest_release_is_skipped_for_an_older_green_one_that_is_pending(
    checkout: Checkout, older_is_running: bool, expected_builds: int,
) -> None:
    """defect:#1880 cell T7 -- a red newest release gives way to an older pending green one."""

    checkout.move_main_forward()
    older = checkout.commit_of("v2026.10.25.1")
    if older_is_running:
        assert checkout.tick().returncode == 0
        checkout.docker_calls_file.unlink()
    checkout.move_main_forward()
    newest = checkout.commit_of("v2026.10.25.2")
    checkout.set_check_runs_for_commit(newest, ("completed", "failure"))

    result = checkout.tick()

    assert result.returncode == 0
    assert len([c for c in checkout.build_and_recreate_calls if c.startswith("compose up")]) == (
        expected_builds
    )
    assert checkout.head == older


def test_a_release_older_than_the_running_commit_never_moves_the_checkout_backwards(
    checkout: Checkout,
) -> None:
    """defect:#1880 cell T8 -- never backwards."""

    checkout.move_main_forward()
    assert checkout.tick().returncode == 0
    checkout.move_main_forward(release=False)
    git(checkout.root, "fetch", "--no-tags", "origin", "main")
    running = checkout.remote_main_sha()
    checkout.detach_at(running)
    checkout.deployed_sha_file.write_text(running)
    checkout.docker_calls_file.unlink()

    result = checkout.tick()

    assert result.returncode == 0
    assert checkout.build_and_recreate_calls == []
    assert checkout.head == running
    assert _deployed_sha(checkout) == running
    assert checkout.uncommitted_changes == ""


def test_a_checkout_on_a_branch_with_a_pending_release_is_a_counted_refusal_that_alerts(
    checkout: Checkout,
) -> None:
    """defect:#1880 cell T9 -- a branch checkout with a pending release is a counted refusal."""

    checkout.move_main_forward()
    checkout.switch_to_work_branch()
    before = checkout.head

    exit_codes = [checkout.tick().returncode for _ in range(FAILURE_ALERT_THRESHOLD)]

    assert exit_codes == [0, 0, 1]
    assert len(checkout.alert_lines()) == 1
    assert checkout.head == before
    assert git_output(checkout.root, "symbolic-ref", "--short", "HEAD") == "work"
    assert checkout.build_and_recreate_calls == []


def test_a_dirty_checkout_with_a_pending_release_is_refused(checkout: Checkout) -> None:
    """defect:#1880 cell T10 -- a dirty checkout is refused."""

    checkout.move_main_forward()
    before = checkout.head
    (checkout.root / "README.md").write_text("operator edit\n")

    result = checkout.tick()

    assert result.returncode == 0
    assert "dirty" in checkout.journal
    assert checkout.head == before
    assert checkout.build_and_recreate_calls == []
    assert _failure_count(checkout) == "1"


@pytest.mark.parametrize("state", ["garbage", "unknown commit"])
def test_an_unreadable_running_commit_counts_every_release_as_pending(
    checkout: Checkout, state: str,
) -> None:
    """defect:#1880 cell T13 -- an unreadable running commit counts every release as pending."""

    checkout.install_backup_command(exit_code=0)
    checkout.cut_release()
    commit = checkout.head
    checkout.deployed_sha_file.write_text("garbage" if state == "garbage" else "0" * 40)

    result = checkout.tick()

    assert result.returncode == 0
    assert any(call.startswith("compose up") for call in checkout.build_and_recreate_calls)
    assert _deployed_sha(checkout) == commit


def test_a_first_run_without_a_running_commit_adopts_head_and_deploys_nothing(
    tmp_path: Path,
) -> None:
    """defect:#1880 cell T13 -- a first run adopts HEAD and deploys nothing."""

    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.move_main_forward()
    before = checkout.head

    result = checkout.tick()

    assert result.returncode == 0
    assert _deployed_sha(checkout) == before
    assert checkout.build_and_recreate_calls == []


def test_a_pending_release_that_then_fails_is_not_named_again_and_is_named_by_tag(
    checkout: Checkout,
) -> None:
    """defect:#1880 cell T7 -- a skipped release is named once by tag, whatever its status."""
    checkout.move_main_forward()
    green_release = checkout.remote_main_sha()
    checkout.move_main_forward()
    red_release = checkout.remote_main_sha()
    checkout.set_check_runs_for_commit(green_release, ("completed", "success"))
    checkout.set_check_runs_for_commit(red_release, ("in_progress", ""))
    assert checkout.tick().returncode == 0
    checkout.set_check_runs_for_commit(red_release, ("completed", "failure"))
    journal_before = checkout.journal

    assert checkout.tick().returncode == 0

    named = [
        line for line in journal_before.splitlines() if "skipping deploy candidate" in line
    ]
    assert len(named) == 1
    assert "v2026.10.25.2" in named[0]
    assert "skipping deploy candidate" not in checkout.journal[len(journal_before) :]


def _checkout_on_main_with_main_moved_on(checkout: Checkout) -> str:
    checkout.adopt_current_head_as_deployed()
    checkout.log_file.unlink()
    checkout.switch_to_main()
    running = checkout.head
    checkout.move_main_forward(release=False)
    return running


@pytest.mark.parametrize(
    "release_at_running_commit", [False, True], ids=["no release", "release is running"],
)
def test_a_work_clone_on_main_with_nothing_pending_stays_untouched_and_silent(
    tmp_path: Path, release_at_running_commit: bool,
) -> None:
    """defect:#1880 cells T14/T15 -- a work clone on main stays untouched and silent."""

    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    if release_at_running_commit:
        checkout.cut_release()
    running = _checkout_on_main_with_main_moved_on(checkout)

    result = checkout.tick()

    assert result.returncode == 0
    assert checkout.journal_above_debug == []
    assert checkout.build_and_recreate_calls == []
    assert checkout.head == running
    assert git_output(checkout.root, "symbolic-ref", "--short", "HEAD") == "main"
    assert checkout.uncommitted_changes == ""
    assert _deployed_sha(checkout) == running
    assert _failure_count(checkout) == "0"


def _backup_precedes_recreate(checkout: Checkout) -> bool:
    calls = checkout.docker_calls.splitlines()
    backup = calls.index("hal backup songmaker --pre-apply")
    return backup < next(i for i, call in enumerate(calls) if call.startswith("compose up"))


def test_a_release_that_changes_the_schema_is_backed_up_once_before_the_recreate(
    checkout: Checkout,
) -> None:
    """defect:#1880 cell D8/T16 -- a changed schema is backed up once before up."""

    checkout.install_backup_command(exit_code=0)
    checkout.move_main_forward_with_migration("aaa111")
    assert checkout.tick().returncode == 0
    checkout.move_main_forward_with_migration("bbb222", down_revision="aaa111")
    before = len(checkout.backup_calls)

    result = checkout.tick()

    assert result.returncode == 0
    assert len(checkout.backup_calls) == before + 1
    assert _backup_precedes_recreate(checkout)
    assert _deployed_sha(checkout) == checkout.head


def test_a_schema_changing_release_is_backed_up_when_uv_lives_only_in_the_user_executables(
    checkout: Checkout,
) -> None:
    """defect:#2020 -- hal's launcher finds uv in ~/.local/bin, not on the unit's minimal PATH."""

    checkout.install_backup_command(exit_code=0)
    checkout.move_main_forward_with_migration("aaa111")

    result = checkout.tick()

    assert result.returncode == 0
    assert checkout.backup_calls == ["hal backup songmaker --pre-apply"]
    assert _deployed_sha(checkout) == checkout.head


def test_a_release_whose_tag_names_another_schema_than_the_running_one_is_backed_up(
    checkout: Checkout,
) -> None:
    """defect:#1880 cell D8/T16 -- the tag's schema line decides the backup."""

    checkout.install_backup_command(exit_code=0)
    checkout.move_main_forward_with_migration("aaa111")
    assert checkout.tick().returncode == 0
    checkout.move_main_forward(release=False)
    checkout.cut_release(schema="bbb222")

    result = checkout.tick()

    assert result.returncode == 0
    assert checkout.backup_calls[-1] == "hal backup songmaker --pre-apply"
    assert len(checkout.backup_calls) == 2


@pytest.mark.parametrize("backup", ["exits non-zero", "is missing"])
def test_a_failed_backup_stops_the_tick_before_anything_is_built_or_recreated(
    checkout: Checkout, backup: str,
) -> None:
    """defect:#1880 cell D8/T17 -- a failed or missing backup stops the tick."""

    if backup == "exits non-zero":
        checkout.install_backup_command(exit_code=3)
    checkout.move_main_forward_with_migration("aaa111")
    running = _deployed_sha(checkout)

    exit_codes = [checkout.tick().returncode for _ in range(FAILURE_ALERT_THRESHOLD)]

    assert exit_codes == [0, 0, 1]
    assert len(checkout.alert_lines()) == 1
    assert not any("build" in call for call in checkout.docker_calls.splitlines())
    assert not any(call.startswith("compose up") for call in checkout.docker_calls.splitlines())
    assert _deployed_sha(checkout) == running


def test_a_lightweight_tag_never_overrides_the_migration_head_with_its_commit_message(
    checkout: Checkout,
) -> None:
    """defect:#1880 cell D8/T16 -- only an annotated tag's message names a schema."""
    checkout.install_backup_command(exit_code=0)
    checkout.move_main_forward_with_migration("aaa111")
    assert checkout.tick().returncode == 0
    pusher = checkout.root.parent / "pusher"
    checkout.move_main_forward_with_migration("bbb222", down_revision="aaa111", release=False)
    git(pusher, "commit", "--amend", "-m", "migration bbb222\n\nschema: aaa111")
    git(pusher, "push", "--force", "origin", "main")
    git(pusher, "tag", "v2026.10.25.50")
    git(pusher, "push", "origin", "v2026.10.25.50")
    calls_before = len(checkout.backup_calls)

    result = checkout.tick()

    assert result.returncode == 0
    assert len(checkout.backup_calls) == calls_before + 1


def test_a_release_with_the_running_schema_is_not_backed_up(checkout: Checkout) -> None:
    """defect:#1880 cell D8/T18 -- an unchanged schema takes no backup."""

    checkout.install_backup_command(exit_code=0)
    checkout.move_main_forward_with_migration("aaa111")
    assert checkout.tick().returncode == 0
    checkout.move_main_forward()
    checkout.move_main_forward(release=False)
    checkout.cut_release(schema="aaa111")
    calls_before = len(checkout.backup_calls)

    result = checkout.tick()

    assert result.returncode == 0
    assert len(checkout.backup_calls) == calls_before
    assert _deployed_sha(checkout) == checkout.head


@pytest.mark.parametrize(
    ("check_runs", "workflow_runs", "grace_elapsed", "outcome"),
    [
        pytest.param([PASSED_CI, UPDATE_RUN], [UPDATE_SUITE], False, "deploys", id="D1"),
        pytest.param([FAILED_CI, PASSED_UPDATE_RUN], [UPDATE_SUITE], False, "failed", id="D2"),
        pytest.param([PASSED_UPDATE_RUN], [UPDATE_SUITE], False, "waiting", id="D3"),
        pytest.param([PASSED_UPDATE_RUN], [UPDATE_SUITE], True, "failed", id="D4"),
        pytest.param(
            [PASSED_UPDATE_RUN, ("completed", "skipped"), ("completed", "neutral")],
            [UPDATE_SUITE], False, "failed", id="D4a",
        ),
        pytest.param(
            [PASSED_UPDATE_RUN, ("in_progress", "")], [UPDATE_SUITE], False, "waiting", id="D4b",
        ),
        pytest.param(
            [PASSED_UPDATE_RUN, ("unheard_of", "")], [UPDATE_SUITE], False, "refused", id="D4c",
        ),
        pytest.param(
            [PASSED_CI, ("github-actions", "Dependabot", "in_progress", "", UPDATE_CHECK_SUITE_ID)],
            [UPDATE_SUITE], False, "deploys", id="D5",
        ),
        pytest.param(
            [PASSED_CI, ("github-actions", "Dependabot", "completed", "failure")],
            [UPDATE_SUITE], False, "failed", id="D6",
        ),
        pytest.param(
            [PASSED_CI, ("github-actions", "CodeQL", "completed", "failure", OTHER_CHECK_SUITE_ID)],
            [(OTHER_CHECK_SUITE_ID, CODE_SCANNING_WORKFLOW_PATH)], False, "failed", id="D7",
        ),
        pytest.param([PASSED_CI, ("completed", "failure")], [], False, "failed", id="D9"),
        pytest.param([PASSED_CI], [], False, "deploys", id="D9-green"),
    ],
)
def test_only_the_check_suites_of_dependabot_update_runs_leave_the_deploy_guard(
    checkout: Checkout,
    check_runs: list[tuple[str, ...]],
    workflow_runs: list[tuple[str, str]],
    grace_elapsed: bool,
    outcome: str,
) -> None:
    """defect:#2128 cells D1-D7, D9 -- an update run never decides, it never loosens either."""

    checkout.move_main_forward()
    candidate = checkout.remote_main_sha()
    checkout.set_check_runs(*check_runs)
    checkout.set_workflow_runs(*workflow_runs)
    if grace_elapsed:
        assert checkout.tick().returncode == 0
        checkout.advance_clock(CHECK_RUN_APPEARANCE_GRACE_SECONDS)

    result = checkout.tick()

    assert result.returncode == 0
    assert (_deployed_sha(checkout) == candidate) == (outcome == "deploys")
    assert ("cannot determine GitHub check status" in checkout.journal) == (outcome == "refused")
    waited = outcome == "waiting" or grace_elapsed
    assert (f"{candidate} is not green: waiting" in checkout.journal) == waited
    assert (f"{candidate} is not green: failed" in checkout.journal) == (outcome == "failed")


@pytest.mark.parametrize("other_run_failed", [False, True], ids=["update-only", "other-path"])
def test_a_paginated_workflow_answer_leaves_only_the_matching_suites(
    checkout: Checkout, other_run_failed: bool,
) -> None:
    """defect:#2128 cell D8d -- only update-path suites leave the judgement across pages."""

    checkout.move_main_forward()
    candidate = checkout.remote_main_sha()
    pages = [
        {"total_count": 3, "workflow_runs": [
            {"check_suite_id": 2000, "path": DEPENDABOT_UPDATES_WORKFLOW_PATH},
            {"check_suite_id": 3000, "path": CODE_SCANNING_WORKFLOW_PATH},
        ]},
        {"total_count": 3, "workflow_runs": [
            {"check_suite_id": 4000, "path": DEPENDABOT_UPDATES_WORKFLOW_PATH},
        ]},
    ]
    checkout.set_workflow_runs_raw_response("\n".join(json.dumps(page) for page in pages))
    checkout.set_check_runs(
        PASSED_CI,
        UPDATE_RUN,
        ("github-actions", "Dependabot", "completed", "failure", "4000"),
        (
            "github-actions", "CodeQL", "completed",
            "failure" if other_run_failed else "success", OTHER_CHECK_SUITE_ID,
        ),
    )

    result = checkout.tick()

    assert result.returncode == 0
    assert (_deployed_sha(checkout) == candidate) == (not other_run_failed)


def _workflow_page(*records: str, total_count: int | None = None) -> str:
    total = len(records) if total_count is None else total_count
    return f'{{"total_count":{total},"workflow_runs":[{",".join(records)}]}}'


def _run_record(suite_id: str, path: str) -> str:
    return f'{{"check_suite_id":{suite_id},"path":{json.dumps(path)}}}'


VALID_RUN = _run_record("2000", DEPENDABOT_UPDATES_WORKFLOW_PATH)


@pytest.mark.parametrize(
    "raw_response",
    [
        pytest.param('{"workflow_runs":[]}', id="no-total"),
        pytest.param('{"total_count":0}', id="no-records"),
        pytest.param("[]", id="not-an-object"),
        pytest.param("not json", id="not-json"),
        pytest.param(_workflow_page(VALID_RUN, total_count=2), id="truncated"),
        pytest.param(_workflow_page(VALID_RUN, VALID_RUN, total_count=1), id="surplus"),
        pytest.param(
            _workflow_page(VALID_RUN, total_count=3) + _workflow_page(VALID_RUN, total_count=2),
            id="page-totals-disagree",
        ),
        pytest.param(
            _workflow_page('{"path":"dynamic/dependabot/dependabot-updates"}'), id="no-suite-id",
        ),
        pytest.param(_workflow_page('{"check_suite_id":2000}'), id="no-path"),
        pytest.param(_workflow_page(_run_record('"2000"', "p")), id="string-suite-id"),
        pytest.param(_workflow_page(_run_record("2000.5", "p")), id="fractional-suite-id"),
        pytest.param(_workflow_page(_run_record("2000", "")), id="empty-path"),
        pytest.param(_workflow_page(_run_record("2000", "dynamic\u0000")), id="control-path"),
    ],
)
def test_a_malformed_workflow_run_answer_refuses_the_whole_tick(
    checkout: Checkout, raw_response: str,
) -> None:
    """defect:#2128 cells D8b, D8c -- an unusable second lookup is never read as no update runs."""

    checkout.move_main_forward()
    checkout.move_main_forward()
    before = checkout.head
    checkout.set_workflow_runs_raw_response(raw_response, checkout.remote_main_sha())

    result = checkout.tick()

    assert result.returncode == 0
    assert "cannot determine GitHub check status" in checkout.journal
    assert checkout.head == before
    assert _deployed_sha(checkout) == before


@pytest.mark.parametrize(
    ("lookup_fault", "diagnostic"),
    [
        pytest.param("fail", "GitHub API unavailable", id="fail"),
        pytest.param("term", "workflow-run lookup timed out", id="term"),
        pytest.param("kill", "workflow-run lookup was killed by SIGKILL", id="kill"),
    ],
)
def test_a_failed_workflow_run_lookup_refuses_the_tick_without_an_older_release(
    checkout: Checkout, lookup_fault: str, diagnostic: str,
) -> None:
    """defect:#2128 cell D8a -- the second lookup fails like the first and blocks the fallback."""

    checkout.move_main_forward()
    checkout.move_main_forward()
    before = checkout.head
    newest = checkout.remote_main_sha()
    if lookup_fault == "fail":
        checkout.make_workflow_lookup_fail(newest)
    else:
        checkout.check_run_lookup_timeout_seconds = 3
        checkout.make_workflow_lookup_terminate(kill=lookup_fault == "kill", commit_sha=newest)

    result = checkout.tick()

    assert result.returncode == 0
    assert diagnostic in checkout.journal
    assert "cannot determine GitHub check status" in checkout.journal
    assert checkout.head == before
    assert _deployed_sha(checkout) == before


def _api_check_run(app_slug: str, conclusion: str, check_suite: str) -> str:
    return (
        f'{{"app":{{"slug":"{app_slug}"}},"name":"job","status":"completed",'
        f'"conclusion":"{conclusion}"{check_suite}}}'
    )


@pytest.mark.parametrize(
    ("suite_field", "deploys"),
    [
        pytest.param("", False, id="actions-run-without-suite"),
        pytest.param(',"check_suite":null', False, id="actions-run-with-null-suite"),
        pytest.param(',"check_suite":{"id":"x"}', False, id="actions-run-with-text-suite"),
        pytest.param(',"check_suite":{"id":1000}', True, id="actions-run-with-suite"),
    ],
)
def test_a_github_actions_run_whose_suite_cannot_be_read_is_never_passed_over(
    checkout: Checkout, suite_field: str, deploys: bool,
) -> None:
    """defect:#2128 cell D8e -- unknown still blocks; a readable suite is judged as before."""

    checkout.move_main_forward()
    candidate = checkout.remote_main_sha()
    run = _api_check_run("github-actions", "success", suite_field)
    checkout.set_check_runs_response(f'{{"total_count":1,"check_runs":[{run}]}}')

    result = checkout.tick()

    assert result.returncode == 0
    assert (_deployed_sha(checkout) == candidate) == deploys
    assert ("cannot determine GitHub check status" in checkout.journal) == (not deploys)


@pytest.mark.parametrize("suite_field", ["", ',"check_suite":null'])
def test_a_failed_other_app_run_without_a_suite_stays_advisory(
    checkout: Checkout, suite_field: str,
) -> None:
    """defect:#2128 cell D9 -- an other-app run is judged as today whatever its suite."""

    checkout.move_main_forward()
    candidate = checkout.remote_main_sha()
    runs = [
        _api_check_run("github-actions", "success", ',"check_suite":{"id":1000}'),
        _api_check_run("sonarqubecloud", "failure", suite_field),
    ]
    checkout.set_check_runs_response(f'{{"total_count":2,"check_runs":[{",".join(runs)}]}}')

    result = checkout.tick()

    assert result.returncode == 0
    assert _deployed_sha(checkout) == candidate


def test_the_update_run_lookup_runs_after_the_check_run_lookup(checkout: Checkout) -> None:
    """defect:#2128 -- an update run that appears once the check runs are read stays unjudged."""

    checkout.move_main_forward()
    candidate = checkout.remote_main_sha()
    checkout.set_check_runs(PASSED_CI, UPDATE_RUN)
    answer = json.dumps({
        "total_count": 1,
        "workflow_runs": [
            {
                "check_suite_id": int(UPDATE_CHECK_SUITE_ID),
                "path": DEPENDABOT_UPDATES_WORKFLOW_PATH,
            },
        ],
    })
    answer_file = checkout.workflow_runs_directory / "default"
    checkout.run_after_check_lookup(
        f"printf %s {shlex.quote(answer)} > {shlex.quote(str(answer_file))}\n",
    )

    result = checkout.tick()

    assert result.returncode == 0
    assert _deployed_sha(checkout) == candidate

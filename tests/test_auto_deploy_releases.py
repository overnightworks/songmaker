"""Which commit scripts/auto-deploy.sh puts live: only a release tag, never a main tip.

The script is driven as a real subprocess against a throwaway checkout and its
own origin (see ``auto_deploy_harness``). A landing on main deploys nothing;
a tag ``vYYYY.MM.DD.N`` on a green main commit does, checked out detached.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from auto_deploy_harness import (
    Checkout,
)
from auto_deploy_support import (
    FAILURE_ALERT_THRESHOLD,
    git,
    git_output,
)

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


def test_untagged_commits_after_a_release_do_not_deploy(checkout: Checkout) -> None:
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
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.move_main_forward()
    before = checkout.head

    result = checkout.tick()

    assert result.returncode == 0
    assert _deployed_sha(checkout) == before
    assert checkout.build_and_recreate_calls == []


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


def test_a_release_whose_tag_names_another_schema_than_the_running_one_is_backed_up(
    checkout: Checkout,
) -> None:
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


def test_a_release_with_the_running_schema_is_not_backed_up(checkout: Checkout) -> None:
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

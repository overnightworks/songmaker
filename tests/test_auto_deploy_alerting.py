"""When an auto-deploy tick alerts, driven as a real subprocess.

The unit's ``OnFailure=songmaker-alert@%n.service`` turns a non-zero exit
of scripts/auto-deploy.sh into an email (issue #333), so "which ticks exit
non-zero" is this script's alerting contract and is pinned here against
the real script: a copy of it runs against a throwaway git checkout with
its own origin, with ``logger``, ``docker`` and ``date`` replaced by fakes
on PATH. No real deploy, no syslog, no network — and no waiting: the fake
``date`` is the script's only clock, so an hourly repeat is proven by
moving that clock, never by sleeping.
"""

from __future__ import annotations

import fcntl
import json
import shlex
import subprocess
import time
from pathlib import Path

import pytest
from auto_deploy_harness import (
    Checkout,
)
from auto_deploy_support import (
    ACESTEP_SUBMODULE_PATH,
    ALERT_REPEAT_SECONDS,
    CHECK_RUN_APPEARANCE_GRACE_SECONDS,
    CHECK_RUN_FIELD_SEPARATOR,
    FAILURE_ALERT_THRESHOLD,
    GIT_FETCH_TIMEOUT_SECONDS,
    GRAFANA_PASSWORD_REFUSAL,
    HUNG_FETCH_TIMEOUT_SECONDS,
    HUNG_TICK_CEILING_SECONDS,
    PRUNE_TIMEOUT_SECONDS,
    REQUIRED_ACTIONS_JOB_NAME,
    REQUIRED_GRAFANA_PASSWORD,
    SONAR_ACTIONS_JOB_NAME,
    VALID_ALERT_ENV,
    AcestepFork,
    ComposeConfigRefusal,
    FailingTransport,
    git,
    git_output,
    has_commit,
    prometheus_rules_response,
    stops_running,
    write_executable,
)


@pytest.fixture
def stuck_checkout(tmp_path: Path) -> Checkout:
    """A checkout whose every tick refuses to deploy: HEAD is on a work branch."""
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    checkout.switch_to_work_branch()
    return checkout


def test_a_streak_fails_the_unit_only_on_the_tick_that_crosses_the_threshold(
    stuck_checkout: Checkout,
) -> None:
    exit_codes = [stuck_checkout.tick().returncode for _ in range(4)]

    assert exit_codes == [0, 0, 1, 0]
    assert len(stuck_checkout.alert_lines()) == 1


# A tick is not a fixed two minutes: a systemd timer starts no second run
# while the previous one is still going, and one tick may wait out the
# whole compose-up timeout. Both speeds below therefore have to reach the
# operator on the same wall-clock cadence — the fast one without paging
# more often, the slow one without going quiet for hours.
@pytest.mark.parametrize("seconds_per_tick", [60, ALERT_REPEAT_SECONDS])
def test_an_outage_nobody_fixes_is_paged_again_after_the_repeat_time(
    stuck_checkout: Checkout, seconds_per_tick: int,
) -> None:
    for _ in range(FAILURE_ALERT_THRESHOLD):
        stuck_checkout.tick()
    assert len(stuck_checkout.alert_lines()) == 1

    elapsed = 0
    while elapsed < ALERT_REPEAT_SECONDS:
        stuck_checkout.advance_clock(seconds_per_tick)
        elapsed += seconds_per_tick
        result = stuck_checkout.tick()

    assert result.returncode == 1
    assert len(stuck_checkout.alert_lines()) == 2


def test_a_recovered_tick_resets_the_streak(stuck_checkout: Checkout) -> None:
    """And with it the repeat window — no clock is moved below.

    A new outage minutes after a recovered one must page on its own
    crossing tick instead of waiting out the previous episode's hour.
    """
    for _ in range(FAILURE_ALERT_THRESHOLD):
        stuck_checkout.tick()

    stuck_checkout.detach_at(stuck_checkout.head)
    recovered = stuck_checkout.tick()
    assert recovered.returncode == 0

    stuck_checkout.switch_to_work_branch()
    stuck_checkout.move_main_forward()
    assert [stuck_checkout.tick().returncode for _ in range(3)] == [0, 0, 1]


def test_a_missing_alert_configuration_refuses_to_deploy_and_names_the_key(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    checkout.write_alert_config(
        VALID_ALERT_ENV.replace("SMTP_PASSWORD='correct-horse-battery-staple'\n", ""),
    )

    result = checkout.tick()

    assert result.returncode == 0
    assert "SMTP_PASSWORD" in checkout.journal
    assert "alert channel not configured" in checkout.journal


def test_a_failing_mount_preflight_alerts_without_pulling_or_building(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.commit_mount_preflight(
        "#!/bin/bash\nprintf '%s\\n' 'Claude CLI mount source is not a regular file'\nexit 1\n",
    )
    local_head_before = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip()
    checkout.move_main_forward()

    exit_codes = [checkout.tick().returncode for _ in range(FAILURE_ALERT_THRESHOLD)]

    assert exit_codes == [0, 0, 1]
    assert len(checkout.alert_lines()) == 1
    assert "reason: agent CLI mount preflight failed" in checkout.journal
    assert "agent CLI mount preflight failed" in checkout.journal
    assert "Claude CLI mount source is not a regular file" in checkout.journal
    assert subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip() == local_head_before
    assert "compose build" not in checkout.docker_calls


def test_a_missing_mount_preflight_is_logged_and_the_deploy_continues(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()

    result = checkout.tick()

    assert result.returncode == 0
    assert "mount preflight not installed, skipping" in checkout.journal
    assert "compose build" in checkout.docker_calls


@pytest.mark.parametrize(
    "compose_error",
    [
        pytest.param(GRAFANA_PASSWORD_REFUSAL, id="missing-variable"),
        pytest.param("yaml: line 2: did not find expected ',' or ']'", id="invalid-yaml"),
    ],
)
def test_an_invalid_compose_configuration_refuses_before_the_job_guard_and_the_pull(
    tmp_path: Path, compose_error: str,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    head_before = checkout.head
    checkout.move_main_forward()
    checkout.refuse_compose_config(ComposeConfigRefusal(stderr=compose_error))

    exit_codes = [checkout.tick().returncode for _ in range(FAILURE_ALERT_THRESHOLD)]

    assert exit_codes == [0, 0, 1]
    assert "reason: compose configuration refused before checkout" in checkout.journal
    assert compose_error in checkout.journal
    assert checkout.head == head_before
    assert set(checkout.docker_calls.splitlines()) == {"compose config --quiet"}


@pytest.mark.parametrize("pin_moves", [False, True], ids=["pin unchanged", "pin moves"])
def test_a_commit_needing_a_missing_variable_is_refused_after_the_fast_forward_before_any_build(
    acestep_checkout: Checkout, acestep_fork: AcestepFork, pin_moves: bool,
) -> None:
    """defect:#1479 -- a variable the selected commit newly requires refuses the tick after
    the fast-forward and before any build; a pin change in that commit is already checked
    out by then, so the refusal strands no submodule, and the tick after the variable is
    supplied deploys."""
    checkout = acestep_checkout
    deployed_before = checkout.deployed_sha_file.read_text()
    checkout.set_base_images_present(False)
    checkout.refuse_compose_config(
        ComposeConfigRefusal(
            stderr=GRAFANA_PASSWORD_REFUSAL,
            when_compose_file_contains=REQUIRED_GRAFANA_PASSWORD,
        ),
    )
    checkout.move_main_forward_with_compose_file(
        "services:\n"
        "  grafana:\n"
        "    environment:\n"
        f"      GF_SECURITY_ADMIN_PASSWORD: {REQUIRED_GRAFANA_PASSWORD}\n",
    )
    expected_pin = checkout.acestep_head
    if pin_moves:
        expected_pin = acestep_fork.commit()
        acestep_fork.push()
        checkout.move_main_forward_with_acestep_pin(expected_pin)

    fast_forward_tick = checkout.tick()

    assert fast_forward_tick.returncode == 0
    assert checkout.head == checkout.remote_main_sha()
    assert "refuses the stack configuration after checking out" in checkout.journal
    assert GRAFANA_PASSWORD_REFUSAL in checkout.journal
    assert checkout.build_and_recreate_calls == []
    assert checkout.deployed_sha_file.read_text() == deployed_before
    assert checkout.acestep_head == expected_pin
    assert checkout.uncommitted_changes == ""

    checkout.tick()

    assert "refuses the stack configuration before checkout" in checkout.journal

    checkout.satisfy_compose_config()
    repaired_tick = checkout.tick()

    assert repaired_tick.returncode == 0
    assert checkout.deployed_sha_file.read_text() == checkout.head
    assert checkout.acestep_head == expected_pin


def test_green_checks_allow_the_fetched_commit_to_fast_forward_and_deploy(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()

    result = checkout.tick()

    assert result.returncode == 0
    assert subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip() == subprocess.check_output(
        ["git", "rev-parse", "origin/main"], cwd=checkout.root, text=True,
    ).strip()
    assert "compose build" in checkout.docker_calls
    assert [
        call for call in checkout.docker_calls.splitlines() if " prune " in call
    ] == [
        "image prune --force --filter until=48h --filter label!=songmaker.base-image=true",
        "builder prune --all --force --filter until=48h",
    ]
    assert "pruned unreferenced Docker images and build cache older than 48h" in checkout.journal


def test_a_missing_base_image_is_built_before_compose(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    checkout.set_base_images_present(False)

    result = checkout.tick()

    assert result.returncode == 0
    docker_calls = checkout.docker_calls.splitlines()
    base_builds = [call for call in docker_calls if call.startswith("build -f docker/base/")]
    assert base_builds == [
        "build -f docker/base/gpu-torch-base.Dockerfile --label "
        "songmaker.base-image=true -t songmaker/gpu-torch-base:latest .",
        "build -f docker/base/acestep-base.Dockerfile --label "
        "songmaker.base-image=true -t songmaker/acestep-base:latest .",
    ]
    assert docker_calls.index(base_builds[-1]) < docker_calls.index("compose build")
    assert "base image songmaker/gpu-torch-base:latest is missing" in checkout.journal


def test_a_changed_base_image_is_built_before_compose(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward_with_changed_base_image()

    result = checkout.tick()

    assert result.returncode == 0
    docker_calls = checkout.docker_calls.splitlines()
    base_builds = [call for call in docker_calls if call.startswith("build -f docker/base/")]
    assert len(base_builds) == 2
    assert docker_calls.index(base_builds[-1]) < docker_calls.index("compose build")


def test_an_unchanged_base_image_is_not_built(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()

    result = checkout.tick()

    assert result.returncode == 0
    assert "compose build" in checkout.docker_calls
    assert "build -f docker/base/" not in checkout.docker_calls


@pytest.fixture
def acestep_fork(tmp_path: Path) -> AcestepFork:
    return AcestepFork(tmp_path)


@pytest.fixture
def acestep_checkout(tmp_path: Path, acestep_fork: AcestepFork) -> Checkout:
    """A deployed checkout whose vendor/acestep is pinned to the fork's first commit."""
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.add_acestep_submodule(acestep_fork)
    checkout.adopt_current_head_as_deployed()
    return checkout


def _base_builds(checkout: Checkout) -> list[str]:
    return [
        call for call in checkout.docker_calls.splitlines()
        if call.startswith("build -f docker/base/")
    ]


@pytest.mark.parametrize(
    "submodule_ignore_setting",
    [
        pytest.param(None, id="no ignore setting"),
        pytest.param("diff.ignoreSubmodules", id="diff.ignoreSubmodules=all"),
        pytest.param(f"submodule.{ACESTEP_SUBMODULE_PATH}.ignore", id="submodule ignore=all"),
    ],
)
def test_a_changed_acestep_pin_is_checked_out_and_rebuilds_the_bases(
    acestep_checkout: Checkout, acestep_fork: AcestepFork, submodule_ignore_setting: str | None,
) -> None:
    """defect:#1479 cell 1 -- a pin change in the selected commit is fetched, checked
    out and rebuilds both bases before compose build, whatever diff ignores of submodules."""
    if submodule_ignore_setting is not None:
        git(acestep_checkout.root, "config", submodule_ignore_setting, "all")
    new_pin = acestep_fork.commit()
    acestep_fork.push()
    acestep_checkout.move_main_forward_with_acestep_pin(new_pin)
    submodule = acestep_checkout.root / ACESTEP_SUBMODULE_PATH
    assert not has_commit(submodule, new_pin)

    result = acestep_checkout.tick()

    assert result.returncode == 0
    assert acestep_checkout.acestep_head == new_pin
    assert acestep_checkout.head == acestep_checkout.remote_main_sha()
    assert acestep_checkout.deployed_sha_file.read_text() == acestep_checkout.head
    assert acestep_checkout.uncommitted_changes == ""
    docker_calls = acestep_checkout.docker_calls.splitlines()
    base_builds = _base_builds(acestep_checkout)
    assert len(base_builds) == 2
    assert docker_calls.index(base_builds[-1]) < docker_calls.index("compose build")


def test_an_unfetchable_pin_refuses_the_tick_until_it_can_be_fetched(
    acestep_checkout: Checkout, acestep_fork: AcestepFork,
) -> None:
    """defect:#1479 cells 3, 4 -- a pin the fork does not serve refuses three ticks in a
    row with one ALERT and moves nothing; once served, the next tick deploys."""
    head_before = acestep_checkout.head
    pin_before = acestep_checkout.acestep_head
    deployed_before = acestep_checkout.deployed_sha_file.read_text()
    withheld_pin = acestep_fork.commit()
    acestep_checkout.move_main_forward_with_acestep_pin(withheld_pin)

    exit_codes = [acestep_checkout.tick().returncode for _ in range(FAILURE_ALERT_THRESHOLD)]

    assert exit_codes == [0, 0, 1]
    [alert] = acestep_checkout.alert_lines()
    assert withheld_pin in alert
    assert acestep_checkout.build_and_recreate_calls == []
    assert acestep_checkout.deployed_sha_file.read_text() == deployed_before
    assert acestep_checkout.head == head_before
    assert acestep_checkout.acestep_head == pin_before

    acestep_fork.push()
    result = acestep_checkout.tick()

    assert result.returncode == 0
    assert acestep_checkout.acestep_head == withheld_pin
    assert acestep_checkout.head == acestep_checkout.remote_main_sha()
    assert acestep_checkout.deployed_sha_file.read_text() == acestep_checkout.head


def test_an_uninitialised_submodule_refuses_the_tick(
    tmp_path: Path, acestep_fork: AcestepFork,
) -> None:
    """defect:#1479 cell 5 -- an uninitialised vendor/acestep is refused by name, and
    nothing is fetched into the superproject under the submodule's name."""
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.add_acestep_submodule(acestep_fork, initialised=False)
    checkout.adopt_current_head_as_deployed()
    head_before = checkout.head
    deployed_before = checkout.deployed_sha_file.read_text()
    new_pin = acestep_fork.commit()
    acestep_fork.push()
    checkout.move_main_forward_with_acestep_pin(new_pin)
    # Were the pin looked up in the superproject under the submodule's name,
    # this decoy would let that lookup succeed and fetch the commit into it.
    git(acestep_fork.work, "push", str(checkout.origin), f"{new_pin}:refs/heads/decoy")

    result = checkout.tick()

    assert result.returncode == 0
    assert "is not initialised" in checkout.journal
    assert not (checkout.root / ACESTEP_SUBMODULE_PATH / ".git").exists()
    assert checkout.head == head_before
    assert checkout.deployed_sha_file.read_text() == deployed_before
    assert checkout.build_and_recreate_calls == []
    assert not has_commit(checkout.root, new_pin)


@pytest.mark.parametrize(
    ("transport", "journal_wording"),
    [
        pytest.param(FailingTransport.HANGS, "timed out", id="hangs"),
        pytest.param(FailingTransport.HANGS_IGNORING_TERM, "timed out", id="hangs ignoring TERM"),
        pytest.param(FailingTransport.KILLS_ITS_GIT, "was killed by SIGKILL", id="kills its git"),
    ],
)
@pytest.mark.parametrize("failing_fetch", ["superproject", "acestep pin"])
def test_a_fetch_that_cannot_finish_is_a_counted_refusal_that_leaves_no_process_behind(
    acestep_checkout: Checkout,
    acestep_fork: AcestepFork,
    failing_fetch: str,
    transport: FailingTransport,
    journal_wording: str,
) -> None:
    """A4; defect:#1479 cell 10 -- a fetch that hangs, whose transport ignores TERM, or whose
    git is SIGKILLed is cut off within the deadline with everything it started, counts as
    a refusal worded as what happened, and the next healthy tick recovers."""
    new_pin = acestep_fork.commit()
    acestep_fork.push()
    acestep_checkout.move_main_forward_with_acestep_pin(new_pin)
    head_before = acestep_checkout.head
    pin_before = acestep_checkout.acestep_head
    deployed_before = acestep_checkout.deployed_sha_file.read_text()
    if failing_fetch == "superproject":
        failing_repository = acestep_checkout.root
        failing_description = f"git fetch origin main in {acestep_checkout.root}"
    else:
        failing_repository = acestep_checkout.root / ACESTEP_SUBMODULE_PATH
        failing_description = f"fetching the {ACESTEP_SUBMODULE_PATH} pin {new_pin}"
    acestep_checkout.make_fetches_fail(failing_repository, transport)
    acestep_checkout.git_fetch_timeout_seconds = HUNG_FETCH_TIMEOUT_SECONDS

    started = time.monotonic()
    result = acestep_checkout.tick()
    elapsed = time.monotonic() - started

    assert result.returncode == 0
    assert elapsed < HUNG_TICK_CEILING_SECONDS
    assert stops_running(acestep_checkout.failing_transport_pid)
    assert f"{failing_description} {journal_wording}" in acestep_checkout.journal
    assert acestep_checkout.failure_count_file.read_text() == "1"
    assert acestep_checkout.build_and_recreate_calls == []
    assert acestep_checkout.deployed_sha_file.read_text() == deployed_before
    assert acestep_checkout.head == head_before
    assert acestep_checkout.acestep_head == pin_before
    assert not list((acestep_checkout.root / ".git").glob("songmaker-autodeploy.git-fetch.*"))

    acestep_checkout.make_fetches_work_again(failing_repository)
    acestep_checkout.git_fetch_timeout_seconds = GIT_FETCH_TIMEOUT_SECONDS
    recovered = acestep_checkout.tick()

    assert recovered.returncode == 0
    assert acestep_checkout.acestep_head == new_pin
    assert acestep_checkout.deployed_sha_file.read_text() == acestep_checkout.head
    assert not list((acestep_checkout.root / ".git").glob("songmaker-autodeploy.git-fetch.*"))


def test_an_unchanged_acestep_pin_does_not_rebuild_the_bases(
    acestep_checkout: Checkout, acestep_fork: AcestepFork,
) -> None:
    """defect:#1479 cell 2 -- main moving with the pin unchanged builds no base and
    never asks the fork."""
    acestep_fork.make_unreachable()
    acestep_checkout.move_main_forward()

    result = acestep_checkout.tick()

    assert result.returncode == 0
    assert acestep_checkout.deployed_sha_file.read_text() == acestep_checkout.remote_main_sha()
    assert "compose build" in acestep_checkout.docker_calls
    assert _base_builds(acestep_checkout) == []


def test_a_red_newest_commit_with_a_bad_pin_does_not_block_the_green_predecessor(
    acestep_checkout: Checkout, acestep_fork: AcestepFork,
) -> None:
    """defect:#1479 cell 7 -- the step-2 fetch does not recurse into submodules, so a
    bad pin in a red newest commit cannot keep the green predecessor from deploying."""
    acestep_checkout.move_main_forward()
    green_predecessor = acestep_checkout.remote_main_sha()
    acestep_checkout.move_main_forward_with_acestep_pin(acestep_fork.commit())
    red_head = acestep_checkout.remote_main_sha()
    acestep_checkout.set_check_runs_for_commit(red_head, ("completed", "failure"))
    acestep_checkout.set_check_runs_for_commit(green_predecessor, ("completed", "success"))

    result = acestep_checkout.tick()

    assert result.returncode == 0
    assert acestep_checkout.head == green_predecessor
    assert acestep_checkout.deployed_sha_file.read_text() == green_predecessor


def test_recreate_preserves_each_running_service_image_with_a_previous_tag(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()

    result = checkout.tick()

    assert result.returncode == 0
    docker_calls = checkout.docker_calls.splitlines()
    previous_tag = "tag sha256:previous-songmaker-web songmaker-songmaker-web:previous"
    recreate = "compose up -d --wait --wait-timeout 1200"
    assert previous_tag in docker_calls
    assert "tag sha256:previous-songmaker-web songmaker-postgres:previous" not in docker_calls
    assert "compose config --format json --no-interpolate" in docker_calls
    assert recreate in docker_calls
    assert docker_calls.index(previous_tag) < docker_calls.index(recreate)


def test_an_idle_tick_without_jq_stays_successful(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    failure_count_before = checkout.failure_count_file.read_text()
    checkout.remove_jq_from_path()

    result = checkout.tick()

    assert result.returncode == 0
    assert checkout.failure_count_file.read_text() == failure_count_before
    assert not checkout.alert_lines()


def test_a_pending_deploy_without_jq_is_a_counted_refusal(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    deployed_sha_before = checkout.deployed_sha_file.read_text()
    checkout.move_main_forward()
    checkout.remove_jq_from_path()

    result = checkout.tick()

    assert result.returncode == 0
    assert "jq is required" in checkout.journal
    assert checkout.failure_count_file.read_text() == "1"
    assert "compose up" not in checkout.docker_calls
    assert checkout.deployed_sha_file.read_text() == deployed_sha_before


def test_recreate_uses_the_compose_project_name_for_rollback_tags(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.set_compose_project_name("issue-384-prune")
    checkout.move_main_forward()

    result = checkout.tick()

    assert result.returncode == 0
    assert (
        "tag sha256:previous-songmaker-web "
        "issue-384-prune-songmaker-web:previous"
    ) in checkout.docker_calls


def test_compose_warning_on_stderr_does_not_prevent_the_recreate(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.compose_stderr = "variable is not set. Defaulting to a blank string"
    checkout.move_main_forward()

    result = checkout.tick()

    assert result.returncode == 0
    assert "compose up -d --wait" in checkout.docker_calls
    assert "cannot preserve running images before recreate" not in checkout.journal


def test_origin_advance_after_check_lookup_cannot_change_the_deployed_commit(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    checked_commit = checkout.remote_main_sha()
    checkout.move_main_forward_after_check_lookup()

    result = checkout.tick()

    assert result.returncode == 0
    assert subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip() == checked_commit
    assert subprocess.check_output(
        ["git", "rev-parse", "origin/main"], cwd=checkout.root, text=True,
    ).strip() == checked_commit
    assert checkout.remote_main_sha() != checked_commit
    assert "compose build" in checkout.docker_calls


# GitHub's CodeQL default setup reports this job as skipped on every main commit.
UNJUDGED_ACTIONS_JOB_NAME = "Adjust Configuration"
UNSUCCESSFUL_CHECKS_VERDICT = "failed (one or more GitHub Actions check runs did not succeed)"
NOTHING_VERIFIED_VERDICT = "failed (no required GitHub Actions check run succeeded)"
RUNNING_CHECKS_VERDICT = "waiting (one or more GitHub Actions check runs are still running)"


@pytest.mark.parametrize(
    "job_name", [UNJUDGED_ACTIONS_JOB_NAME, SONAR_ACTIONS_JOB_NAME],
    ids=["codeql", "old-sonar"],
)
@pytest.mark.parametrize("conclusion", ["skipped", "neutral"])
def test_a_skipped_or_neutral_actions_job_does_not_block_a_green_candidate(
    tmp_path: Path,
    conclusion: str,
    job_name: str,
) -> None:
    """A2: unjudged Actions jobs neither block nor prove success."""
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    expected_head = checkout.remote_main_sha()
    checkout.set_check_runs(
        ("completed", "success"),
        ("github-actions", job_name, "completed", conclusion),
    )

    result = checkout.tick()

    assert result.returncode == 0
    assert checkout.deployed_sha_file.read_text() == expected_head
    assert "compose build" in checkout.docker_calls


@pytest.mark.parametrize(
    ("runs", "verdict"),
    [
        *(
            pytest.param(
                [("completed", "success"), ("completed", conclusion)],
                UNSUCCESSFUL_CHECKS_VERDICT,
                id=conclusion,
            )
            for conclusion in ("failure", "cancelled", "timed_out")
        ),
        *(
            pytest.param(
                [("completed", "success"), ("github-actions", name, "completed", "failure")],
                UNSUCCESSFUL_CHECKS_VERDICT,
                id=case,
            )
            for case, name in (
                ("old-sonar", SONAR_ACTIONS_JOB_NAME),
                ("quality-sonar", "quality / sonar"),
                ("quality-verdict", "quality / verdict"),
            )
        ),
        pytest.param([("completed", "skipped")], NOTHING_VERIFIED_VERDICT, id="skipped-only"),
        pytest.param(
            [("completed", "skipped"), ("completed", "neutral")],
            NOTHING_VERIFIED_VERDICT,
            id="skipped-and-neutral-only",
        ),
        pytest.param([("in_progress", "")], RUNNING_CHECKS_VERDICT, id="running"),
        pytest.param(
            [
                ("github-actions", UNJUDGED_ACTIONS_JOB_NAME, "completed", "skipped"),
                ("in_progress", ""),
            ],
            RUNNING_CHECKS_VERDICT,
            id="skipped-while-another-job-runs",
        ),
    ],
)
def test_a_candidate_is_passed_over_unless_its_actions_checks_prove_it_green(
    tmp_path: Path,
    runs: list[tuple[str, ...]],
    verdict: str,
) -> None:
    """A1: every failed Actions job rejects the candidate, regardless of name."""
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    local_head_before = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip()
    checkout.set_check_runs(*runs)

    result = checkout.tick()

    assert result.returncode == 0
    assert (
        f"deploy candidate {checkout.remote_main_sha()} is not green: {verdict}" in checkout.journal
    )
    assert "no fully green release" in checkout.journal
    assert "failure count now" not in checkout.journal
    assert subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip() == local_head_before
    assert "compose build" not in checkout.docker_calls
    assert "image prune" not in checkout.docker_calls
    assert "builder prune" not in checkout.docker_calls


@pytest.mark.parametrize(
    ("app_slug", "name", "advisory_log"),
    [
        ("sonarcloud", "SonarCloud Code Analysis", "app 'sonarcloud' is advisory, ignored"),
    ],
)
@pytest.mark.parametrize(
    "through_github_api_filter", [False, True], ids=["projected", "raw-api-response"],
)
def test_a_failed_other_app_check_does_not_block_a_green_github_actions_candidate(
    tmp_path: Path,
    app_slug: str,
    name: str,
    advisory_log: str,
    through_github_api_filter: bool,
) -> None:
    """A2: an external app failure is ignored for projected and raw API answers."""
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    expected_head = checkout.remote_main_sha()
    if through_github_api_filter:
        checkout.set_check_runs_raw_response(json.dumps({
            "total_count": 2,
            "check_runs": [
                {
                    "app": {"slug": "github-actions"},
                    "name": REQUIRED_ACTIONS_JOB_NAME,
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "app": {"slug": app_slug},
                    "name": name,
                    "status": "completed",
                    "conclusion": "failure",
                },
            ],
        }))
    else:
        checkout.set_check_runs(
            ("github-actions", "completed", "success"),
            (app_slug, name, "completed", "failure"),
        )

    result = checkout.tick()

    assert result.returncode == 0
    assert checkout.deployed_sha_file.read_text() == expected_head
    assert "compose build" in checkout.docker_calls
    assert advisory_log in checkout.journal


def test_a_missing_check_run_app_slug_refuses_to_deploy(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    local_head_before = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip()
    checkout.set_check_runs_response(
        f"envelope{CHECK_RUN_FIELD_SEPARATOR}1\n"
        + CHECK_RUN_FIELD_SEPARATOR.join(
            ("check", "", REQUIRED_ACTIONS_JOB_NAME, "completed", "failure"),
        )
        + "\n",
    )

    result = checkout.tick()

    assert result.returncode == 0
    assert "cannot determine GitHub check status" in checkout.journal
    assert "incomplete check-run status" in checkout.journal
    assert subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip() == local_head_before
    assert "compose build" not in checkout.docker_calls


@pytest.mark.parametrize(
    "check_run_record",
    [
        pytest.param(
            r'{"app":{"slug":"github-actions"},"name":"Backend",'
            r'"status":"completed","conclusion":"suc\u0000cess"}',
            id="nul-in-conclusion",
        ),
        pytest.param(
            r'{"app":{"slug":"github-actions"},"status":"completed","conclusion":"success"}',
            id="missing-job-name",
        ),
    ],
)
def test_a_malformed_check_run_record_refuses_to_deploy(
    tmp_path: Path,
    check_run_record: str,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    local_head_before = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip()
    checkout.set_check_runs_raw_response(
        f'{{"total_count":1,"check_runs":[{check_run_record}]}}',
    )

    result = checkout.tick()

    assert result.returncode == 0
    assert "cannot determine GitHub check status" in checkout.journal
    assert "GitHub returned malformed check-run record" in checkout.journal
    assert subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip() == local_head_before
    assert "compose build" not in checkout.docker_calls


def test_running_head_deploys_the_newest_green_predecessor(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    green_predecessor = checkout.remote_main_sha()
    checkout.move_main_forward()
    running_head = checkout.remote_main_sha()
    checkout.set_check_runs_for_commit(running_head, ("in_progress", ""))
    checkout.set_check_runs_for_commit(green_predecessor, ("completed", "success"))

    result = checkout.tick()

    assert result.returncode == 0
    assert subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip() == green_predecessor
    assert checkout.deployed_sha_file.read_text() == green_predecessor
    assert f"deploy candidate {running_head} is not green: waiting" in checkout.journal
    selected = f"selected newest fully green release v2026.10.25.1 ({green_predecessor})"
    assert selected in checkout.journal


@pytest.mark.parametrize(
    "job_name",
    [SONAR_ACTIONS_JOB_NAME, "quality / sonar", "quality / verdict"],
    ids=["old-sonar", "quality-sonar", "quality-verdict"],
)
def test_failed_head_deploys_the_newest_green_predecessor(
    tmp_path: Path, job_name: str,
) -> None:
    """A1: a red Actions candidate leaves its newest green predecessor eligible."""
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    green_predecessor = checkout.remote_main_sha()
    checkout.move_main_forward()
    failed_head = checkout.remote_main_sha()
    checkout.set_check_runs_for_commit(
        failed_head, ("github-actions", job_name, "completed", "failure"),
    )
    checkout.set_check_runs_for_commit(green_predecessor, ("completed", "success"))

    result = checkout.tick()

    assert result.returncode == 0
    assert subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip() == green_predecessor
    assert checkout.deployed_sha_file.read_text() == green_predecessor
    assert "compose build" in checkout.docker_calls
    assert f"deploy candidate {failed_head} is not green: failed" in checkout.journal
    selected = f"selected newest fully green release v2026.10.25.1 ({green_predecessor})"
    assert selected in checkout.journal


def test_lookback_limit_does_not_deploy_a_green_commit_outside_the_window(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    local_head_before = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip()
    checkout.move_main_forward()
    green_predecessor = checkout.remote_main_sha()
    checkout.move_main_forward()
    failed_head = checkout.remote_main_sha()
    checkout.check_run_lookback_commits = 1
    checkout.set_check_runs_for_commit(failed_head, ("completed", "failure"))
    checkout.set_check_runs_for_commit(green_predecessor, ("completed", "success"))

    result = checkout.tick()

    assert result.returncode == 0
    assert subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip() == local_head_before
    assert "no fully green release among the newest 1;" in checkout.journal
    assert "compose build" not in checkout.docker_calls


def test_a_failed_container_recreate_does_not_prune(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    checkout.set_compose_up_exit_code(1)

    result = checkout.tick()

    assert result.returncode == 0
    assert "compose up -d --wait" in checkout.docker_calls
    assert "image prune" not in checkout.docker_calls
    assert "builder prune" not in checkout.docker_calls


def test_a_prune_failure_resets_the_counters_like_any_successful_deploy(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    checkout.set_prune_exit_code(1)
    checkout.failure_count_file.write_text("2")

    result = checkout.tick()

    assert result.returncode == 0
    assert (
        "docker image prune --force --filter until=48h failed after deploy (exit 1)"
        in checkout.journal
    )
    assert (
        "docker builder prune --all --force --filter until=48h failed after deploy (exit 1)"
        in checkout.journal
    )
    assert "deploy remains successful" in checkout.journal
    assert checkout.failure_count_file.read_text() == "0"
    assert checkout.deployed_sha_file.read_text() == checkout.remote_main_sha()


def test_a_prune_timeout_resets_the_counters_like_any_successful_deploy(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    checkout.set_prune_sleep_seconds(PRUNE_TIMEOUT_SECONDS + 1)
    checkout.failure_count_file.write_text("2")

    result = checkout.tick()

    assert result.returncode == 0
    assert (
        "docker image prune --force --filter until=48h failed after deploy (exit 124)"
        in checkout.journal
    )
    assert (
        "docker builder prune --all --force --filter until=48h failed after deploy (exit 124)"
        in checkout.journal
    )
    assert "failure count now" not in checkout.journal
    assert checkout.failure_count_file.read_text() == "0"
    assert "deploy succeeded, now running" in checkout.journal


@pytest.mark.parametrize("change", ["alert_rules", "prometheus_config"])
def test_a_changed_prometheus_file_reloads_and_verifies_prometheus_rules(
    tmp_path: Path, change: str,
) -> None:
    """#418: a changed Prometheus file reloads and verifies the rules."""
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    getattr(checkout, f"move_main_forward_with_changed_{change}")()

    result = checkout.tick()

    assert result.returncode == 0
    assert checkout.curl_calls.splitlines() == [
        "--fail --silent --show-error --max-time 30 --retry 5 --retry-connrefused --retry-delay 2 http://127.0.0.1:9090/-/ready",
        "--fail --silent --show-error --max-time 30 http://127.0.0.1:9090/metrics",
        "--fail --silent --show-error --max-time 30 http://127.0.0.1:9090/api/v1/rules",
    ]
    assert "compose ps -q prometheus" in checkout.docker_calls
    assert "kill -s HUP 0123456789ab" in checkout.docker_calls
    assert "deploy remains successful" not in checkout.journal


def test_an_alert_rule_count_mismatch_is_logged_after_a_successful_deploy(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    configured = checkout.configured_alerting_rules
    loaded = configured - 1
    checkout.set_prometheus_rules_response(prometheus_rules_response(loaded))
    checkout.move_main_forward_with_changed_alert_rules()

    result = checkout.tick()

    assert result.returncode == 0
    assert (
        f"Prometheus alert rule count mismatch after reload: configured {configured}, "
        f"loaded {loaded}; deploy remains successful"
    ) in checkout.journal
    assert checkout.failure_count_file.read_text() == "0"


def test_prometheus_compose_warnings_do_not_contaminate_its_container_id(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.compose_stderr = "WARN: compose emitted a warning"
    checkout.move_main_forward_with_changed_alert_rules()

    result = checkout.tick()

    assert result.returncode == 0
    assert "kill -s HUP 0123456789ab" in checkout.docker_calls
    assert "WARN: compose emitted a warning" not in checkout.journal
    assert "Prometheus container ID" not in checkout.journal


def test_an_empty_previous_deployed_sha_reloads_changed_prometheus_rules(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.install_backup_command(exit_code=0)
    checkout.deployed_sha_file.write_text("")
    checkout.move_main_forward_with_changed_alert_rules()

    result = checkout.tick()

    assert result.returncode == 0
    assert "kill -s HUP 0123456789ab" in checkout.docker_calls


def test_an_unchanged_alert_rule_file_does_not_reload_prometheus(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()

    result = checkout.tick()

    assert result.returncode == 0
    assert checkout.curl_calls == ""


def test_unavailable_check_status_refuses_to_pull_with_a_named_failure(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    local_head_before = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip()
    checkout.make_check_lookup_fail()

    result = checkout.tick()

    assert result.returncode == 0
    assert "cannot determine GitHub check status" in checkout.journal
    assert "GitHub API unavailable" in checkout.journal
    assert "failure count now 1" in checkout.journal
    assert subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip() == local_head_before
    assert "compose build" not in checkout.docker_calls


def test_no_check_runs_yet_waits_without_incrementing_the_failure_streak(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    checkout.set_check_runs()

    result = checkout.tick()

    assert result.returncode == 0
    assert "GitHub Actions has not reported a check run yet" in checkout.journal
    assert "failure count now" not in checkout.journal
    assert "compose build" not in checkout.docker_calls


def test_future_commit_timestamp_cannot_starve_first_seen_grace_alarm(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    checkout.set_check_runs()
    # The repository's commit timestamp is deliberately still in the future
    # when the first-seen grace period expires. It must not starve the alarm.
    checkout.set_clock(
        checkout.remote_main_commit_timestamp() - CHECK_RUN_APPEARANCE_GRACE_SECONDS - 1,
    )

    first_tick = checkout.tick()

    assert first_tick.returncode == 0
    assert "GitHub Actions has not reported a check run yet" in checkout.journal

    checkout.advance_clock(CHECK_RUN_APPEARANCE_GRACE_SECONDS)
    result = checkout.tick()

    assert result.returncode == 0
    assert "has not reported a check run within 1800s of its commit" in checkout.journal
    assert "no fully green release" in checkout.journal
    assert "failure count now" not in checkout.journal
    assert "compose build" not in checkout.docker_calls


@pytest.mark.parametrize(
    ("kill", "diagnostic"),
    [
        pytest.param(False, "check-run lookup timed out", id="term"),
        pytest.param(True, "check-run lookup was killed by SIGKILL", id="kill"),
    ],
)
def test_a_check_run_lookup_timeout_counts_as_a_failed_tick(
    tmp_path: Path, kill: bool, diagnostic: str,
) -> None:
    """A3: both lookup terminations keep their diagnostic and count one refusal."""
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    if not kill:
        checkout.check_run_lookup_timeout_seconds = 3
    checkout.make_check_lookup_terminate(kill=kill)

    result = checkout.tick()

    assert result.returncode == 0
    assert diagnostic in checkout.journal
    assert "failure count now 1 (this tick: GitHub check status undetermined)" in checkout.journal
    assert "compose build" not in checkout.docker_calls


def test_gh_stderr_does_not_be_parsed_as_a_check_run(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    checkout.check_runs_stderr = "gh progress notice"

    result = checkout.tick()

    assert result.returncode == 0
    assert "compose build" in checkout.docker_calls


def test_malformed_check_status_refuses_to_pull_with_a_named_failure(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    checkout.set_check_runs_response(
        CHECK_RUN_FIELD_SEPARATOR.join(
            ("check", "github-actions", REQUIRED_ACTIONS_JOB_NAME, "completed", "success"),
        )
        + "\n",
    )

    result = checkout.tick()

    assert result.returncode == 0
    assert "cannot determine GitHub check status" in checkout.journal
    assert "incomplete check-runs response" in checkout.journal
    assert "failure count now 1" in checkout.journal
    assert "compose build" not in checkout.docker_calls


def test_post_merge_hook_is_not_run_by_the_deploy_fast_forward(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    hook = checkout.root / ".git" / "hooks" / "post-merge"
    write_executable(
        hook,
        "#!/bin/bash\n"
        f"printf 'ran' > {shlex.quote(str(checkout.post_merge_marker))}\n",
    )
    checkout.move_main_forward()
    expected_head = checkout.remote_main_sha()

    result = checkout.tick()

    assert result.returncode == 0
    assert not checkout.post_merge_marker.exists()
    assert subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip() == expected_head


@pytest.mark.parametrize(
    ("setter", "value", "diagnostic", "absent_journal", "absent_docker", "absent_curl"),
    [
        ('set_prometheus_reload_exit_code', 1,
         'Prometheus rule reload failed after deploy; deploy remains successful',
         ('Prometheus alert rule count mismatch',), (), ()),
        ('set_prometheus_container', '',
         'cannot find the Prometheus container to reload rules after deploy; '
         'deploy remains successful',
         (), ('kill -s HUP',), ()),
        ('set_prometheus_container', 'prometheus-container',
         "Prometheus container ID 'prometheus-container' contains unsupported characters "
         "after deploy; deploy remains successful",
         (), ('kill -s HUP',), ()),
        ('set_prometheus_metrics_response', 'prometheus_config_last_reload_successful 0\n',
         'Prometheus reload did not apply; deploy remains successful',
         ('failure count now',), (), ('http://127.0.0.1:9090/api/v1/rules',)),
        ('set_prometheus_metrics_exit_code', 1,
         'cannot read Prometheus reload status after deploy; deploy remains successful',
         ('Prometheus alert rule count mismatch',), (), ('http://127.0.0.1:9090/api/v1/rules',)),
        ('set_prometheus_metrics_response', 'other_metric 1\n',
         'cannot determine Prometheus reload status after deploy; deploy remains successful',
         ('Prometheus reload did not apply',), (), ('http://127.0.0.1:9090/api/v1/rules',)),
        ('set_prometheus_ready_exit_code', 1,
         'Prometheus did not become ready after rule reload; deploy remains successful',
         ('Prometheus alert rule count mismatch',), (), ()),
        ('set_prometheus_rules_exit_code', 1,
         'cannot read Prometheus rules after reload; deploy remains successful',
         ('Prometheus alert rule count mismatch',), (), ()),
        ('set_prometheus_rules_response', 'not JSON',
         'cannot read Prometheus rules after reload; deploy remains successful',
         ('Prometheus alert rule count mismatch',), (), ()),
    ],
)
def test_prometheus_refusal_keeps_a_successful_deploy_successful(
    tmp_path: Path, setter: str, value: str | int, diagnostic: str,
    absent_journal: tuple[str, ...], absent_docker: tuple[str, ...], absent_curl: tuple[str, ...],
) -> None:
    """#418: a Prometheus refusal keeps a successful deploy successful."""
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    getattr(checkout, setter)(value)
    checkout.move_main_forward_with_changed_alert_rules()

    assert checkout.tick().returncode == 0
    assert f"-t songmaker-autodeploy -p user.err -- {diagnostic}" in checkout.journal.splitlines()
    assert checkout.failure_count_file.read_text() == "0"
    assert checkout.deployed_sha_file.read_text() == checkout.head
    assert all(text not in checkout.journal for text in absent_journal)
    assert all(text not in checkout.docker_calls for text in absent_docker)
    assert all(text not in checkout.curl_calls for text in absent_curl)


@pytest.mark.parametrize(
    "prefix", ["git-fetch", "compose-stderr", "prometheus-ps-stderr", "gh-stderr"],
)
@pytest.mark.parametrize("kind", ["file", "symlink", "dangling-symlink"])
def test_stale_temp_sweep_removes_only_owned_entries_before_fetch(
    tmp_path: Path, prefix: str, kind: str,
) -> None:
    """S1–S4: exact names, direct children only, targets and all state retained."""
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    admin = checkout.root / ".git"
    preserved = [admin / f"songmaker-autodeploy.{name}" for name in (
        "lock", "failcount", "busycount", "deployed-sha", "first-seen-commit",
        "failure-escalated-at", "busy-escalated-at", "guard-reason",
    )]
    preserved += [
        admin / "foreign.Abc123",
        admin / "songmaker-autodeploy.other.Abc123",
        admin / "worktrees/other/songmaker-autodeploy.git-fetch.Abc123",
    ]
    preserved += [admin / f"songmaker-autodeploy.{prefix}.{suffix}"
                  for suffix in ("Abc12", "Abc1234", "Abc_12", "Äbc123")]
    for path in preserved:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
    target = tmp_path / "target"
    if kind != "dangling-symlink":
        target.write_text("keep me")
        preserved.append(target)
    stale = admin / f"songmaker-autodeploy.{prefix}.Az09bZ"
    if kind == "file":
        stale.write_text("interrupted")
    else:
        stale.symlink_to(target)
    observed = checkout.observe_sweep_at_fetch(stale, preserved)

    assert checkout.tick().returncode == 0
    assert observed.exists()
    assert not stale.exists()
    assert not stale.is_symlink()
    assert f"-p user.info -- removed stale temp file: {stale}" in checkout.journal
    if kind == "dangling-symlink":
        assert not target.exists()
    else:
        assert target.read_text() == "keep me"


@pytest.mark.parametrize("advance_origin", [False, True], ids=["up-to-date", "new-commit"])
@pytest.mark.parametrize("kind", ["failed-rm", "directory"])
def test_unremovable_stale_temp_refuses_before_fetch_and_alerts_on_third_tick(
    tmp_path: Path, advance_origin: bool, kind: str,
) -> None:
    """S5–S6: no fetch, one counted refusal per tick, third-tick escalation."""
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    before = git_output(checkout.root, "rev-parse", "origin/main")
    if advance_origin:
        checkout.move_main_forward()
    stale = checkout.root / ".git/songmaker-autodeploy.git-fetch.Abc123"
    if kind == "directory":
        stale.mkdir()
    else:
        stale.touch()
        checkout.refuse_removal(stale)
    for count, status in enumerate((0, 0, 1), start=1):
        assert checkout.tick().returncode == status
        assert checkout.failure_count_file.read_text() == str(count)
        assert git_output(checkout.root, "rev-parse", "origin/main") == before
    assert stale.exists()
    assert f"-p user.err -- stale temp file could not be removed: {stale}" in checkout.journal
    assert ("ALERT: 3 ticks in a row deferred/failed, "
            "reason: stale temp file could not be removed") in checkout.journal


def test_stale_temp_sweep_waits_for_the_deploy_lock(tmp_path: Path) -> None:
    """S7: the losing tick cannot remove the active tick's temp files."""
    checkout = Checkout(tmp_path)
    stale = checkout.root / ".git/songmaker-autodeploy.git-fetch.Abc123"
    stale.touch()
    with (checkout.root / ".git/songmaker-autodeploy.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert checkout.tick().returncode == 0
        assert stale.exists()
    assert "another run is already in flight" in checkout.journal

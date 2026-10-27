"""The deploy-checkout switch and its backout, driven through recording fakes."""

from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "switch_deploy_checkout.sh"
TAG = "v2026.10.27.1"
TAG_COMMIT = "0123456789abcdef0123456789abcdef01234567"
SECRET = "SONGMAKER_SECRET_KEY=do-not-print-me"

# One generic fake serves every external command: it records the call, answers
# the few questions the script asks, and fails when the call contains FAIL_ON.
FAKE = r"""#!/bin/bash
printf '%s %s\n' "$(basename "$0")" "$*" >> "$RECORDING"
case "$(basename "$0")" in
    sudo)
        printf 'sudo-cwd %s\n' "$PWD" >> "$RECORDING" ;;
    systemctl)
        case "${1:-}" in
            is-active)
                echo "${FAKE_SERVICE_STATE:-inactive}"
                [ "${FAKE_SERVICE_STATE:-inactive}" = active ] ;;
            cat) cat "$HOME/unit-lines" ;;
        esac ;;
    git)
        case "$*" in
            *"rev-parse HEAD"*) echo "$FAKE_TAG_COMMIT" ;;
            clone*) mkdir -p "${@: -1}/.git" "${@: -1}/vendor/acestep" ;;
        esac ;;
    docker)
        case "$*" in
            "compose config"*) printf '{"name": "%s"}\n' "${FAKE_PROJECT_NAME:-songmaker}" ;;
            "compose ls"*)
                printf '[{"Name": "songmaker", "ConfigFiles": "%s"}]\n' "$FAKE_CONFIG_FILES" ;;
        esac ;;
    journalctl) echo "$FAKE_JOURNAL" ;;
    sleep)
        [ -z "${FAKE_TAMPER:-}" ] || echo changed > "$HOME/git/songmaker/.env" ;;
    stat)
        [ -z "${FAKE_DEVICES:-}" ] || { echo "$FAKE_DEVICES"; exit 0; }
        exec /usr/bin/stat "$@" ;;
esac
status=0
if [ -n "${FAIL_ON:-}" ] && [[ "$(basename "$0") $*" == *"$FAIL_ON"* ]]; then
    status=1
fi
exit "$status"
"""
FAKED_COMMANDS = (
    "sudo",
    "systemctl",
    "git",
    "docker",
    "flock",
    "journalctl",
    "sleep",
    "stat",
)


@dataclass(frozen=True)
class Outcome:
    result: subprocess.CompletedProcess[str]
    recording: list[str]
    home: Path

    @property
    def work_env(self) -> Path:
        return self.home / "git" / "songmaker" / ".env"


@pytest.fixture
def run_switch(tmp_path: Path):
    home = tmp_path / "home"
    work = home / "git" / "songmaker"
    (work / ".git").mkdir(parents=True)
    (work / "vendor" / "acestep" / "checkpoints").mkdir(parents=True)
    (work / "vendor" / "acestep" / "checkpoints" / "model.bin").write_text("w")
    (work / ".env").write_text(SECRET + "\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in FAKED_COMMANDS:
        fake = fake_bin / name
        fake.write_text(FAKE)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    recording = tmp_path / "recording"
    recording.write_text("")

    def _run(
        *arguments: str,
        stdin: str = "",
        unit_directory: str | None = None,
        **environment: str,
    ) -> Outcome:
        release = home / "srv" / "songmaker"
        directory = unit_directory or (
            str(release) if arguments and arguments[0] != "--backout" else str(work)
        )
        (home / "unit-lines").write_text(
            f"WorkingDirectory={directory}\nExecStart={directory}/scripts/x.sh\n"
        )
        result = subprocess.run(
            [str(SCRIPT), *arguments],
            input=stdin,
            env={
                "HOME": str(home),
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "RECORDING": str(recording),
                "FAKE_TAG_COMMIT": TAG_COMMIT,
                "FAKE_JOURNAL": f"adopted running state {TAG_COMMIT} (first run)",
                "FAKE_CONFIG_FILES": f"{work}/docker-compose.yml",
                **environment,
            },
            text=True,
            capture_output=True,
            check=False,
        )
        return Outcome(result, recording.read_text().splitlines(), home)

    _run.home = home
    return _run


def _calls(outcome: Outcome) -> list[str]:
    return [line for line in outcome.recording if not line.startswith("sudo-cwd")]


def _assert_never_touches_stack_or_secret(outcome: Outcome) -> None:
    for call in _calls(outcome):
        assert not call.startswith(
            ("docker compose up", "docker compose down", "docker compose restart")
        )
        assert "start songmaker.service" not in call
    printed = outcome.result.stdout + outcome.result.stderr
    assert "do-not-print-me" not in printed


def test_switch_runs_steps_1_to_16_in_order_and_keeps_the_old_env_unconfirmed(run_switch) -> None:
    outcome = run_switch(TAG, stdin="")

    assert outcome.result.returncode == 0, outcome.result.stderr
    steps = [
        line.split(":")[0]
        for line in outcome.result.stdout.splitlines()
        if line.startswith("step ")
    ]
    assert steps == [f"step {number}" for number in range(1, 17)]
    assert "sudo is used only for" in outcome.result.stdout.splitlines()[0]
    assert outcome.work_env.exists()
    assert "stays" in outcome.result.stdout
    _assert_never_touches_stack_or_secret(outcome)


def test_switch_runs_the_installers_from_the_release_clone_through_sudo(run_switch) -> None:
    outcome = run_switch(TAG)

    release = str(outcome.home / "srv" / "songmaker")
    assert "sudo ./scripts/install-cli-credentials-mirror.sh --force" in outcome.recording
    assert "sudo ./scripts/install-autostart.sh --force" in outcome.recording
    assert "sudo ./scripts/install-autodeploy.sh" in outcome.recording
    assert f"sudo-cwd {release}" in outcome.recording
    assert f"git -C {release} checkout --detach {TAG}" in outcome.recording
    assert (
        (outcome.home / "srv" / "songmaker" / ".env").read_text().startswith("SONGMAKER_SECRET_KEY")
    )


def test_switch_deletes_the_old_env_only_after_a_typed_yes(run_switch) -> None:
    outcome = run_switch(TAG, stdin="yes\n")

    assert outcome.result.returncode == 0, outcome.result.stderr
    assert not outcome.work_env.exists()


def test_switch_keeps_the_old_env_after_any_other_answer(run_switch) -> None:
    outcome = run_switch(TAG, stdin="y\n")

    assert outcome.result.returncode == 0
    assert outcome.work_env.exists()


def test_switch_keeps_the_old_env_when_the_copies_differ(run_switch) -> None:
    outcome = run_switch(TAG, stdin="yes\n", FAKE_TAMPER="1")

    assert outcome.result.returncode == 1
    assert "stopped at step 16" in outcome.result.stderr
    assert outcome.work_env.exists()
    _assert_never_touches_stack_or_secret(outcome)


@pytest.mark.parametrize(
    ("label", "environment", "reason"),
    [
        ("step 1", {"FAIL_ON": "systemctl stop"}, "the timer did not stop"),
        ("step 2", {"FAIL_ON": "flock"}, "deploy lock"),
        ("step 2", {"FAKE_SERVICE_STATE": "active"}, "is active"),
        ("step 4", {"FAKE_DEVICES": "1\n2"}, "another file system"),
    ],
)
def test_switch_stops_before_any_change_and_restarts_the_timer(
    run_switch, label: str, environment: dict[str, str], reason: str
) -> None:
    outcome = run_switch(TAG, **environment)

    assert outcome.result.returncode != 0
    assert f"stopped at {label}" in outcome.result.stderr
    assert reason in outcome.result.stderr
    assert "nothing changed" in outcome.result.stderr
    assert "sudo systemctl start songmaker-autodeploy.timer" in outcome.recording
    assert "step 5" not in outcome.result.stdout
    assert not (outcome.home / "srv" / "songmaker").exists()
    _assert_never_touches_stack_or_secret(outcome)


@pytest.mark.parametrize(
    ("label", "environment", "reason", "later_step"),
    [
        ("step 5", {"FAIL_ON": "git clone"}, "clone failed", "step 6"),
        ("step 6", {"FAIL_ON": "checkout --detach"}, "could not be checked out", "step 7"),
        ("step 7", {"FAIL_ON": "submodule"}, "submodule", "step 8"),
        ("step 10", {"FAKE_PROJECT_NAME": "srv"}, "not songmaker", "step 11"),
        ("step 10", {"FAIL_ON": "compose config"}, "docker compose config failed", "step 11"),
        ("step 11", {"FAIL_ON": "install-cli-credentials-mirror"}, "install-cli", "step 12"),
        ("step 12", {"FAIL_ON": "install-autostart"}, "install-autostart", "step 13"),
        ("step 13", {"FAIL_ON": "install-autodeploy"}, "install-autodeploy", "step 14"),
        ("step 14", {"unit_directory": "/home/someone/git/songmaker"}, "does not name", "step 15"),
        ("step 15", {"FAKE_JOURNAL": "nothing adopted"}, "adopted running state", "step 16"),
    ],
)
def test_switch_stops_at_the_first_failed_check_and_names_the_backout(
    run_switch, label: str, environment: dict[str, str], reason: str, later_step: str
) -> None:
    outcome = run_switch(TAG, stdin="yes\n", **environment)

    assert outcome.result.returncode != 0
    assert f"stopped at {label}" in outcome.result.stderr
    assert reason in outcome.result.stderr
    assert "--backout" in outcome.result.stderr
    assert f"{later_step}:" not in outcome.result.stdout
    assert outcome.work_env.exists()
    _assert_never_touches_stack_or_secret(outcome)


@pytest.mark.parametrize(
    ("label", "missing", "later_step"),
    [
        ("step 8", ".env", "step 9"),
        ("step 9", "vendor/acestep/checkpoints", "step 10"),
    ],
)
def test_switch_stops_when_a_file_to_carry_over_is_missing(
    run_switch, label: str, missing: str, later_step: str
) -> None:
    target = run_switch.home / "git" / "songmaker" / missing
    if target.is_dir():
        for child in target.iterdir():
            child.unlink()
        target.rmdir()
    else:
        target.unlink()

    outcome = run_switch(TAG)

    assert outcome.result.returncode != 0
    assert f"stopped at {label}" in outcome.result.stderr
    assert "--backout" in outcome.result.stderr
    assert f"{later_step}:" not in outcome.result.stdout


def test_switch_refuses_something_that_is_not_a_release_tag(run_switch) -> None:
    outcome = run_switch("main")

    assert outcome.result.returncode == 2
    assert _calls(outcome) == []


def test_backout_runs_b1_to_b8_and_removes_the_release_clone(run_switch) -> None:
    switched = run_switch(TAG)
    assert switched.result.returncode == 0

    outcome = run_switch("--backout")

    assert outcome.result.returncode == 0, outcome.result.stderr
    labels = [
        line.split(":")[0]
        for line in outcome.result.stdout.splitlines()
        if line.startswith("backout ")
    ]
    assert labels == [
        "backout B1",
        "backout B2",
        "backout B3",
        "backout B4",
        "backout B5",
        "backout B6",
        "backout B7",
        "backout B7b",
        "backout B8",
    ]
    assert not (outcome.home / "srv" / "songmaker").exists()
    assert any(
        line.startswith("sudo-cwd") and line.endswith("git/songmaker") for line in outcome.recording
    )
    _assert_never_touches_stack_or_secret(outcome)


@pytest.mark.parametrize(
    ("config_files", "reason"),
    [
        ("{release}/docker-compose.yml", "already deployed"),
        ("", "compose file is ''"),
    ],
)
def test_backout_refuses_and_keeps_the_clone_unless_the_stack_runs_from_the_work_clone(
    run_switch, config_files: str, reason: str
) -> None:
    release = run_switch.home / "srv" / "songmaker"
    run_switch(TAG)

    outcome = run_switch("--backout", FAKE_CONFIG_FILES=config_files.format(release=release))

    assert outcome.result.returncode != 0
    assert "stopped at backout B7b" in outcome.result.stderr
    assert reason in outcome.result.stderr
    assert "backout B8" not in outcome.result.stdout
    assert release.exists()


@pytest.mark.parametrize(
    ("label", "fail_on"),
    [
        ("backout B1", "systemctl stop"),
        ("backout B2", "flock"),
        ("backout B6", "install-autodeploy"),
    ],
)
def test_backout_stops_at_the_first_failed_step_and_removes_nothing(
    run_switch, label: str, fail_on: str
) -> None:
    release = run_switch.home / "srv" / "songmaker"
    run_switch(TAG)

    outcome = run_switch("--backout", FAIL_ON=fail_on)

    assert outcome.result.returncode != 0
    assert f"stopped at {label}" in outcome.result.stderr
    assert "backout B8" not in outcome.result.stdout
    assert release.exists()


def test_backout_stops_when_the_old_env_is_gone(run_switch) -> None:
    switched = run_switch(TAG, stdin="yes\n")
    assert not switched.work_env.exists()

    outcome = run_switch("--backout")

    assert outcome.result.returncode != 0
    assert "stopped at backout B3" in outcome.result.stderr
    assert "backout B4" not in outcome.result.stdout
    assert (outcome.home / "srv" / "songmaker").exists()

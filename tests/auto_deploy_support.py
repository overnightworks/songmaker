"""Constants, fake-response builders and git helpers for the auto-deploy script tests."""

from __future__ import annotations

import stat
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "auto-deploy.sh"
ALERT_CONFIG_LIB = REPO_ROOT / "scripts" / "alert-config.sh"
PROMETHEUS_RULE_PATH = Path("monitoring/rules/alert.rules.yml")

FAILURE_ALERT_THRESHOLD = 3
# Shorter than the 1h default only to keep the number of ticks a test has
# to drive small; what is under test is that the repeat follows this
# duration rather than a tick count.
ALERT_REPEAT_SECONDS = 600
# Match the production defaults while allowing the timeout test to use a
# short, deterministic deadline.
CHECK_RUN_LOOKUP_TIMEOUT_SECONDS = 60
CHECK_RUN_APPEARANCE_GRACE_SECONDS = 30 * 60
PRUNE_TIMEOUT_SECONDS = 1
ACESTEP_SUBMODULE_PATH = "vendor/acestep"
GIT_FETCH_TIMEOUT_SECONDS = 30
GIT_FETCH_KILL_GRACE_SECONDS = 1
HUNG_FETCH_TIMEOUT_SECONDS = 3
# Long enough that a fetch which is not killed is unmistakable, and shorter
# than the tick's own ceiling so the failure is an assertion, not a timeout.
HUNG_TRANSPORT_SECONDS = 40
HUNG_TICK_CEILING_SECONDS = 20
PROMETHEUS_RULES_RESPONSE = """\
{"status":"success","data":{"groups":[{"file":"/etc/prometheus/rules/alert.rules.yml","rules":[{"type":"alerting"},{"type":"alerting"},{"type":"alerting"},{"type":"alerting"}]}]}}
"""
PROMETHEUS_METRICS_RESPONSE = """\
# HELP prometheus_config_last_reload_successful Whether the last reload succeeded.
# TYPE prometheus_config_last_reload_successful gauge
prometheus_config_last_reload_successful 1
"""
# Any fixed point in time — the script only ever reads differences.
CLOCK_START_EPOCH = 1_756_000_000
CHECK_RUN_FIELD_SEPARATOR = "\x1f"
REQUIRED_ACTIONS_JOB_NAME = "Backend (Python 3.12)"
SONAR_ACTIONS_JOB_NAME = "SonarCloud scan"

REQUIRED_GRAFANA_PASSWORD = (
    "${GRAFANA_PASSWORD:?GRAFANA_PASSWORD must be set in .env (see docker/.env.docker.example)}"
)
GRAFANA_PASSWORD_REFUSAL = (
    "error while interpolating services.grafana.environment.GF_SECURITY_ADMIN_PASSWORD: "
    "required variable GRAFANA_PASSWORD is missing a value: "
    "GRAFANA_PASSWORD must be set in .env (see docker/.env.docker.example)"
)
VALID_ALERT_ENV = """\
ALERT_EMAIL_TO='operator@example.com'
SMTP_HOST='smtp.example.com'
SMTP_PORT='587'
SMTP_USER='songmaker@example.com'
SMTP_PASSWORD='correct-horse-battery-staple'
"""


@dataclass(frozen=True)
class ComposeConfigRefusal:
    """How the fake `docker compose config --quiet` refuses a configuration.

    It exits 1, as compose does for every refusal (a missing variable, invalid
    YAML, no compose file). ``when_compose_file_contains`` limits the refusal
    to checkouts whose docker-compose.yml carries that text, standing in for a
    commit that introduces a newly required variable.
    """

    stderr: str
    when_compose_file_contains: str | None = None


def check_runs_response(*runs: tuple[str, ...]) -> str:
    """Project GitHub check runs as the auto-deploy script's jq query does.

    A run is status/conclusion, app/status/conclusion, or
    app/name/status/conclusion; the omitted app is GitHub Actions and the
    omitted name an ordinary required CI job.
    """
    records = []
    for run in runs:
        if len(run) == 2:
            app_slug, name = "github-actions", REQUIRED_ACTIONS_JOB_NAME
            status, conclusion = run
        elif len(run) == 3:
            name = REQUIRED_ACTIONS_JOB_NAME
            app_slug, status, conclusion = run
        elif len(run) == 4:
            app_slug, name, status, conclusion = run
        else:
            raise ValueError(
                "a check run needs status/conclusion, app/status/conclusion, "
                "or app/name/status/conclusion",
            )
        records.append(
            CHECK_RUN_FIELD_SEPARATOR.join(("check", app_slug, name, status, conclusion)) + "\n",
        )
    return f"envelope{CHECK_RUN_FIELD_SEPARATOR}{len(runs)}\n" + "".join(records)


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def git_output(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def has_commit(repository: Path, commit_sha: str) -> bool:
    return subprocess.run(
        ["git", "cat-file", "-e", f"{commit_sha}^{{commit}}"],
        cwd=repository,
        capture_output=True,
    ).returncode == 0


def stops_running(process_id: int, within_seconds: float = 5.0) -> bool:
    """A killed process takes a moment to die; a zombie awaiting its reaper is dead."""

    def is_running() -> bool:
        try:
            stat_line = Path(f"/proc/{process_id}/stat").read_text()
        except FileNotFoundError:
            return False
        return stat_line.rsplit(")", 1)[1].split()[0] != "Z"

    deadline = time.monotonic() + within_seconds
    while is_running() and time.monotonic() < deadline:
        time.sleep(0.05)
    return not is_running()


def write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class FailingTransport(Enum):
    """What a fetch's transport child does instead of serving objects.

    Each value runs before the transport lingers, so a fetch that is not cut
    short stays at it for HUNG_TRANSPORT_SECONDS.
    """

    HANGS = ""
    HANGS_IGNORING_TERM = "trap '' TERM\n"
    KILLS_ITS_GIT = (
        "git_pid=$PPID\n"
        'while [[ "$(</proc/$git_pid/comm)" != git ]]; do\n'
        "    read -r _ _ _ git_pid _ </proc/$git_pid/stat\n"
        "done\n"
        'kill -KILL "$git_pid"\n'
    )


class AcestepFork:
    """The ACE-Step fork the deploy checkout's submodule points at."""

    def __init__(self, tmp_path: Path) -> None:
        self.origin = tmp_path / "acestep-fork.git"
        self.work = tmp_path / "acestep-work"
        self._commits = 0
        git(tmp_path, "init", "--bare", "--initial-branch=main", str(self.origin))
        git(tmp_path, "clone", str(self.origin), str(self.work))
        git(self.work, "config", "user.email", "test@example.com")
        git(self.work, "config", "user.name", "Test")
        self.commit()
        self.push()

    def commit(self) -> str:
        """Commit locally, so the commit exists on the fork only once pushed."""
        self._commits += 1
        (self.work / "acestep.txt").write_text(f"fork commit {self._commits}\n")
        git(self.work, "add", "acestep.txt")
        git(self.work, "commit", "-m", f"fork commit {self._commits}")
        return git_output(self.work, "rev-parse", "HEAD")

    def push(self) -> None:
        git(self.work, "push", "origin", "main")

    @property
    def head(self) -> str:
        return git_output(self.work, "rev-parse", "HEAD")

    def make_unreachable(self) -> None:
        self.origin.rename(self.origin.with_name("acestep-fork.away"))

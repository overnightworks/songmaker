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

import shlex
import stat
import subprocess
from pathlib import Path

import pytest

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

VALID_ALERT_ENV = """\
ALERT_EMAIL_TO='operator@example.com'
SMTP_HOST='smtp.example.com'
SMTP_PORT='587'
SMTP_USER='songmaker@example.com'
SMTP_PASSWORD='correct-horse-battery-staple'
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class Checkout:
    """A throwaway deploy target the script under test can be run against."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "checkout"
        self.origin = tmp_path / "origin.git"
        self.log_file = tmp_path / "journal.txt"
        self.docker_calls_file = tmp_path / "docker-calls.txt"
        self.curl_calls_file = tmp_path / "curl-calls.txt"
        self.check_runs_file = tmp_path / "check-runs.txt"
        self.post_merge_marker = tmp_path / "post-merge-ran.txt"
        self._after_check_lookup_script: Path | None = None
        self._bin = tmp_path / "bin"
        self._bin.mkdir()
        self._system_bin_without_jq: Path | None = None
        self._jq_path_filter: Path | None = None
        self._clock_file = tmp_path / "clock.txt"
        self._clock_file.write_text(str(CLOCK_START_EPOCH))
        self._commits_pushed = 0
        self._active_job_count = 0
        self._prune_exit_code = 0
        self._prune_sleep_seconds = 0
        self._compose_up_exit_code = 0
        self._compose_project_name = "songmaker"
        self._prometheus_ready_exit_code = 0
        self._prometheus_reload_exit_code = 0
        self._prometheus_rules_exit_code = 0
        self._prometheus_metrics_exit_code = 0
        self._prometheus_rules_response = PROMETHEUS_RULES_RESPONSE
        self._prometheus_metrics_response = PROMETHEUS_METRICS_RESPONSE
        self._prometheus_container = "0123456789ab"
        self.compose_stderr = ""
        self.check_runs_stderr = ""
        self.check_run_lookup_timeout_seconds = CHECK_RUN_LOOKUP_TIMEOUT_SECONDS
        self.check_run_appearance_grace_seconds = CHECK_RUN_APPEARANCE_GRACE_SECONDS

        _git(tmp_path, "init", "--bare", "--initial-branch=main", str(self.origin))
        _git(tmp_path, "clone", str(self.origin), str(self.root))
        _git(self.root, "config", "user.email", "test@example.com")
        _git(self.root, "config", "user.name", "Test")

        (self.root / "scripts").mkdir()
        for source in (DEPLOY_SCRIPT, ALERT_CONFIG_LIB):
            copy = self.root / "scripts" / source.name
            copy.write_text(source.read_text())
            copy.chmod(source.stat().st_mode)
        self.deploy_script = self.root / "scripts" / DEPLOY_SCRIPT.name
        (self.root / "monitoring" / "rules").mkdir(parents=True)
        (self.root / PROMETHEUS_RULE_PATH).write_text(
            (REPO_ROOT / PROMETHEUS_RULE_PATH).read_text(),
        )
        (self.root / "monitoring" / "prometheus.yml").write_text(
            (REPO_ROOT / "monitoring" / "prometheus.yml").read_text(),
        )

        (self.root / "README.md").write_text("initial\n")
        # The deploy guard refuses a dirty tree, and the alert config this
        # script reads lives in an untracked .env — exactly as on the host.
        (self.root / ".gitignore").write_text(".env\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-m", "initial")
        _git(self.root, "push", "origin", "main")

        _write_executable(
            self._bin / "logger",
            '#!/bin/bash\nprintf "%s\\n" "$*" >> "$LOG_CAPTURE_FILE"\n',
        )
        _write_executable(
            self._bin / "date",
            "#!/bin/bash\n"
            'if [[ "$1" == "+%s" ]]; then\n'
            '    cat "$FAKE_CLOCK_FILE"\n'
            "else\n"
            '    exec /usr/bin/date "$@"\n'
            "fi\n",
        )
        self._write_curl_stub()
        self.set_check_runs(("completed", "success"))
        self.set_active_jobs(0)

    def set_active_jobs(self, count: int) -> None:
        """Stand in for `docker compose exec postgres psql …`."""
        self._active_job_count = count
        self._write_docker_stub()

    def set_prune_exit_code(self, exit_code: int) -> None:
        self._prune_exit_code = exit_code
        self._write_docker_stub()

    def set_prune_sleep_seconds(self, seconds: int) -> None:
        self._prune_sleep_seconds = seconds
        self._write_docker_stub()

    def set_compose_up_exit_code(self, exit_code: int) -> None:
        self._compose_up_exit_code = exit_code
        self._write_docker_stub()

    def set_compose_project_name(self, project_name: str) -> None:
        self._compose_project_name = project_name
        self._write_docker_stub()

    def set_prometheus_ready_exit_code(self, exit_code: int) -> None:
        self._prometheus_ready_exit_code = exit_code
        self._write_curl_stub()

    def set_prometheus_reload_exit_code(self, exit_code: int) -> None:
        self._prometheus_reload_exit_code = exit_code
        self._write_docker_stub()

    def set_prometheus_rules_exit_code(self, exit_code: int) -> None:
        self._prometheus_rules_exit_code = exit_code
        self._write_curl_stub()

    def set_prometheus_metrics_exit_code(self, exit_code: int) -> None:
        self._prometheus_metrics_exit_code = exit_code
        self._write_curl_stub()

    def set_prometheus_rules_response(self, response: str) -> None:
        self._prometheus_rules_response = response
        self._write_curl_stub()

    def set_prometheus_metrics_response(self, response: str) -> None:
        self._prometheus_metrics_response = response
        self._write_curl_stub()

    def set_prometheus_container(self, container: str) -> None:
        self._prometheus_container = container
        self._write_docker_stub()

    def _write_curl_stub(self) -> None:
        _write_executable(
            self._bin / "curl",
            "#!/bin/bash\n"
            'printf "%s\\n" "$*" >> "$CURL_CALLS_FILE"\n'
            'if [[ "$*" == "--fail --silent --show-error --max-time 30 --retry 5 '
            '--retry-connrefused --retry-delay 2 http://127.0.0.1:9090/-/ready" ]]; then\n'
            f"    exit {self._prometheus_ready_exit_code}\n"
            "fi\n"
            'if [[ "$*" == "--fail --silent --show-error --max-time 30 '
            'http://127.0.0.1:9090/metrics" ]]; then\n'
            f"    printf '%s' {shlex.quote(self._prometheus_metrics_response)}\n"
            f"    exit {self._prometheus_metrics_exit_code}\n"
            "fi\n"
            'if [[ "$*" == "--fail --silent --show-error --max-time 30 '
            'http://127.0.0.1:9090/api/v1/rules" ]]; then\n'
            f"    printf '%s' {shlex.quote(self._prometheus_rules_response)}\n"
            f"    exit {self._prometheus_rules_exit_code}\n"
            "fi\n"
            'echo "unexpected curl invocation: $*" >&2\n'
            "exit 2\n",
        )

    def _write_docker_stub(self) -> None:
        _write_executable(
            self._bin / "docker",
            "#!/bin/bash\n"
            'printf "%s\\n" "$*" >> "$DOCKER_CALLS_FILE"\n'
            'if [[ "$1" == "compose" && "$2" == "config" && "$3" == "--format" '
            '&& "$4" == "json" ]]; then\n'
            '    if [[ -n "${DOCKER_COMPOSE_STDERR:-}" ]]; then\n'
            '        printf "%s\\n" "$DOCKER_COMPOSE_STDERR" >&2\n'
            "    fi\n"
            '    printf \'{"name":"%s","services":{"songmaker-web":'
            '{"build":{"context":"."}},"postgres":{"image":"postgres:16"}}}\\n\' '
            '"$DOCKER_COMPOSE_PROJECT_NAME"\n'
            "    exit 0\n"
            "fi\n"
            'if [[ "$1" == "compose" && "$2" == "ps" ]]; then\n'
            '    if [[ -n "${DOCKER_COMPOSE_STDERR:-}" ]]; then\n'
            '        printf "%s\\n" "$DOCKER_COMPOSE_STDERR" >&2\n'
            "    fi\n"
            '    if [[ "$3" == "-q" && "$4" == "prometheus" ]]; then\n'
            f"        printf '%s\\n' {shlex.quote(self._prometheus_container)}\n"
            "        exit 0\n"
            "    fi\n"
            '    echo container-songmaker-web\n'
            "    exit 0\n"
            "fi\n"
            'if [[ "$1" == "inspect" ]]; then\n'
            '    echo sha256:previous-songmaker-web\n'
            "    exit 0\n"
            "fi\n"
            'if [[ "$1" == "kill" && "$2" == "-s" && "$3" == "HUP" '
            f'&& "$4" == {shlex.quote(self._prometheus_container)} ]]; then\n'
            f"    exit {self._prometheus_reload_exit_code}\n"
            "fi\n"
            'if [[ "$1" == "image" || "$1" == "builder" ]]; then\n'
            '    sleep "$DOCKER_PRUNE_SLEEP_SECONDS"\n'
            f"    exit {self._prune_exit_code}\n"
            "fi\n"
            'if [[ "$1" == "compose" && "$2" == "up" ]]; then\n'
            f"    exit {self._compose_up_exit_code}\n"
            "fi\n"
            f"echo {self._active_job_count}\n",
        )

    def set_check_runs(self, *runs: tuple[str, str]) -> None:
        """Make GitHub report these status/conclusion pairs for the SHA."""
        self.set_check_runs_response(
            f"envelope\t{len(runs)}\n"
            + "".join(f"check\t{status}\t{conclusion}\n" for status, conclusion in runs),
        )

    def set_check_runs_response(self, response: str) -> None:
        """Make the fake gh process return an already-projected API response."""
        self.check_runs_file.write_text(response)
        _write_executable(
            self._bin / "gh",
            "#!/bin/bash\n"
            'expected_url="repos/FlexOr2/songmaker/commits/${GH_EXPECTED_COMMIT_SHA}/check-runs?per_page=100"\n'
            'if [[ "$1" != "api" || "$2" != "--paginate" ]]; then\n'
            '    echo "unexpected gh api invocation: $*" >&2\n'
            "    exit 2\n"
            "fi\n"
            'if [[ "$3" != "$expected_url" || "$4" != "--jq" ]]; then\n'
            '    echo "unexpected gh api invocation: $*" >&2\n'
            "    exit 2\n"
            "fi\n"
            'if [[ -n "${GH_CHECK_RUNS_STDERR:-}" ]]; then\n'
            '    printf "%s\\n" "$GH_CHECK_RUNS_STDERR" >&2\n'
            "fi\n"
            'cat "$GH_CHECK_RUNS_FILE"\n'
            'if [[ -n "${GH_AFTER_CHECK_LOOKUP_SCRIPT:-}" ]]; then\n'
            '    "$GH_AFTER_CHECK_LOOKUP_SCRIPT"\n'
            "fi\n",
        )

    def make_check_lookup_fail(self) -> None:
        _write_executable(
            self._bin / "gh",
            "#!/bin/bash\n"
            'echo "GitHub API unavailable" >&2\n'
            "exit 1\n",
        )

    def make_check_lookup_hang(self) -> None:
        _write_executable(
            self._bin / "gh",
            "#!/bin/bash\n"
            'exec sleep "$GH_CHECK_RUN_LOOKUP_HANG_SECONDS"\n',
        )

    def write_alert_config(self, content: str = VALID_ALERT_ENV) -> None:
        (self.root / ".env").write_text(content)

    def write_mount_preflight(self, body: str) -> None:
        _write_executable(self.root / "scripts" / "check_agent_cli_mounts.sh", body)

    def commit_mount_preflight(self, body: str) -> None:
        self.write_mount_preflight(body)
        _git(self.root, "add", "scripts/check_agent_cli_mounts.sh")
        _git(self.root, "commit", "-m", "add mount preflight")
        _git(self.root, "push", "origin", "main")

    def move_main_forward(self) -> None:
        clone = self.root.parent / "pusher"
        if not clone.exists():
            _git(self.root.parent, "clone", str(self.origin), str(clone))
            _git(clone, "config", "user.email", "test@example.com")
            _git(clone, "config", "user.name", "Test")
        _git(clone, "pull", "--ff-only", "origin", "main")
        self._commits_pushed += 1
        (clone / "README.md").write_text(f"moved {self._commits_pushed}\n")
        _git(clone, "commit", "-am", f"move main {self._commits_pushed}")
        _git(clone, "push", "origin", "main")

    def move_main_forward_with_changed_alert_rules(self) -> None:
        clone = self.root.parent / "pusher"
        if not clone.exists():
            _git(self.root.parent, "clone", str(self.origin), str(clone))
            _git(clone, "config", "user.email", "test@example.com")
            _git(clone, "config", "user.name", "Test")
        _git(clone, "pull", "--ff-only", "origin", "main")
        rules = clone / PROMETHEUS_RULE_PATH
        rules.write_text(rules.read_text() + "\n# changed by deploy test\n")
        _git(clone, "add", str(PROMETHEUS_RULE_PATH))
        _git(clone, "commit", "-m", "change alert rules")
        _git(clone, "push", "origin", "main")

    def move_main_forward_with_changed_prometheus_config(self) -> None:
        clone = self.root.parent / "pusher"
        if not clone.exists():
            _git(self.root.parent, "clone", str(self.origin), str(clone))
            _git(clone, "config", "user.email", "test@example.com")
            _git(clone, "config", "user.name", "Test")
        _git(clone, "pull", "--ff-only", "origin", "main")
        config = clone / "monitoring" / "prometheus.yml"
        config.write_text(config.read_text() + "\n# changed by deploy test\n")
        _git(clone, "add", "monitoring/prometheus.yml")
        _git(clone, "commit", "-m", "change Prometheus config")
        _git(clone, "push", "origin", "main")

    def move_main_forward_after_check_lookup(self) -> None:
        """Advance origin after the deploy script has checked its current SHA."""
        clone = self.root.parent / "pusher"
        assert clone.exists()
        self._after_check_lookup_script = self._bin / "move-main-after-check-lookup"
        clone_text = shlex.quote(str(clone))
        readme_text = shlex.quote(str(clone / "README.md"))
        _write_executable(
            self._after_check_lookup_script,
            "#!/bin/bash\n"
            "set -euo pipefail\n"
            f"printf 'moved after check lookup\\n' > {readme_text}\n"
            f"/usr/bin/git -C {clone_text} commit -am "
            "'move main after check lookup' >/dev/null 2>&1\n"
            f"/usr/bin/git -C {clone_text} push origin main >/dev/null 2>&1\n",
        )

    def remote_main_sha(self) -> str:
        return subprocess.check_output(
            ["git", "ls-remote", "origin", "refs/heads/main"],
            cwd=self.root,
            text=True,
        ).split()[0]

    def remote_main_commit_timestamp(self) -> int:
        return int(subprocess.check_output(
            ["git", "show", "-s", "--format=%ct", "HEAD"],
            cwd=self.root.parent / "pusher",
            text=True,
        ))

    def switch_to_work_branch(self) -> None:
        _git(self.root, "checkout", "-B", "work")

    def switch_to_main(self) -> None:
        _git(self.root, "checkout", "main")

    def advance_clock(self, seconds: int) -> None:
        """Let time pass for the script without any passing for the test."""
        self._clock_file.write_text(str(int(self._clock_file.read_text()) + seconds))

    def set_clock(self, epoch_seconds: int) -> None:
        self._clock_file.write_text(str(epoch_seconds))

    def adopt_current_head_as_deployed(self) -> None:
        """Skip the first-run adoption tick the script does on a fresh state."""
        self.tick()

    def remove_jq_from_path(self) -> None:
        self._system_bin_without_jq = self.root.parent / "usr-bin-without-jq"
        self._system_bin_without_jq.mkdir()
        for entry in Path("/usr/bin").iterdir():
            if entry.name != "jq":
                (self._system_bin_without_jq / entry.name).symlink_to(entry)
        self._jq_path_filter = self.root.parent / "hide-jq"
        self._jq_path_filter.write_text(
            'command() { [[ "$1" == "-v" && "$2" == "jq" ]] && return 1; builtin command "$@"; }\n',
        )

    def tick(self) -> subprocess.CompletedProcess[str]:
        system_bin = self._system_bin_without_jq or Path("/usr/bin")
        return subprocess.run(
            [str(self.deploy_script)],
            capture_output=True,
            text=True,
            timeout=60,
            env={
                "PATH": f"{self._bin}:{system_bin}:/bin",
                "BASH_ENV": str(self._jq_path_filter) if self._jq_path_filter else "",
                "HOME": str(self.root.parent),
                "LOG_CAPTURE_FILE": str(self.log_file),
                "DOCKER_CALLS_FILE": str(self.docker_calls_file),
                "CURL_CALLS_FILE": str(self.curl_calls_file),
                "GH_CHECK_RUNS_FILE": str(self.check_runs_file),
                "GH_CHECK_RUNS_STDERR": self.check_runs_stderr,
                "GH_EXPECTED_COMMIT_SHA": self.remote_main_sha(),
                "GH_CHECK_RUN_LOOKUP_HANG_SECONDS": "2",
                "GH_AFTER_CHECK_LOOKUP_SCRIPT": (
                    str(self._after_check_lookup_script)
                    if self._after_check_lookup_script is not None
                    else ""
                ),
                "FAKE_CLOCK_FILE": str(self._clock_file),
                "SONGMAKER_AUTODEPLOY_FAILURE_ALERT_THRESHOLD": str(FAILURE_ALERT_THRESHOLD),
                "SONGMAKER_AUTODEPLOY_ALERT_REPEAT_SECONDS": str(ALERT_REPEAT_SECONDS),
                "SONGMAKER_AUTODEPLOY_CHECK_RUN_LOOKUP_TIMEOUT_SECONDS": str(
                    self.check_run_lookup_timeout_seconds,
                ),
                "SONGMAKER_AUTODEPLOY_CHECK_RUN_APPEARANCE_GRACE_SECONDS": str(
                    self.check_run_appearance_grace_seconds,
                ),
                "SONGMAKER_AUTODEPLOY_PRUNE_TIMEOUT_SECONDS": str(PRUNE_TIMEOUT_SECONDS),
                "DOCKER_PRUNE_SLEEP_SECONDS": str(self._prune_sleep_seconds),
                "DOCKER_COMPOSE_PROJECT_NAME": self._compose_project_name,
                "DOCKER_COMPOSE_STDERR": self.compose_stderr,
            },
        )

    @property
    def journal(self) -> str:
        return self.log_file.read_text() if self.log_file.exists() else ""

    @property
    def docker_calls(self) -> str:
        return self.docker_calls_file.read_text() if self.docker_calls_file.exists() else ""

    @property
    def curl_calls(self) -> str:
        return self.curl_calls_file.read_text() if self.curl_calls_file.exists() else ""

    def alert_lines(self) -> list[str]:
        return [line for line in self.journal.splitlines() if "ALERT:" in line]

    @property
    def failure_count_file(self) -> Path:
        return self.root / ".git" / "songmaker-autodeploy.failcount"

    @property
    def deployed_sha_file(self) -> Path:
        return self.root / ".git" / "songmaker-autodeploy.deployed-sha"


@pytest.fixture
def stuck_checkout(tmp_path: Path) -> Checkout:
    """A checkout whose every tick refuses to deploy: HEAD is off main."""
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

    stuck_checkout.switch_to_main()
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
        "image prune --force --filter until=48h",
        "builder prune --all --force --filter until=48h",
    ]
    assert "pruned unreferenced Docker images and build cache older than 48h" in checkout.journal


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


def test_failed_checks_refuse_to_pull_and_increment_the_failure_streak(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    local_head_before = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip()
    checkout.set_check_runs(("completed", "success"), ("completed", "failure"))

    result = checkout.tick()

    assert result.returncode == 0
    assert "GitHub checks for origin/main" in checkout.journal
    assert "failure count now 1" in checkout.journal
    assert subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip() == local_head_before
    assert "compose build" not in checkout.docker_calls
    assert "image prune" not in checkout.docker_calls
    assert "builder prune" not in checkout.docker_calls


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


def test_a_changed_alert_rule_file_reloads_and_verifies_prometheus_rules(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward_with_changed_alert_rules()

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


def test_a_changed_prometheus_config_reloads_and_verifies_prometheus_rules(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward_with_changed_prometheus_config()

    result = checkout.tick()

    assert result.returncode == 0
    assert checkout.curl_calls.splitlines() == [
        "--fail --silent --show-error --max-time 30 --retry 5 --retry-connrefused --retry-delay 2 http://127.0.0.1:9090/-/ready",
        "--fail --silent --show-error --max-time 30 http://127.0.0.1:9090/metrics",
        "--fail --silent --show-error --max-time 30 http://127.0.0.1:9090/api/v1/rules",
    ]
    assert "kill -s HUP 0123456789ab" in checkout.docker_calls


def test_an_alert_rule_count_mismatch_is_logged_after_a_successful_deploy(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.set_prometheus_rules_response(
        '{"status":"success","data":{"groups":[{"file":"/etc/prometheus/rules/alert.rules.yml","rules":['
        '{"type":"alerting"},{"type":"alerting"},{"type":"alerting"}] }]}}',
    )
    checkout.move_main_forward_with_changed_alert_rules()

    result = checkout.tick()

    assert result.returncode == 0
    assert (
        "Prometheus alert rule count mismatch after reload: configured 4, loaded 3; "
        "deploy remains successful"
    ) in checkout.journal
    assert checkout.failure_count_file.read_text() == "0"


def test_a_failed_prometheus_hup_keeps_a_successful_deploy_successful(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.set_prometheus_reload_exit_code(1)
    checkout.move_main_forward_with_changed_alert_rules()

    result = checkout.tick()

    assert result.returncode == 0
    assert (
        "Prometheus rule reload failed after deploy; deploy remains successful"
        in checkout.journal
    )
    assert checkout.failure_count_file.read_text() == "0"
    assert checkout.deployed_sha_file.read_text() == subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip()
    assert "Prometheus alert rule count mismatch" not in checkout.journal


def test_a_missing_prometheus_container_keeps_a_successful_deploy_successful(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.set_prometheus_container("")
    checkout.move_main_forward_with_changed_alert_rules()

    result = checkout.tick()

    assert result.returncode == 0
    missing_container_error = (
        "cannot find the Prometheus container to reload rules after deploy; "
        "deploy remains successful"
    )
    assert missing_container_error in checkout.journal
    assert "kill -s HUP" not in checkout.docker_calls
    assert checkout.failure_count_file.read_text() == "0"


def test_an_invalid_prometheus_container_id_keeps_a_successful_deploy_successful(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.set_prometheus_container("prometheus-container")
    checkout.move_main_forward_with_changed_alert_rules()

    result = checkout.tick()

    assert result.returncode == 0
    assert (
        "Prometheus container ID 'prometheus-container' contains unsupported characters "
        "after deploy; deploy remains successful"
    ) in checkout.journal
    assert "kill -s HUP" not in checkout.docker_calls
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


def test_a_failed_prometheus_config_reload_is_logged_without_failing_the_tick(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.set_prometheus_metrics_response(
        "prometheus_config_last_reload_successful 0\n",
    )
    checkout.move_main_forward_with_changed_alert_rules()

    result = checkout.tick()

    assert result.returncode == 0
    assert (
        "-t songmaker-autodeploy -p user.err -- Prometheus reload did not apply; "
        "deploy remains successful"
    ) in checkout.journal.splitlines()
    assert checkout.failure_count_file.read_text() == "0"
    assert "failure count now" not in checkout.journal
    assert "http://127.0.0.1:9090/api/v1/rules" not in checkout.curl_calls


def test_an_unreadable_prometheus_reload_status_keeps_a_successful_deploy_successful(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.set_prometheus_metrics_exit_code(1)
    checkout.move_main_forward_with_changed_alert_rules()

    result = checkout.tick()

    assert result.returncode == 0
    assert (
        "cannot read Prometheus reload status after deploy; deploy remains successful"
        in checkout.journal
    )
    assert checkout.failure_count_file.read_text() == "0"
    assert checkout.deployed_sha_file.read_text() == subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip()
    assert "http://127.0.0.1:9090/api/v1/rules" not in checkout.curl_calls
    assert "Prometheus alert rule count mismatch" not in checkout.journal


def test_a_missing_prometheus_reload_status_keeps_a_successful_deploy_successful(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.set_prometheus_metrics_response("other_metric 1\n")
    checkout.move_main_forward_with_changed_alert_rules()

    result = checkout.tick()

    assert result.returncode == 0
    assert (
        "cannot determine Prometheus reload status after deploy; deploy remains successful"
        in checkout.journal
    )
    assert "Prometheus reload did not apply" not in checkout.journal
    assert checkout.failure_count_file.read_text() == "0"
    assert "http://127.0.0.1:9090/api/v1/rules" not in checkout.curl_calls


def test_a_prometheus_readiness_failure_keeps_a_successful_deploy_successful(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.set_prometheus_ready_exit_code(1)
    checkout.move_main_forward_with_changed_alert_rules()

    result = checkout.tick()

    assert result.returncode == 0
    assert (
        "Prometheus did not become ready after rule reload; deploy remains successful"
        in checkout.journal
    )
    assert checkout.failure_count_file.read_text() == "0"
    assert "Prometheus alert rule count mismatch" not in checkout.journal


def test_an_unavailable_prometheus_rule_api_keeps_a_successful_deploy_successful(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.set_prometheus_rules_exit_code(1)
    checkout.move_main_forward_with_changed_alert_rules()

    result = checkout.tick()

    assert result.returncode == 0
    assert (
        "cannot read Prometheus rules after reload; deploy remains successful"
        in checkout.journal
    )
    assert checkout.failure_count_file.read_text() == "0"
    assert checkout.deployed_sha_file.read_text() == subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip()
    assert "Prometheus alert rule count mismatch" not in checkout.journal


def test_an_empty_previous_deployed_sha_reloads_changed_prometheus_rules(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.deployed_sha_file.write_text("")
    checkout.move_main_forward_with_changed_alert_rules()

    result = checkout.tick()

    assert result.returncode == 0
    assert "kill -s HUP 0123456789ab" in checkout.docker_calls


def test_an_invalid_prometheus_rule_api_response_keeps_a_successful_deploy_successful(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.set_prometheus_rules_response("not JSON")
    checkout.move_main_forward_with_changed_alert_rules()

    result = checkout.tick()

    assert result.returncode == 0
    assert (
        "cannot read Prometheus rules after reload; deploy remains successful"
        in checkout.journal
    )
    assert checkout.failure_count_file.read_text() == "0"
    assert checkout.deployed_sha_file.read_text() == subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip()
    assert "Prometheus alert rule count mismatch" not in checkout.journal


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


def test_running_checks_wait_without_incrementing_the_failure_streak(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    local_head_before = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip()
    checkout.set_check_runs(("in_progress", ""))

    result = checkout.tick()

    assert result.returncode == 0
    assert "are not green yet: waiting" in checkout.journal
    assert "failure count now" not in checkout.journal
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
    assert "GitHub has not reported a check run yet" in checkout.journal
    assert "failure count now" not in checkout.journal
    assert "compose build" not in checkout.docker_calls


def test_no_check_runs_past_the_commit_grace_period_counts_as_a_failed_tick(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    checkout.set_check_runs()
    checkout.set_clock(
        checkout.remote_main_commit_timestamp() + CHECK_RUN_APPEARANCE_GRACE_SECONDS,
    )

    result = checkout.tick()

    assert result.returncode == 0
    assert "has not reported a check run within 1800s of its commit" in checkout.journal
    failure_reason = (
        "failure count now 1 (this tick: no GitHub check runs reported within 1800s of commit)"
    )
    assert failure_reason in checkout.journal
    assert "compose build" not in checkout.docker_calls


def test_a_check_run_lookup_timeout_counts_as_a_failed_tick(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    checkout.check_run_lookup_timeout_seconds = 1
    checkout.make_check_lookup_hang()

    result = checkout.tick()

    assert result.returncode == 0
    assert "check-run lookup timed out" in checkout.journal
    assert "failure count now 1 (this tick: check-run lookup timed out)" in checkout.journal
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
    checkout.set_check_runs_response("check\tcompleted\tsuccess\n")

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
    _write_executable(
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

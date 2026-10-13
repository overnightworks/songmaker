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

import json
import re
import shlex
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "auto-deploy.sh"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
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
CHECK_RUN_FIELD_SEPARATOR = "\x1f"
REQUIRED_ACTIONS_JOB_NAME = "Backend (Python 3.12)"
ADVISORY_ACTIONS_JOB_NAME = "SonarCloud scan"

# A synthetic stand-in for the real overnightworks read token (#1349) — every
# Checkout gets one by default so the build step the rest of this file drives
# through can succeed; the dedicated token tests below override or remove it.
DEFAULT_OVERNIGHTWORKS_TOKEN = "test-overnightworks-token-value"

VALID_ALERT_ENV = """\
ALERT_EMAIL_TO='operator@example.com'
SMTP_HOST='smtp.example.com'
SMTP_PORT='587'
SMTP_USER='songmaker@example.com'
SMTP_PASSWORD='correct-horse-battery-staple'
"""


def _check_runs_response(*runs: tuple[str, ...]) -> str:
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


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


# Every stub stands in for a real compiled binary (docker, logger, curl,
# date) that would never process an inherited BASH_ENV/SHELLOPTS the way a
# bash script does; clearing any inherited trap/functrace/xtrace state the
# instant a stub starts keeps that stand-in honest under the inherited-tracing
# test below, without changing anything the other tests observe since none of
# them leave a trap or functrace active in the first place (#1349).
_STUB_TRACING_GUARD = (
    "trap - DEBUG RETURN ERR 2>/dev/null\n"
    "set +o functrace +o errtrace 2>/dev/null\n"
    "{ set +x; } 2>/dev/null\n"
)


def _write_executable(path: Path, body: str) -> None:
    shebang, _, rest = body.partition("\n")
    path.write_text(f"{shebang}\n{_STUB_TRACING_GUARD}{rest}")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class Checkout:
    """A throwaway deploy target the script under test can be run against."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "checkout"
        self.origin = tmp_path / "origin.git"
        self.log_file = tmp_path / "journal.txt"
        self.docker_calls_file = tmp_path / "docker-calls.txt"
        self.curl_calls_file = tmp_path / "curl-calls.txt"
        self.token_env_calls_file = tmp_path / "token-env-calls.txt"
        self.overnightworks_token_file = tmp_path / "overnightworks-read-token"
        self.check_runs_file = tmp_path / "check-runs.txt"
        self.check_runs_raw_response_file = tmp_path / "check-runs-response.json"
        self.check_runs_directory = tmp_path / "check-runs"
        self.check_runs_directory.mkdir()
        self.post_merge_marker = tmp_path / "post-merge-ran.txt"
        self._after_check_lookup_script: Path | None = None
        self._bin = tmp_path / "bin"
        self._bin.mkdir()
        self._system_bin_without_jq: Path | None = None
        self._jq_path_filter: Path | None = None
        self._debug_trap_file: Path | None = None
        self._shellopts = ""
        self._xtrace_log_file = tmp_path / "xtrace.log"
        self._clock_file = tmp_path / "clock.txt"
        self._clock_file.write_text(str(CLOCK_START_EPOCH))
        self._commits_pushed = 0
        self._active_job_count = 0
        self._base_images_present = True
        self._prune_exit_code = 0
        self._prune_sleep_seconds = 0
        self._compose_build_exit_code = 0
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
        self.check_run_lookback_commits = 10

        _git(tmp_path, "init", "--bare", "--initial-branch=main", str(self.origin))
        _git(tmp_path, "clone", str(self.origin), str(self.root))
        _git(self.root, "config", "user.email", "test@example.com")
        _git(self.root, "config", "user.name", "Test")

        (self.root / "scripts").mkdir()
        for source in (DEPLOY_SCRIPT, ALERT_CONFIG_LIB, REPO_ROOT / "scripts" / "build_images.sh"):
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
            '#!/bin/bash\nprintf "%s\\n" "$*" >> "$LOG_CAPTURE_FILE"\n'
            'printf "logger=%s\\n" "${OVERNIGHTWORKS_READ_TOKEN:-<unset>}" '
            '>> "$TOKEN_ENV_CALLS_FILE"\n',
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
        self.set_overnightworks_token(DEFAULT_OVERNIGHTWORKS_TOKEN)

    def set_overnightworks_token(self, token: str | None) -> None:
        """Point the script's token-file override at `token`, or remove it.

        `None` stands in for the file being missing entirely (unreadable);
        an empty string for a restored-but-empty file.
        """
        if token is None:
            self.overnightworks_token_file.unlink(missing_ok=True)
        else:
            self.overnightworks_token_file.write_text(token)

    def set_compose_build_exit_code(self, exit_code: int) -> None:
        self._compose_build_exit_code = exit_code
        self._write_docker_stub()

    def set_active_jobs(self, count: int) -> None:
        """Stand in for `docker compose exec postgres psql …`."""
        self._active_job_count = count
        self._write_docker_stub()

    def set_base_images_present(self, present: bool) -> None:
        """Control whether the fake Docker host has both local base images."""
        self._base_images_present = present
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
            'printf "%s %s=%s\\n" "$1" "$2" "${OVERNIGHTWORKS_READ_TOKEN:-<unset>}" '
            '>> "$TOKEN_ENV_CALLS_FILE"\n'
            'if [[ "$1" == "compose" && "$2" == "build" ]]; then\n'
            f"    exit {self._compose_build_exit_code}\n"
            "fi\n"
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
            'if [[ "$1" == "image" && "$2" == "inspect" ]]; then\n'
            '    if [[ "$DOCKER_BASE_IMAGES_PRESENT" == "true" ]]; then\n'
            '        echo sha256:base-image\n'
            "        exit 0\n"
            "    fi\n"
            "    exit 1\n"
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

    def set_check_runs(self, *runs: tuple[str, ...]) -> None:
        """Make GitHub report these app/status/conclusion pairs for the SHA."""
        self.set_check_runs_response(_check_runs_response(*runs))

    def set_check_runs_response(self, response: str) -> None:
        """Make the fake gh process return an already-projected API response."""
        self.check_runs_file.write_text(response)
        _write_executable(
            self._bin / "gh",
            "#!/bin/bash\n"
            'expected_prefix="repos/FlexOr2/songmaker/commits/"\n'
            'expected_suffix="/check-runs?per_page=100"\n'
            'if [[ "$1" != "api" || "$2" != "--paginate" ]]; then\n'
            '    echo "unexpected gh api invocation: $*" >&2\n'
            "    exit 2\n"
            "fi\n"
            'if [[ "$3" != "$expected_prefix"*"$expected_suffix" || "$4" != "--jq" ]]; then\n'
            '    echo "unexpected gh api invocation: $*" >&2\n'
            "    exit 2\n"
            "fi\n"
            'commit_sha="${3#"$expected_prefix"}"\n'
            'commit_sha="${commit_sha%"$expected_suffix"}"\n'
            'if [[ -n "${GH_CHECK_RUNS_STDERR:-}" ]]; then\n'
            '    printf "%s\\n" "$GH_CHECK_RUNS_STDERR" >&2\n'
            "fi\n"
            'if [[ -f "$GH_CHECK_RUNS_RAW_RESPONSE_FILE" ]]; then\n'
            '    jq -r "$5" "$GH_CHECK_RUNS_RAW_RESPONSE_FILE"\n'
            "    exit $?\n"
            "fi\n"
            'response_file="${GH_CHECK_RUNS_DIRECTORY}/${commit_sha}"\n'
            'if [[ -f "$response_file" ]]; then\n'
            '    cat "$response_file"\n'
            "else\n"
            '    cat "$GH_CHECK_RUNS_FILE"\n'
            "fi\n"
            'if [[ -n "${GH_AFTER_CHECK_LOOKUP_SCRIPT:-}" ]]; then\n'
            '    "$GH_AFTER_CHECK_LOOKUP_SCRIPT"\n'
            "fi\n",
        )

    def set_check_runs_for_commit(self, commit_sha: str, *runs: tuple[str, ...]) -> None:
        """Make GitHub report app/status/conclusion pairs for one commit only."""
        (self.check_runs_directory / commit_sha).write_text(_check_runs_response(*runs))

    def set_check_runs_raw_response(self, response: str) -> None:
        """Make the fake gh process apply its jq filter to a raw API response."""
        self.check_runs_raw_response_file.write_text(response)

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

    def move_main_forward_with_changed_base_image(self) -> None:
        clone = self.root.parent / "pusher"
        if not clone.exists():
            _git(self.root.parent, "clone", str(self.origin), str(clone))
            _git(clone, "config", "user.email", "test@example.com")
            _git(clone, "config", "user.name", "Test")
        _git(clone, "pull", "--ff-only", "origin", "main")
        base_dockerfile = clone / "docker" / "base" / "acestep-base.Dockerfile"
        base_dockerfile.parent.mkdir(parents=True)
        base_dockerfile.write_text("# changed by deploy test\n")
        _git(clone, "add", "docker/base/acestep-base.Dockerfile")
        _git(clone, "commit", "-m", "change base image")
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

    def inject_debug_trap(self) -> None:
        """Simulate a DEBUG trap + functrace left behind by an ancestor shell.

        `BASH_ENV` is sourced into the script's own top-level shell before
        anything else runs (the same mechanism `remove_jq_from_path` uses
        above), so this reproduces an inherited `trap 'set -x' DEBUG` honestly
        rather than faking the trap from inside the test (#1349 review). Trace
        output is redirected to its own fd/file first (`BASH_XTRACEFD`) purely
        so a genuinely full-script trace doesn't corrupt the `$(cmd 2>&1)`
        captures the rest of the (unrelated, untouched) script relies on;
        `xtrace_log` is what a caller asserts the token absent from.
        """
        self._debug_trap_file = self.root.parent / "debug-trap-bash-env"
        self._debug_trap_file.write_text(
            f"exec 9>>{self._xtrace_log_file}\n"
            "export BASH_XTRACEFD=9\n"
            "set -o functrace\n"
            "trap 'set -x' DEBUG\n",
        )

    def enable_inherited_xtrace(self) -> None:
        """Simulate an ancestor shell's `bash -x` carrying in via `SHELLOPTS`.

        Bash activates every option named in `SHELLOPTS` at startup, so this
        reproduces inherited xtrace without invoking the script under
        `bash -x` itself (#1349 review). See `inject_debug_trap` above for why
        trace output is redirected to `xtrace_log` rather than left on stderr.
        """
        self._shellopts = "xtrace"
        self._debug_trap_file = self.root.parent / "xtrace-bash-env"
        self._debug_trap_file.write_text(
            f"exec 9>>{self._xtrace_log_file}\nexport BASH_XTRACEFD=9\n",
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
                "BASH_ENV": str(self._jq_path_filter or self._debug_trap_file or ""),
                "SHELLOPTS": self._shellopts,
                "HOME": str(self.root.parent),
                "LOG_CAPTURE_FILE": str(self.log_file),
                "DOCKER_CALLS_FILE": str(self.docker_calls_file),
                "CURL_CALLS_FILE": str(self.curl_calls_file),
                "TOKEN_ENV_CALLS_FILE": str(self.token_env_calls_file),
                "SONGMAKER_AUTODEPLOY_OVERNIGHTWORKS_READ_TOKEN_FILE": str(
                    self.overnightworks_token_file,
                ),
                "GH_CHECK_RUNS_FILE": str(self.check_runs_file),
                "GH_CHECK_RUNS_DIRECTORY": str(self.check_runs_directory),
                "GH_CHECK_RUNS_RAW_RESPONSE_FILE": str(self.check_runs_raw_response_file),
                "GH_CHECK_RUNS_STDERR": self.check_runs_stderr,
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
                "SONGMAKER_AUTODEPLOY_CHECK_RUN_LOOKBACK_COMMITS": str(
                    self.check_run_lookback_commits,
                ),
                "SONGMAKER_AUTODEPLOY_PRUNE_TIMEOUT_SECONDS": str(PRUNE_TIMEOUT_SECONDS),
                "DOCKER_PRUNE_SLEEP_SECONDS": str(self._prune_sleep_seconds),
                "DOCKER_BASE_IMAGES_PRESENT": str(self._base_images_present).lower(),
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

    @property
    def token_env_calls(self) -> str:
        """`<binary args>=<token-or-<unset>>` for every stubbed-process call.

        Proves which processes the real overnightworks read token (#1349)
        reached, and — just as importantly — which ones never saw it.
        """
        return self.token_env_calls_file.read_text() if self.token_env_calls_file.exists() else ""

    @property
    def non_build_token_env_calls(self) -> list[str]:
        """Every recorded call except the one `compose build` call itself.

        `compose build` is the only process the token may legitimately
        reach (#1349); every other recorded call — `compose up`/`ps`,
        `logger`, etc. — must never carry it, so a caller asserts the token
        absent from every line this returns, not just one hand-picked line.
        """
        return [
            line
            for line in self.token_env_calls.splitlines()
            if not line.startswith("compose build=")
        ]

    @property
    def xtrace_log(self) -> str:
        """Captured `set -x` output when `inject_debug_trap`/
        `enable_inherited_xtrace` redirected it here instead of stderr."""
        return (
            self._xtrace_log_file.read_text() if self._xtrace_log_file.exists() else ""
        )

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
        "image prune --force --filter until=48h --filter label!=songmaker.base-image=true",
        "builder prune --all --force --filter until=48h",
    ]
    assert "pruned unreferenced Docker images and build cache older than 48h" in checkout.journal


def test_a_successful_build_exports_the_overnightworks_token_only_to_the_build_call(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()

    result = checkout.tick()

    assert result.returncode == 0
    assert f"compose build={DEFAULT_OVERNIGHTWORKS_TOKEN}" in checkout.token_env_calls
    assert "compose up=<unset>" in checkout.token_env_calls


@pytest.mark.parametrize(
    ("token_content", "expected_journal_substring"),
    [
        pytest.param(
            None,
            "cannot read overnightworks read token file",
            id="missing-token-file",
        ),
        pytest.param(
            "",
            "is empty (#1349)",
            id="empty-token-file",
        ),
    ],
)
def test_a_bad_overnightworks_token_file_fails_the_tick_before_compose_build(
    tmp_path: Path, token_content: str | None, expected_journal_substring: str,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    checkout.set_overnightworks_token(token_content)

    result = checkout.tick()

    assert result.returncode == 0
    assert expected_journal_substring in checkout.journal
    assert checkout.failure_count_file.read_text() == "1"
    assert "compose build" not in checkout.docker_calls


def test_a_failed_build_s_children_do_not_see_the_overnightworks_token(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    checkout.set_compose_build_exit_code(7)

    result = checkout.tick()

    assert result.returncode == 0
    assert "docker compose build failed in" in checkout.journal
    assert "exit 7" in checkout.journal
    assert checkout.failure_count_file.read_text() == "1"
    assert "compose up" not in checkout.docker_calls
    non_build_calls = checkout.non_build_token_env_calls
    assert non_build_calls
    assert all(DEFAULT_OVERNIGHTWORKS_TOKEN not in call for call in non_build_calls)


@pytest.mark.parametrize(
    "contaminate",
    [
        pytest.param(Checkout.enable_inherited_xtrace, id="inherited-shellopts-xtrace"),
        pytest.param(Checkout.inject_debug_trap, id="inherited-functrace-debug-trap"),
    ],
)
def test_the_overnightworks_token_never_reaches_output_under_inherited_tracing(
    tmp_path: Path, contaminate: Callable[[Checkout], None],
) -> None:
    """Neither an inherited `bash -x`/xtrace nor an inherited DEBUG trap with
    functrace may ever print the token (#1349 review): both carry into the
    build subshell like any other shell option or trap unless the subshell
    itself clears them before the token is read.
    """
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    contaminate(checkout)

    result = checkout.tick()

    assert result.returncode == 0
    assert checkout.xtrace_log, "inherited tracing never actually activated"
    assert f"compose build={DEFAULT_OVERNIGHTWORKS_TOKEN}" in checkout.token_env_calls
    assert DEFAULT_OVERNIGHTWORKS_TOKEN not in result.stdout
    assert DEFAULT_OVERNIGHTWORKS_TOKEN not in result.stderr
    assert DEFAULT_OVERNIGHTWORKS_TOKEN not in checkout.journal
    assert DEFAULT_OVERNIGHTWORKS_TOKEN not in checkout.xtrace_log


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
    assert "docker/base changed since deployed revision" in checkout.journal


def test_an_unchanged_base_image_is_not_built(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()

    result = checkout.tick()

    assert result.returncode == 0
    assert "compose build" in checkout.docker_calls
    assert "build -f docker/base/" not in checkout.docker_calls


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


@pytest.mark.parametrize(
    ("job_name", "conclusion"),
    [
        (REQUIRED_ACTIONS_JOB_NAME, "failure"),
        (REQUIRED_ACTIONS_JOB_NAME, "cancelled"),
        ("Sonarcloud scan", "failure"),
    ],
)
def test_non_successful_github_actions_checks_are_skipped(
    tmp_path: Path,
    job_name: str,
    conclusion: str,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    local_head_before = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip()
    checkout.set_check_runs(
        ("completed", "success"),
        ("github-actions", job_name, "completed", conclusion),
    )

    result = checkout.tick()

    assert result.returncode == 0
    assert "skipping deploy candidate" in checkout.journal
    assert "no fully green deploy candidate" in checkout.journal
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
        (
            "github-actions",
            ADVISORY_ACTIONS_JOB_NAME,
            f"GitHub Actions job '{ADVISORY_ACTIONS_JOB_NAME}' is advisory, ignored",
        ),
    ],
)
@pytest.mark.parametrize(
    "through_github_api_filter", [False, True], ids=["projected", "raw-api-response"],
)
def test_a_failed_advisory_check_does_not_block_a_green_github_actions_candidate(
    tmp_path: Path,
    app_slug: str,
    name: str,
    advisory_log: str,
    through_github_api_filter: bool,
) -> None:
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


def test_the_advisory_job_name_is_the_sonarcloud_job_name_in_ci() -> None:
    script_value = re.search(
        r'^ADVISORY_ACTIONS_JOB_NAME="([^"]+)"$', DEPLOY_SCRIPT.read_text(), re.MULTILINE,
    )
    ci_jobs = yaml.safe_load(CI_WORKFLOW.read_text())["jobs"]

    assert script_value is not None
    assert ci_jobs["sonar"]["name"] == script_value.group(1)


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
    assert f"skipping deploy candidate {running_head}: waiting" in checkout.journal
    assert f"selected newest fully green deploy candidate {green_predecessor}" in checkout.journal


def test_failed_head_deploys_the_newest_green_predecessor(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    green_predecessor = checkout.remote_main_sha()
    checkout.move_main_forward()
    failed_head = checkout.remote_main_sha()
    checkout.set_check_runs_for_commit(failed_head, ("completed", "failure"))
    checkout.set_check_runs_for_commit(green_predecessor, ("completed", "success"))

    result = checkout.tick()

    assert result.returncode == 0
    assert subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout.root, text=True,
    ).strip() == green_predecessor
    assert f"skipping deploy candidate {failed_head}: failed" in checkout.journal
    assert f"selected newest fully green deploy candidate {green_predecessor}" in checkout.journal


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
    assert "no fully green deploy candidate among the newest 1 commits" in checkout.journal
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
    assert "skipping deploy candidate" in checkout.journal
    assert "no fully green deploy candidate" in checkout.journal
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
    assert "no fully green deploy candidate" in checkout.journal
    assert "failure count now" not in checkout.journal
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

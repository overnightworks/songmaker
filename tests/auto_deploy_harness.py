"""A throwaway deploy checkout for driving scripts/auto-deploy.sh as a real subprocess.

The script is copied into a git checkout with its own origin and runs with
``logger``, ``docker``, ``gh``, ``curl`` and ``date`` replaced by fakes on PATH:
no real deploy, no syslog, no network, no waiting.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from auto_deploy_support import (
    ACESTEP_SUBMODULE_PATH,
    ALERT_CONFIG_LIB,
    ALERT_REPEAT_SECONDS,
    CHECK_RUN_APPEARANCE_GRACE_SECONDS,
    CHECK_RUN_LOOKUP_TIMEOUT_SECONDS,
    CLOCK_START_EPOCH,
    DEPLOY_SCRIPT,
    FAILURE_ALERT_THRESHOLD,
    GIT_FETCH_KILL_GRACE_SECONDS,
    GIT_FETCH_TIMEOUT_SECONDS,
    HUNG_TRANSPORT_SECONDS,
    MIGRATIONS_PATH,
    PROMETHEUS_METRICS_RESPONSE,
    PROMETHEUS_RULE_PATH,
    PRUNE_TIMEOUT_SECONDS,
    REPO_ROOT,
    VALID_ALERT_ENV,
    AcestepFork,
    ComposeConfigRefusal,
    FailingTransport,
    check_runs_response,
    count_alerting_rules,
    git,
    git_output,
    prometheus_rules_response,
    write_executable,
)


class Checkout:
    """A throwaway deploy target the script under test can be run against."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "checkout"
        self.origin = tmp_path / "origin.git"
        self.log_file = tmp_path / "journal.txt"
        self.docker_calls_file = tmp_path / "docker-calls.txt"
        self.docker_release_env_file = tmp_path / "docker-release-env.txt"
        self.curl_calls_file = tmp_path / "curl-calls.txt"
        self.check_runs_file = tmp_path / "check-runs.txt"
        self.check_runs_raw_response_file = tmp_path / "check-runs-response.json"
        self.check_runs_directory = tmp_path / "check-runs"
        self.check_runs_directory.mkdir()
        self.post_merge_marker = tmp_path / "post-merge-ran.txt"
        self._after_check_lookup_script: Path | None = None
        self._bin = tmp_path / "bin"
        self._bin.mkdir()
        self._failing_transport_pid_file = tmp_path / "failing-transport.pid"
        self._system_bin_without_jq: Path | None = None
        self._jq_path_filter: Path | None = None
        self._clock_file = tmp_path / "clock.txt"
        self._clock_file.write_text(str(CLOCK_START_EPOCH))
        self._commits_pushed = 0
        self._releases_cut = 0
        self._hal_path = tmp_path / "hal"
        self._active_job_count = 0
        self._base_images_present = True
        self._prune_exit_code = 0
        self._prune_sleep_seconds = 0
        self._compose_up_exit_code = 0
        self._compose_project_name = "songmaker"
        self._compose_config_refusal: ComposeConfigRefusal | None = None
        self._prometheus_ready_exit_code = 0
        self._prometheus_reload_exit_code = 0
        self._prometheus_rules_exit_code = 0
        self._prometheus_metrics_exit_code = 0
        self._prometheus_rules_response: str | None = None
        self._prometheus_metrics_response = PROMETHEUS_METRICS_RESPONSE
        self._prometheus_container = "0123456789ab"
        self.compose_stderr = ""
        self.check_runs_stderr = ""
        self.check_run_lookup_timeout_seconds = CHECK_RUN_LOOKUP_TIMEOUT_SECONDS
        self.check_run_appearance_grace_seconds = CHECK_RUN_APPEARANCE_GRACE_SECONDS
        self.check_run_lookback_commits = 10
        self.git_fetch_timeout_seconds = GIT_FETCH_TIMEOUT_SECONDS

        self._create_repository(tmp_path)
        self._install_fakes()
        self.set_check_runs(("completed", "success"))
        self.set_active_jobs(0)

    def _create_repository(self, tmp_path: Path) -> None:
        git(tmp_path, "init", "--bare", "--initial-branch=main", str(self.origin))
        git(tmp_path, "clone", str(self.origin), str(self.root))
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "config", "user.name", "Test")

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
        git(self.root, "add", "-A")
        git(self.root, "commit", "-m", "initial")
        git(self.root, "push", "origin", "main")
        # The deploy checkout sits detached at a release, never on a branch.
        git(self.root, "checkout", "--detach")

    def _install_fakes(self) -> None:
        write_executable(
            self._bin / "logger",
            '#!/bin/bash\nprintf "%s\\n" "$*" >> "$LOG_CAPTURE_FILE"\n',
        )
        write_executable(
            self._bin / "date",
            "#!/bin/bash\n"
            'if [[ "$1" == "+%s" ]]; then\n'
            '    cat "$FAKE_CLOCK_FILE"\n'
            "else\n"
            '    exec /usr/bin/date "$@"\n'
            "fi\n",
        )
        self._write_curl_stub()

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

    def refuse_compose_config(self, refusal: ComposeConfigRefusal) -> None:
        """Make `docker compose config --quiet` fail the way compose itself does."""
        self._compose_config_refusal = refusal
        self._write_docker_stub()

    def satisfy_compose_config(self) -> None:
        """Stand in for the operator adding the missing variable to .env."""
        self._compose_config_refusal = None
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

    @property
    def configured_alerting_rules(self) -> int:
        return count_alerting_rules(self.root / PROMETHEUS_RULE_PATH)

    @property
    def _loaded_rules_response(self) -> str:
        if self._prometheus_rules_response is None:
            return prometheus_rules_response(self.configured_alerting_rules)
        return self._prometheus_rules_response

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
        write_executable(
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
            f"    printf '%s' {shlex.quote(self._loaded_rules_response)}\n"
            f"    exit {self._prometheus_rules_exit_code}\n"
            "fi\n"
            'echo "unexpected curl invocation: $*" >&2\n'
            "exit 2\n",
        )

    def _compose_config_quiet_stub(self) -> str:
        """Compose's own validation; the wrapper runs it inside the checkout."""
        refusal_branch = ""
        refusal = self._compose_config_refusal
        if refusal is not None:
            condition = (
                "true"
                if refusal.when_compose_file_contains is None
                else f"grep -qsF -- {shlex.quote(refusal.when_compose_file_contains)} "
                "docker-compose.yml"
            )
            refusal_branch = (
                f"    if {condition}; then\n"
                f"        printf '%s\\n' {shlex.quote(refusal.stderr)} >&2\n"
                "        exit 1\n"
                "    fi\n"
            )
        return (
            'if [[ "$1" == "compose" && "$2" == "config" && "$3" == "--quiet" ]]; then\n'
            '    if [[ -n "${DOCKER_COMPOSE_STDERR:-}" ]]; then\n'
            '        printf "%s\\n" "$DOCKER_COMPOSE_STDERR" >&2\n'
            "    fi\n"
            + refusal_branch
            + "    exit 0\n"
            "fi\n"
        )

    def _write_docker_stub(self) -> None:
        write_executable(
            self._bin / "docker",
            "#!/bin/bash\n"
            'printf "%s\\n" "$*" >> "$DOCKER_CALLS_FILE"\n'
            'printf "%s\\t%s\\t%s\\n" "$*" "${SONGMAKER_RELEASE-}" "${SONGMAKER_COMMIT-}" '
            '>> "$DOCKER_RELEASE_ENV_FILE"\n'
            + self._compose_config_quiet_stub()
            +
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
        self.set_check_runs_response(check_runs_response(*runs))

    def set_check_runs_response(self, response: str) -> None:
        """Make the fake gh process return an already-projected API response."""
        self.check_runs_file.write_text(response)
        write_executable(
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
        (self.check_runs_directory / commit_sha).write_text(check_runs_response(*runs))

    def set_check_runs_raw_response(self, response: str) -> None:
        """Make the fake gh process apply its jq filter to a raw API response."""
        self.check_runs_raw_response_file.write_text(response)

    def make_check_lookup_fail(self) -> None:
        write_executable(
            self._bin / "gh",
            "#!/bin/bash\n"
            'echo "GitHub API unavailable" >&2\n'
            "exit 1\n",
        )

    def make_check_lookup_terminate(self, *, kill: bool) -> None:
        write_executable(
            self._bin / "gh",
            "#!/bin/bash\n"
            + ("kill -KILL $$\n" if kill else 'exec sleep "$GH_CHECK_RUN_LOOKUP_HANG_SECONDS"\n'),
        )

    def write_alert_config(self, content: str = VALID_ALERT_ENV) -> None:
        (self.root / ".env").write_text(content)

    def write_mount_preflight(self, body: str) -> None:
        write_executable(self.root / "scripts" / "check_agent_cli_mounts.sh", body)

    def commit_mount_preflight(self, body: str) -> None:
        self.write_mount_preflight(body)
        git(self.root, "add", "scripts/check_agent_cli_mounts.sh")
        git(self.root, "commit", "-m", "add mount preflight")
        self._publish_root_head()

    def _publish_root_head(self) -> None:
        git(self.root, "push", "origin", "HEAD:main")
        git(self.root, "branch", "--force", "main", "HEAD")

    def _land(self, clone: Path, *, release: bool) -> None:
        """Push the clone's commit to main, and cut the next release tag on it."""
        git(clone, "push", "origin", "main")
        if release:
            self.cut_release(clone)

    def cut_release(
        self, clone: Path | None = None, *, name: str | None = None, schema: str | None = None,
    ) -> str:
        """Tag the clone's HEAD with the next release name, as the head does by hand."""
        clone = clone or self._up_to_date_pusher()
        self._releases_cut += 1
        tag = name or f"v2026.10.25.{self._releases_cut}"
        message = f"release {tag}" + (f"\n\nschema: {schema}" if schema else "")
        git(clone, "tag", "--annotate", "--message", message, tag)
        git(clone, "push", "origin", tag)
        return tag

    def _up_to_date_pusher(self) -> Path:
        """A second clone standing in for whoever lands commits on origin/main."""
        clone = self.root.parent / "pusher"
        if not clone.exists():
            git(self.root.parent, "clone", str(self.origin), str(clone))
            git(clone, "config", "user.email", "test@example.com")
            git(clone, "config", "user.name", "Test")
        git(clone, "pull", "--ff-only", "origin", "main")
        return clone

    def move_main_forward(self, *, release: bool = True) -> None:
        clone = self._up_to_date_pusher()
        self._commits_pushed += 1
        (clone / "README.md").write_text(f"moved {self._commits_pushed}\n")
        git(clone, "commit", "-am", f"move main {self._commits_pushed}")
        self._land(clone, release=release)

    def move_main_forward_with_changed_alert_rules(self, *, release: bool = True) -> None:
        clone = self._up_to_date_pusher()
        rules = clone / PROMETHEUS_RULE_PATH
        rules.write_text(rules.read_text() + "\n# changed by deploy test\n")
        git(clone, "add", str(PROMETHEUS_RULE_PATH))
        git(clone, "commit", "-m", "change alert rules")
        self._land(clone, release=release)

    def move_main_forward_with_changed_prometheus_config(self, *, release: bool = True) -> None:
        clone = self._up_to_date_pusher()
        config = clone / "monitoring" / "prometheus.yml"
        config.write_text(config.read_text() + "\n# changed by deploy test\n")
        git(clone, "add", "monitoring/prometheus.yml")
        git(clone, "commit", "-m", "change Prometheus config")
        self._land(clone, release=release)

    def move_main_forward_with_changed_base_image(self, *, release: bool = True) -> None:
        clone = self._up_to_date_pusher()
        base_dockerfile = clone / "docker" / "base" / "acestep-base.Dockerfile"
        base_dockerfile.parent.mkdir(parents=True)
        base_dockerfile.write_text("# changed by deploy test\n")
        git(clone, "add", "docker/base/acestep-base.Dockerfile")
        git(clone, "commit", "-m", "change base image")
        self._land(clone, release=release)

    def add_acestep_submodule(self, fork: AcestepFork, *, initialised: bool = True) -> None:
        """Pin vendor/acestep to the fork's head, as the host's checkout has it."""
        (self.root / ".gitmodules").write_text(
            f'[submodule "{ACESTEP_SUBMODULE_PATH}"]\n'
            f"\tpath = {ACESTEP_SUBMODULE_PATH}\n"
            f"\turl = {fork.origin.as_uri()}\n",
        )
        git(
            self.root, "update-index", "--add", "--cacheinfo",
            f"160000,{fork.head},{ACESTEP_SUBMODULE_PATH}",
        )
        git(self.root, "add", ".gitmodules")
        git(self.root, "commit", "-m", "pin vendor/acestep")
        self._publish_root_head()
        # What a clone leaves behind for a submodule nobody initialised yet.
        (self.root / ACESTEP_SUBMODULE_PATH).mkdir(parents=True)
        if initialised:
            git(
                self.root, "-c", "protocol.file.allow=always",
                "submodule", "update", "--init", "--", ACESTEP_SUBMODULE_PATH,
            )

    def move_main_forward_with_acestep_pin(self, pinned_sha: str, *, release: bool = True) -> None:
        clone = self._up_to_date_pusher()
        git(
            clone, "update-index", "--cacheinfo",
            f"160000,{pinned_sha},{ACESTEP_SUBMODULE_PATH}",
        )
        git(clone, "commit", "-m", f"pin vendor/acestep at {pinned_sha}")
        self._land(clone, release=release)

    def move_main_forward_with_migration(
        self, revision: str, down_revision: str | None = None, *, release: bool = True,
    ) -> None:
        clone = self._up_to_date_pusher()
        migration = clone / MIGRATIONS_PATH / f"{revision}_migration.py"
        migration.parent.mkdir(parents=True, exist_ok=True)
        down = "None" if down_revision is None else f'"{down_revision}"'
        migration.write_text(
            f'revision: str = "{revision}"\n'
            f"down_revision: Union[str, None] = {down}\n",
        )
        git(clone, "add", MIGRATIONS_PATH)
        git(clone, "commit", "-m", f"migration {revision}")
        self._land(clone, release=release)

    def install_backup_command(self, exit_code: int) -> None:
        """Stand in for `hal backup songmaker --pre-apply`, recording into the Docker call log.

        Like edge's launcher it needs `uv` on its PATH, and `uv` lives only in the
        user's executables directory, which the harness PATH does not hold.
        """
        user_executables = self.root.parent / ".local" / "bin"
        user_executables.mkdir(parents=True, exist_ok=True)
        write_executable(user_executables / "uv", "#!/bin/bash\nexit 0\n")
        write_executable(
            self._hal_path,
            "#!/bin/bash\n"
            f'[ "$(command -v uv)" = {shlex.quote(str(user_executables / "uv"))} ] || '
            "{ echo 'uv: not found' >&2; exit 3; }\n"
            'printf "hal %s\\n" "$*" >> "$DOCKER_CALLS_FILE"\n'
            f"exit {exit_code}\n",
        )

    @property
    def backup_calls(self) -> list[str]:
        return [call for call in self.docker_calls.splitlines() if call.startswith("hal ")]

    def move_main_forward_with_compose_file(self, content: str, *, release: bool = True) -> None:
        clone = self._up_to_date_pusher()
        (clone / "docker-compose.yml").write_text(content)
        git(clone, "add", "docker-compose.yml")
        git(clone, "commit", "-m", "change compose file")
        self._land(clone, release=release)

    def move_main_forward_after_check_lookup(self) -> None:
        """Advance origin after the deploy script has checked its current SHA."""
        clone = self.root.parent / "pusher"
        assert clone.exists()
        self._after_check_lookup_script = self._bin / "move-main-after-check-lookup"
        clone_text = shlex.quote(str(clone))
        readme_text = shlex.quote(str(clone / "README.md"))
        late_tag = f"v2026.10.25.{self._releases_cut + 1000}"
        write_executable(
            self._after_check_lookup_script,
            "#!/bin/bash\n"
            "set -euo pipefail\n"
            f"printf 'moved after check lookup\\n' > {readme_text}\n"
            f"/usr/bin/git -C {clone_text} commit -am "
            "'move main after check lookup' >/dev/null 2>&1\n"
            f"/usr/bin/git -C {clone_text} push origin main >/dev/null 2>&1\n"
            f"/usr/bin/git -C {clone_text} tag -a -m late {late_tag} >/dev/null 2>&1\n"
            f"/usr/bin/git -C {clone_text} push origin {late_tag} >/dev/null 2>&1\n",
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

    def make_fetches_fail(self, repository: Path, transport: FailingTransport) -> None:
        """Make every fetch from this repository's origin run the failing transport.

        The script runs git with a scrubbed environment and an absolute binary,
        so neither PATH nor GIT_SSH_COMMAND can slow it down; the repository's
        own remote.origin.uploadpack setting is the one seam it still honours.
        """
        upload_pack = self._bin / "failing-upload-pack"
        write_executable(
            upload_pack,
            f"#!/bin/bash\necho $$ >{self._failing_transport_pid_file}\n"
            f"{transport.value}exec sleep {HUNG_TRANSPORT_SECONDS}\n",
        )
        git(repository, "config", "remote.origin.uploadpack", str(upload_pack))

    def make_fetches_work_again(self, repository: Path) -> None:
        git(repository, "config", "--unset", "remote.origin.uploadpack")

    def switch_to_work_branch(self) -> None:
        git(self.root, "checkout", "-B", "work")

    def switch_to_main(self) -> None:
        git(self.root, "checkout", "main")

    def advance_clock(self, seconds: int) -> None:
        """Let time pass for the script without any passing for the test."""
        self._clock_file.write_text(str(int(self._clock_file.read_text()) + seconds))

    def set_clock(self, epoch_seconds: int) -> None:
        self._clock_file.write_text(str(epoch_seconds))

    def observe_sweep_at_fetch(self, removed: Path, preserved: list[Path]) -> Path:
        observed = self.root.parent / "sweep-observed"
        checks = [f'[[ ! -e {shlex.quote(str(removed))} && ! -L {shlex.quote(str(removed))} ]]']
        checks.extend(f'[[ -e {shlex.quote(str(path))} ]]' for path in preserved)
        upload_pack = self._bin / "observing-upload-pack"
        write_executable(
            upload_pack, "#!/bin/bash\n"
            + " && ".join(checks) + f" && touch {shlex.quote(str(observed))}\n"
            'exec /usr/bin/git-upload-pack "$@"\n',
        )
        git(self.root, "config", "remote.origin.uploadpack", str(upload_pack))
        return observed

    def refuse_removal(self, path: Path) -> None:
        write_executable(
            self._bin / "rm", "#!/bin/bash\n"
            f'for arg; do [[ "$arg" == {shlex.quote(str(path))} ]] && exit 1; done\n'
            'exec /bin/rm "$@"\n',
        )

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
                "DOCKER_RELEASE_ENV_FILE": str(self.docker_release_env_file),
                "CURL_CALLS_FILE": str(self.curl_calls_file),
                "GH_CHECK_RUNS_FILE": str(self.check_runs_file),
                "GH_CHECK_RUNS_DIRECTORY": str(self.check_runs_directory),
                "GH_CHECK_RUNS_RAW_RESPONSE_FILE": str(self.check_runs_raw_response_file),
                "GH_CHECK_RUNS_STDERR": self.check_runs_stderr,
                "GH_CHECK_RUN_LOOKUP_HANG_SECONDS": "10",
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
                "SONGMAKER_AUTODEPLOY_GIT_FETCH_TIMEOUT_SECONDS": str(
                    self.git_fetch_timeout_seconds,
                ),
                "SONGMAKER_AUTODEPLOY_GIT_FETCH_KILL_GRACE_SECONDS": str(
                    GIT_FETCH_KILL_GRACE_SECONDS,
                ),
                "SONGMAKER_AUTODEPLOY_PRUNE_TIMEOUT_SECONDS": str(PRUNE_TIMEOUT_SECONDS),
                "DOCKER_PRUNE_SLEEP_SECONDS": str(self._prune_sleep_seconds),
                "DOCKER_BASE_IMAGES_PRESENT": str(self._base_images_present).lower(),
                "DOCKER_COMPOSE_PROJECT_NAME": self._compose_project_name,
                "DOCKER_COMPOSE_STDERR": self.compose_stderr,
                "SONGMAKER_AUTODEPLOY_HAL": str(self._hal_path),
            },
        )

    @property
    def journal_above_debug(self) -> list[str]:
        return [line for line in self.journal.splitlines() if "-p user.debug" not in line]

    def commit_of(self, release_tag: str) -> str:
        return git_output(self.origin, "rev-parse", f"{release_tag}^{{commit}}")

    def detach_at(self, commit: str) -> None:
        git(self.root, "checkout", "--detach", commit)

    @property
    def journal(self) -> str:
        return self.log_file.read_text() if self.log_file.exists() else ""

    @property
    def head(self) -> str:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True,
        ).strip()

    @property
    def failing_transport_pid(self) -> int:
        return int(self._failing_transport_pid_file.read_text())

    @property
    def acestep_head(self) -> str:
        return git_output(self.root / ACESTEP_SUBMODULE_PATH, "rev-parse", "HEAD")

    @property
    def uncommitted_changes(self) -> str:
        return git_output(self.root, "status", "--porcelain")

    @property
    def build_and_recreate_calls(self) -> list[str]:
        return [
            call for call in self.docker_calls.splitlines()
            if "build" in call or call.startswith("compose up")
        ]

    @property
    def release_env_of_build_and_recreate_calls(self) -> dict[str, tuple[str, str]]:
        """Per `compose build` / `compose up` call: the release and commit it ran with."""
        lines = (
            self.docker_release_env_file.read_text().splitlines()
            if self.docker_release_env_file.exists() else []
        )
        recorded = (line.split("\t") for line in lines)
        return {
            call: (release, commit) for call, release, commit in recorded
            if "build" in call or call.startswith("compose up")
        }

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

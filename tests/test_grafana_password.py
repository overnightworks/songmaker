"""Behavioral tests for scripts/grafana-password.sh (issue #1359), driven as a real subprocess.

Fake ``docker`` and ``openssl`` executables stand first on PATH: docker records
its argv and stdin instead of reaching a Grafana container, openssl returns a
fixed value, so every test can assert exactly where that value went — into
``.env`` and onto docker's stdin, and nowhere else.
"""

from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "grafana-password.sh"

FRESH_VALUE = "0123456789abcdef" * 4
STRONG_VALUE = "kept-strong-value-7f3a9c"
ENV_MODE = 0o640
APPLY_ARGV = [
    "compose", "exec", "-T", "grafana",
    "grafana", "cli", "admin", "reset-admin-password", "--password-from-stdin",
]

# Lines that must survive every rewrite byte for byte: a comment and a
# neighbouring key that both mention the weak value, a quoted secret, and a
# last line without its trailing newline.
LINES_BEFORE = (
    "# GRAFANA_PASSWORD=admin is the compose default\n"
    "GRAFANA_USER=admin\n"
    "SMTP_PASSWORD='p@ss word#x'\n"
)
LINES_AFTER = "  INDENTED_KEY=value \t\nLAST_KEY=no-trailing-newline"


@dataclass(frozen=True)
class Run:
    returncode: int
    stdout: str
    stderr: str
    docker_argv: list[str] | None
    docker_stdin: str | None


@dataclass(frozen=True)
class Sandbox:
    env_file: Path
    bin_dir: Path
    docker_argv_file: Path
    docker_stdin_file: Path

    def write_env(self, grafana_line: str) -> str:
        content = LINES_BEFORE + grafana_line + LINES_AFTER
        self.env_file.write_text(content)
        self.env_file.chmod(ENV_MODE)
        return content

    def run(self, *, docker_fails: bool = False) -> Run:
        for record in (self.docker_argv_file, self.docker_stdin_file):
            record.unlink(missing_ok=True)
        completed = subprocess.run(
            [str(SCRIPT)],
            capture_output=True,
            text=True,
            check=False,
            env={
                "PATH": f"{self.bin_dir}{os.pathsep}{os.environ['PATH']}",
                "SONGMAKER_GRAFANA_ENV_FILE": str(self.env_file),
                "FAKE_DOCKER_ARGV_FILE": str(self.docker_argv_file),
                "FAKE_DOCKER_STDIN_FILE": str(self.docker_stdin_file),
                "FAKE_DOCKER_FAILS": "1" if docker_fails else "0",
            },
        )
        return Run(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            docker_argv=_read_lines(self.docker_argv_file),
            docker_stdin=_read_text(self.docker_stdin_file),
        )


def _read_text(path: Path) -> str | None:
    return path.read_text() if path.exists() else None


def _read_lines(path: Path) -> list[str] | None:
    text = _read_text(path)
    return None if text is None else text.splitlines()


def _install_executable(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\nset -euo pipefail\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # On failure the fake echoes what it was given, standing in for any tool in
    # the chain that might print its input: the script must still not leak it.
    _install_executable(
        bin_dir / "docker",
        'printf "%s\\n" "$@" > "$FAKE_DOCKER_ARGV_FILE"\n'
        'cat > "$FAKE_DOCKER_STDIN_FILE"\n'
        'if [[ "$FAKE_DOCKER_FAILS" == "1" ]]; then\n'
        '    echo "Error: could not reset password: $(cat "$FAKE_DOCKER_STDIN_FILE")"\n'
        "    exit 1\n"
        "fi\n"
        'echo "Admin password changed successfully"\n',
    )
    _install_executable(
        bin_dir / "openssl",
        '[[ "$*" == "rand -hex 32" ]] || exit 2\n'
        f'echo "{FRESH_VALUE}"\n',
    )
    env_dir = tmp_path / "checkout"
    env_dir.mkdir()
    return Sandbox(
        env_file=env_dir / ".env",
        bin_dir=bin_dir,
        docker_argv_file=tmp_path / "docker-argv",
        docker_stdin_file=tmp_path / "docker-stdin",
    )


def _assert_value_kept_secret(run: Run, value: str) -> None:
    assert value not in run.stdout
    assert value not in run.stderr
    assert value not in "\n".join(run.docker_argv or [])


def _assert_only_env_left(sandbox: Sandbox) -> None:
    assert [path.name for path in sandbox.env_file.parent.iterdir()] == [".env"]


@pytest.mark.parametrize(
    "grafana_line",
    [
        pytest.param("", id="absent"),
        pytest.param("GRAFANA_PASSWORD=\n", id="empty"),
        pytest.param("GRAFANA_PASSWORD=admin\n", id="admin"),
        pytest.param("GRAFANA_PASSWORD=CHANGEME_grafana_password\n", id="changeme"),
        pytest.param('GRAFANA_PASSWORD="admin"\n', id="double-quoted-admin"),
        pytest.param("export GRAFANA_PASSWORD='admin' # compose default\n", id="exported-admin"),
    ],
)
def test_a_missing_or_publicly_known_password_is_replaced_and_applied_unseen(
    sandbox: Sandbox, grafana_line: str,
) -> None:
    sandbox.write_env(grafana_line)
    fresh_line = f"GRAFANA_PASSWORD={FRESH_VALUE}\n"
    expected = (
        LINES_BEFORE + fresh_line + LINES_AFTER
        if grafana_line
        else LINES_BEFORE + LINES_AFTER + "\n" + fresh_line
    )

    run = sandbox.run()

    assert (run.returncode, run.stdout) == (0, "set\n")
    assert sandbox.env_file.read_text() == expected
    assert stat.S_IMODE(sandbox.env_file.stat().st_mode) == ENV_MODE
    assert run.docker_argv == APPLY_ARGV
    assert run.docker_stdin == FRESH_VALUE + "\n"
    _assert_value_kept_secret(run, FRESH_VALUE)
    _assert_only_env_left(sandbox)


@pytest.mark.parametrize(
    "grafana_line",
    [
        pytest.param(f"GRAFANA_PASSWORD={STRONG_VALUE}\n", id="unquoted"),
        pytest.param(f"GRAFANA_PASSWORD='{STRONG_VALUE}'  # rotated\n", id="single-quoted"),
    ],
)
def test_a_strong_password_is_kept_and_applied_unseen(
    sandbox: Sandbox, grafana_line: str,
) -> None:
    original = sandbox.write_env(grafana_line)

    run = sandbox.run()

    assert (run.returncode, run.stdout) == (0, "already set\n")
    assert sandbox.env_file.read_text() == original
    assert run.docker_stdin == STRONG_VALUE + "\n"
    _assert_value_kept_secret(run, STRONG_VALUE)


def test_a_second_run_keeps_and_reapplies_the_value_the_first_run_set(
    sandbox: Sandbox,
) -> None:
    sandbox.write_env("GRAFANA_PASSWORD=admin\n")
    assert sandbox.run().stdout == "set\n"
    after_first_run = sandbox.env_file.read_text()

    second = sandbox.run()

    assert (second.returncode, second.stdout) == (0, "already set\n")
    assert sandbox.env_file.read_text() == after_first_run
    assert second.docker_stdin == FRESH_VALUE + "\n"
    _assert_value_kept_secret(second, FRESH_VALUE)


@pytest.mark.parametrize(
    ("grafana_line", "value", "env_after"),
    [
        pytest.param(
            "GRAFANA_PASSWORD=admin\n", FRESH_VALUE,
            LINES_BEFORE + f"GRAFANA_PASSWORD={FRESH_VALUE}\n" + LINES_AFTER,
            id="fresh-value-already-in-env",
        ),
        pytest.param(
            f"GRAFANA_PASSWORD={STRONG_VALUE}\n", STRONG_VALUE,
            LINES_BEFORE + f"GRAFANA_PASSWORD={STRONG_VALUE}\n" + LINES_AFTER,
            id="kept-value",
        ),
    ],
)
def test_a_failed_apply_fails_loud_without_revealing_the_value(
    sandbox: Sandbox, grafana_line: str, value: str, env_after: str,
) -> None:
    sandbox.write_env(grafana_line)

    run = sandbox.run(docker_fails=True)

    assert run.returncode != 0
    assert run.stdout == ""
    assert "Grafana failed" in run.stderr
    assert sandbox.env_file.read_text() == env_after
    _assert_value_kept_secret(run, value)
    _assert_only_env_left(sandbox)


@pytest.mark.parametrize(
    "grafana_line",
    [
        pytest.param('GRAFANA_PASSWORD="Zq9$x"\n', id="interpolation"),
        pytest.param("GRAFANA_PASSWORD='Zq9-x\n", id="unclosed-quote"),
    ],
)
def test_a_value_compose_would_read_differently_is_refused_untouched(
    sandbox: Sandbox, grafana_line: str,
) -> None:
    original = sandbox.write_env(grafana_line)

    run = sandbox.run()

    assert run.returncode != 0
    assert "GRAFANA_PASSWORD" in run.stderr
    assert "Zq9" not in run.stderr
    assert sandbox.env_file.read_text() == original
    assert run.docker_argv is None


def test_a_missing_env_file_is_refused_without_creating_one(sandbox: Sandbox) -> None:
    run = sandbox.run()

    assert run.returncode != 0
    assert not sandbox.env_file.exists()
    assert run.docker_argv is None

"""Behavioural tests for scripts/grafana_password.py (issue #1359), driven as a real subprocess.

The command runs from a scratch main checkout: a git repository holding the
command and the shared ``.env`` reader, with its ``.env`` at the root, exactly
where the real checkout keeps it.

A fake ``docker`` stands first on PATH in place of compose. It records every
argv and the apply's stdin, answers ``compose port grafana 3000`` with the
address of a stub Grafana API on loopback, and plays one apply outcome. The
stub accepts Basic auth only for the admin user and the password the fake last
applied, so the command's API proof sees what a real Grafana would.

When it fails, the fake echoes the stdin it was given, standing in for any tool
in the chain that might print its input: the command must still not leak it.
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import stat
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
COMMAND_FILES = ("grafana_password.py", "dotenv_file.py", "main_checkout.py")

ADMIN_USER = "grafana-admin"
INITIAL_GRAFANA_PASSWORD = "admin"
STRONG_VALUE = "kept-strong-value-7f3a9c"
ENV_MODE = 0o640
APPLY_ARGV = (
    "compose exec -T grafana "
    "grafana cli admin reset-admin-password --password-from-stdin"
)
PORT_ARGV = "compose port grafana 3000"
FRESH_LINE = re.compile(r"^GRAFANA_PASSWORD=([0-9a-f]{64})\r?$", re.MULTILINE)

# Lines that must survive every rewrite byte for byte: a comment and a
# neighbouring key that both mention the weak value, a quoted secret, a CRLF
# line, and a last line without its trailing newline.
LINES_BEFORE = (
    "# GRAFANA_PASSWORD=admin is the compose default\n"
    f"GRAFANA_USER={ADMIN_USER}\n"
    "SMTP_PASSWORD='p@ss word#x'\n"
    "WINDOWS_KEY=crlf\r\n"
)
LINES_AFTER = "  INDENTED_KEY=value \t\nLAST_KEY=no-trailing-newline"

FAKE_DOCKER = r"""#!/bin/bash
set -euo pipefail
printf '%s\n' "$*" >> "$FAKE_DOCKER_DIR/argv"
if [[ "$*" == "compose port grafana 3000" ]]; then
    echo "127.0.0.1:$FAKE_GRAFANA_PORT"
    exit 0
fi
cat > "$FAKE_DOCKER_DIR/stdin"
given="$(cat "$FAKE_DOCKER_DIR/stdin")"
confirm() { printf '\nAdmin password changed successfully \xe2\x9c\x94\n\n\n\n'; }
case "$FAKE_APPLY" in
    applies) printf '%s' "$given" > "$FAKE_DOCKER_DIR/grafana-password"; confirm ;;
    confirms-something-else)
        printf '%s' "$given" > "$FAKE_DOCKER_DIR/grafana-password"
        printf 'Admin password changed successfully \xe2\x9c\x94 for another user\n' ;;
    exits-zero-unconfirmed) echo "Error: failed to update user: $given" ;;
    confirms-without-applying) confirm ;;
    fails) echo "Error: could not reset password: $given" >&2; exit 1 ;;
esac
"""


class Apply(Enum):
    """What the fake ``grafana cli admin reset-admin-password`` does."""

    APPLIES = "applies"
    EXITS_ZERO_UNCONFIRMED = "exits-zero-unconfirmed"
    CONFIRMS_WITHOUT_APPLYING = "confirms-without-applying"
    CONFIRMS_SOMETHING_ELSE = "confirms-something-else"
    FAILS = "fails"


@dataclass(frozen=True)
class Run:
    returncode: int
    stdout: str
    stderr: str
    docker_calls: list[str]
    docker_stdin: str | None
    accepted_logins: int

    def reveals(self, value: str) -> bool:
        return any(value in text for text in (self.stdout, self.stderr, *self.docker_calls))


class StubGrafana:
    """Grafana's API as far as the proof sees it: Basic auth against the applied password."""

    def __init__(self, password_file: Path) -> None:
        self.password_file = password_file
        self.accepted_logins = 0
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/api/user" and stub.accepts(self.headers.get("Authorization")):
                    stub.accepted_logins += 1
                    self.send_response(HTTPStatus.OK)
                else:
                    self.send_response(HTTPStatus.UNAUTHORIZED)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    def accepts(self, authorization: str | None) -> bool:
        password = self.password_file.read_text()
        expected = base64.b64encode(f"{ADMIN_USER}:{password}".encode()).decode("ascii")
        return authorization == f"Basic {expected}"


@dataclass(frozen=True)
class Sandbox:
    checkout: Path
    bin_dir: Path
    docker_dir: Path
    grafana: StubGrafana

    @property
    def env_file(self) -> Path:
        return self.checkout / ".env"

    def write_env(self, grafana_line: str, checkout: Path | None = None) -> str:
        env_file = (checkout or self.checkout) / ".env"
        content = LINES_BEFORE + grafana_line + LINES_AFTER
        env_file.write_bytes(content.encode())
        env_file.chmod(ENV_MODE)
        return content

    def git(self, *arguments: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *arguments],
            cwd=self.checkout, check=True, capture_output=True,
        )

    def env_text(self) -> str:
        return self.env_file.read_bytes().decode()

    def run(self, apply: Apply = Apply.APPLIES, checkout: Path | None = None) -> Run:
        for record in ("argv", "stdin"):
            (self.docker_dir / record).unlink(missing_ok=True)
        logins_before = self.grafana.accepted_logins
        completed = subprocess.run(
            [str((checkout or self.checkout) / "scripts" / "grafana_password.py")],
            capture_output=True,
            text=True,
            check=False,
            env={
                "PATH": f"{self.bin_dir}{os.pathsep}{os.environ['PATH']}",
                "FAKE_DOCKER_DIR": str(self.docker_dir),
                "FAKE_GRAFANA_PORT": str(self.grafana.port),
                "FAKE_APPLY": apply.value,
            },
        )
        argv_log = self.docker_dir / "argv"
        stdin_log = self.docker_dir / "stdin"
        return Run(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            docker_calls=argv_log.read_text().splitlines() if argv_log.exists() else [],
            docker_stdin=stdin_log.read_text() if stdin_log.exists() else None,
            accepted_logins=self.grafana.accepted_logins - logins_before,
        )


@pytest.fixture
def sandbox(tmp_path: Path) -> Iterator[Sandbox]:
    checkout = tmp_path / "checkout"
    (checkout / "scripts").mkdir(parents=True)
    for name in COMMAND_FILES:
        shutil.copy2(SCRIPTS / name, checkout / "scripts" / name)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_docker = bin_dir / "docker"
    fake_docker.write_text(FAKE_DOCKER)
    fake_docker.chmod(fake_docker.stat().st_mode | stat.S_IEXEC)

    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    password_file = docker_dir / "grafana-password"
    password_file.write_text(INITIAL_GRAFANA_PASSWORD)
    grafana = StubGrafana(password_file)
    sandbox = Sandbox(checkout, bin_dir, docker_dir, grafana)
    sandbox.git("init", "-q")
    sandbox.git("add", "scripts")
    sandbox.git("commit", "-q", "-m", "the command")
    grafana.thread.start()
    try:
        yield sandbox
    finally:
        grafana.server.shutdown()
        grafana.server.server_close()
        grafana.thread.join()


def _fresh_value(env_text: str) -> str:
    matches = FRESH_LINE.findall(env_text)
    assert len(matches) == 1, "exactly one fresh 64-hex GRAFANA_PASSWORD line"
    return matches[0]


def _assert_no_temp_file_left(sandbox: Sandbox) -> None:
    assert list(sandbox.checkout.glob(".env.grafana-password.*")) == []


@pytest.mark.parametrize(
    "grafana_line",
    [
        pytest.param("", id="absent"),
        pytest.param("GRAFANA_PASSWORD=\n", id="empty"),
        pytest.param("GRAFANA_PASSWORD=admin\n", id="admin"),
        pytest.param("GRAFANA_PASSWORD=CHANGEME_grafana_password\n", id="changeme"),
        pytest.param('GRAFANA_PASSWORD="admin"\n', id="double-quoted-admin"),
        pytest.param("export GRAFANA_PASSWORD='admin' # compose default\n", id="exported-admin"),
        pytest.param(
            f"GRAFANA_PASSWORD={STRONG_VALUE}\nGRAFANA_PASSWORD=admin\n",
            id="last-assignment-wins",
        ),
    ],
)
def test_a_missing_or_publicly_known_password_is_replaced_proven_and_kept_unseen(
    sandbox: Sandbox, grafana_line: str,
) -> None:
    sandbox.write_env(grafana_line)
    owner_before = sandbox.env_file.stat()

    run = sandbox.run()

    fresh = _fresh_value(sandbox.env_text())
    fresh_line = f"GRAFANA_PASSWORD={fresh}\n"
    shadowed = "".join(grafana_line.splitlines(keepends=True)[:-1])
    expected = (
        LINES_BEFORE + shadowed + fresh_line + LINES_AFTER
        if grafana_line
        else LINES_BEFORE + LINES_AFTER + "\n" + fresh_line
    )
    assert (run.returncode, run.stdout, run.stderr) == (0, "set\n", "")
    assert sandbox.env_text() == expected
    owner_after = sandbox.env_file.stat()
    assert stat.S_IMODE(owner_after.st_mode) == ENV_MODE
    assert (owner_after.st_uid, owner_after.st_gid) == (owner_before.st_uid, owner_before.st_gid)
    assert run.docker_calls == [APPLY_ARGV, PORT_ARGV]
    assert run.docker_stdin == fresh + "\n"
    assert run.accepted_logins == 1
    assert not run.reveals(fresh)
    _assert_no_temp_file_left(sandbox)


@pytest.mark.parametrize(
    ("grafana_line", "kept"),
    [
        pytest.param(f"GRAFANA_PASSWORD={STRONG_VALUE}\n", STRONG_VALUE, id="unquoted"),
        pytest.param(
            f"GRAFANA_PASSWORD='{STRONG_VALUE}'  # rotated\n", STRONG_VALUE, id="single-quoted",
        ),
        # Compose keeps a single-quoted value literally, '$' included.
        pytest.param(
            f"GRAFANA_PASSWORD='{STRONG_VALUE}$x'\n", f"{STRONG_VALUE}$x",
            id="single-quoted-dollar",
        ),
        # Compose reads only the last assignment, so what it shadows may lie
        # outside the subset this command reads.
        pytest.param(
            f'GRAFANA_PASSWORD="Zq9$x"\nGRAFANA_PASSWORD={STRONG_VALUE}\n', STRONG_VALUE,
            id="shadowed-interpolation",
        ),
    ],
)
def test_a_strong_password_is_kept_applied_and_proven_unseen(
    sandbox: Sandbox, grafana_line: str, kept: str,
) -> None:
    original = sandbox.write_env(grafana_line)

    run = sandbox.run()

    assert (run.returncode, run.stdout, run.stderr) == (0, "already set\n", "")
    assert sandbox.env_text() == original
    assert run.docker_stdin == kept + "\n"
    assert run.accepted_logins == 1
    assert not run.reveals(kept)


def test_a_second_run_keeps_the_value_the_first_run_set_and_grafana_still_accepts_it(
    sandbox: Sandbox,
) -> None:
    sandbox.write_env("GRAFANA_PASSWORD=admin\n")
    assert sandbox.run().stdout == "set\n"
    after_first_run = sandbox.env_text()
    fresh = _fresh_value(after_first_run)

    second = sandbox.run()

    assert (second.returncode, second.stdout) == (0, "already set\n")
    assert sandbox.env_text() == after_first_run
    assert second.docker_stdin == fresh + "\n"
    assert second.accepted_logins == 1
    assert not second.reveals(fresh)


@pytest.mark.parametrize(
    ("apply", "failed_step"),
    [
        pytest.param(Apply.FAILS, "applying GRAFANA_PASSWORD", id="exit-1"),
        pytest.param(
            Apply.EXITS_ZERO_UNCONFIRMED, "did not confirm", id="exit-0-without-confirmation",
        ),
        pytest.param(
            Apply.CONFIRMS_WITHOUT_APPLYING, "API rejected", id="confirmed-but-not-applied",
        ),
        pytest.param(
            Apply.CONFIRMS_SOMETHING_ELSE, "did not confirm", id="confirmation-with-a-suffix",
        ),
    ],
)
@pytest.mark.parametrize(
    ("grafana_line", "env_state"),
    [
        pytest.param("GRAFANA_PASSWORD=admin\n", ".env now holds a fresh", id="fresh-value"),
        pytest.param(f"GRAFANA_PASSWORD={STRONG_VALUE}\n", ".env was not changed", id="kept-value"),
    ],
)
def test_an_apply_grafana_does_not_prove_fails_loud_with_a_generic_message(
    sandbox: Sandbox, apply: Apply, failed_step: str, grafana_line: str, env_state: str,
) -> None:
    sandbox.write_env(grafana_line)

    run = sandbox.run(apply)

    value = run.docker_stdin.rstrip("\n")
    assert (run.returncode, run.stdout) == (1, "")
    assert failed_step in run.stderr
    assert env_state in run.stderr
    assert "Error:" not in run.stderr, "Grafana's own output is never replayed"
    assert run.accepted_logins == 0
    assert not run.reveals(value)
    _assert_no_temp_file_left(sandbox)


def test_a_symlinked_env_is_refused_and_left_untouched(sandbox: Sandbox, tmp_path: Path) -> None:
    target = tmp_path / "real.env"
    target.write_text("GRAFANA_PASSWORD=admin\n")
    sandbox.env_file.symlink_to(target)

    run = sandbox.run()

    assert run.returncode == 1
    assert "is a symlink" in run.stderr
    assert sandbox.env_file.is_symlink()
    assert target.read_text() == "GRAFANA_PASSWORD=admin\n"
    assert run.docker_calls == []


def test_a_linked_worktree_is_refused_and_its_env_left_untouched(
    sandbox: Sandbox, tmp_path: Path,
) -> None:
    linked = tmp_path / "linked"
    sandbox.git("worktree", "add", "-q", str(linked))
    original = sandbox.write_env("GRAFANA_PASSWORD=admin\n", checkout=linked)

    run = sandbox.run(checkout=linked)

    assert run.returncode == 1
    assert "linked worktree" in run.stderr
    assert (linked / ".env").read_bytes().decode() == original
    assert run.docker_calls == []


@pytest.mark.parametrize(
    "grafana_line",
    [
        pytest.param('GRAFANA_PASSWORD="Zq9$x"\n', id="interpolation"),
        pytest.param("GRAFANA_PASSWORD='Zq9-x\n", id="unclosed-quote"),
        # Compose refuses the whole file over an unclosed quote, shadowed or not.
        pytest.param(
            f"GRAFANA_PASSWORD='Zq9-x\nGRAFANA_PASSWORD={STRONG_VALUE}\n",
            id="shadowed-unclosed-quote",
        ),
    ],
)
def test_a_value_compose_would_read_differently_is_refused_untouched(
    sandbox: Sandbox, grafana_line: str,
) -> None:
    original = sandbox.write_env(grafana_line)

    run = sandbox.run()

    assert run.returncode == 1
    assert "GRAFANA_PASSWORD" in run.stderr
    assert "Zq9" not in run.stderr
    assert sandbox.env_text() == original
    assert run.docker_calls == []


def test_a_missing_env_file_is_refused_without_creating_one(sandbox: Sandbox) -> None:
    run = sandbox.run()

    assert run.returncode == 1
    assert not sandbox.env_file.exists()
    assert run.docker_calls == []

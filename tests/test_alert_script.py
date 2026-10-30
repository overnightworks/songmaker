"""Behavioral tests for scripts/alert.sh, driven as a real subprocess.

No real mail is ever sent: a fake ``curl`` executable is placed first on
PATH and stands in for the real one, so these tests pin observable
behavior (exit code, stdout/stderr, what curl was invoked with) without
touching a network or reimplementing the script's own logic in Python.
"""

from __future__ import annotations

import base64
import shutil
import stat
import subprocess
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ALERT_SCRIPT = REPO_ROOT / "scripts" / "alert.sh"
ALERT_CONFIG_LIB = REPO_ROOT / "scripts" / "alert-config.sh"

VALID_ENV = {
    "ALERT_EMAIL_TO": "operator@example.com",
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": "587",
    "SMTP_USER": "songmaker@example.com",
    "SMTP_PASSWORD": "correct-horse-battery-staple",
}

# Passwords the shell reads as glob syntax (a bracket expression, an escaping
# backslash): a redaction that treats the password as a pattern instead of as
# text leaves each of them readable.
GLOB_PASSWORDS = ["dummy[x]pw", "digits[0-9]pw", "back\\slash"]


def _write_env_file(path: Path, values: dict[str, str]) -> Path:
    """Write a .env the way an operator has to write one.

    Values are single-quoted: that is the one quoting both readers of this
    file agree on — the shell that sources it here and the dotenv parser
    the app itself uses — and it is what docker/.env.docker.example tells the
    operator to do for a value carrying spaces or shell characters.
    """
    env_file = path / ".env"
    for value in values.values():
        assert "'" not in value, "a single quote in .env has no portable spelling"
    env_file.write_text(
        "".join(f"{key}='{value}'\n" for key, value in values.items()),
    )
    return env_file


def _install_fake_curl(bin_dir: Path, exit_code: int = 0, error_message: str = "") -> Path:
    """Stand in for curl, recording what alert.sh handed it.

    FAKE_CURL_FORWARD_CONFIG_TO_URL hands the --config alert.sh built to the
    real curl (FAKE_CURL_REAL_CURL) and has it fetch that URL, so the
    credentials travel through exactly the transport alert.sh uses.
    FAKE_CURL_UNREAD_CONFIG makes the fake exit without ever reading it.
    """
    bin_dir.mkdir(exist_ok=True)
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        'echo "$@" >> "${FAKE_CURL_ARGS_FILE:-/dev/null}"\n'
        'env >> "${FAKE_CURL_ENV_FILE:-/dev/null}"\n'
        'CONFIG_PATH=""\n'
        'PREVIOUS_ARG=""\n'
        'for ARG in "$@"; do\n'
        '    if [[ "$PREVIOUS_ARG" == "--config" ]]; then\n'
        '        CONFIG_PATH="$ARG"\n'
        "    fi\n"
        '    PREVIOUS_ARG="$ARG"\n'
        "done\n"
        'if [[ -n "${FAKE_CURL_FORWARD_CONFIG_TO_URL:-}" ]]; then\n'
        '    exec "$FAKE_CURL_REAL_CURL" --silent --show-error --fail --basic \\\n'
        '        --config "$CONFIG_PATH" --url "$FAKE_CURL_FORWARD_CONFIG_TO_URL"\n'
        "fi\n"
        'if [[ -n "$CONFIG_PATH" && -z "${FAKE_CURL_UNREAD_CONFIG:-}" ]]; then\n'
        '    cat "$CONFIG_PATH" >> "${FAKE_CURL_CONFIG_FILE:-/dev/null}"\n'
        "fi\n"
        'if [[ -n "${FAKE_CURL_CAPTURE_STDIN_FILE:-}" ]]; then\n'
        '    cat > "$FAKE_CURL_CAPTURE_STDIN_FILE"\n'
        "else\n"
        "    cat > /dev/null\n"
        "fi\n"
        f'if [[ "{exit_code}" != "0" ]]; then\n'
        f'    echo "{error_message}"\n'
        f"    exit {exit_code}\n"
        "fi\n"
        "exit 0\n",
    )
    fake_curl.chmod(fake_curl.stat().st_mode | stat.S_IEXEC)
    return fake_curl


def _run_alert(
    tmp_path: Path,
    args: list[str],
    env_values: dict[str, str] | None,
    fake_curl_exit_code: int = 0,
    fake_curl_error_message: str = "",
    extra_env: dict[str, str] | None = None,
    script: Path = ALERT_SCRIPT,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    _install_fake_curl(bin_dir, fake_curl_exit_code, fake_curl_error_message)

    env: dict[str, str] = {"PATH": f"{bin_dir}:/usr/bin:/bin"}
    if env_values is not None:
        env_file = _write_env_file(tmp_path, env_values)
        env["SONGMAKER_ALERT_ENV_FILE"] = str(env_file)
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        [str(script), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


def _alert_script_whose_credentials_producer_is(tmp_path: Path, producer_body: str) -> Path:
    """A copy of alert.sh whose curl_credentials_config runs ``producer_body``."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    shutil.copy(ALERT_CONFIG_LIB, scripts_dir)
    with (scripts_dir / ALERT_CONFIG_LIB.name).open("a") as config_lib:
        config_lib.write(f"\ncurl_credentials_config() {{\n    {producer_body}\n}}\n")
    return Path(shutil.copy(ALERT_SCRIPT, scripts_dir))


def test_sends_mail_via_curl_on_success(tmp_path: Path) -> None:
    args_file = tmp_path / "curl-args.txt"
    stdin_file = tmp_path / "curl-stdin.txt"

    result = _run_alert(
        tmp_path,
        ["GPU worker offline", "acestep-worker-0 has not reported in 10 minutes."],
        VALID_ENV,
        extra_env={
            "FAKE_CURL_ARGS_FILE": str(args_file),
            "FAKE_CURL_CAPTURE_STDIN_FILE": str(stdin_file),
        },
    )

    assert result.returncode == 0
    assert "sent" in result.stdout
    assert VALID_ENV["ALERT_EMAIL_TO"] in result.stdout

    curl_args = args_file.read_text()
    assert VALID_ENV["SMTP_HOST"] in curl_args
    assert VALID_ENV["SMTP_PORT"] in curl_args
    assert VALID_ENV["ALERT_EMAIL_TO"] in curl_args

    message = stdin_file.read_text()
    assert "Subject: GPU worker offline" in message
    assert "acestep-worker-0 has not reported in 10 minutes." in message


def test_missing_env_file_fails_loud(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(ALERT_SCRIPT), "subject", "body"],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "SONGMAKER_ALERT_ENV_FILE": str(tmp_path / "does-not-exist.env"),
        },
        timeout=10,
    )

    assert result.returncode != 0
    assert ".env" in result.stderr


@pytest.mark.parametrize("missing_key", sorted(VALID_ENV))
def test_missing_config_value_fails_loud_and_named(tmp_path: Path, missing_key: str) -> None:
    incomplete_env = {k: v for k, v in VALID_ENV.items() if k != missing_key}

    result = _run_alert(
        tmp_path,
        ["subject", "body"],
        incomplete_env,
    )

    assert result.returncode != 0
    assert missing_key in result.stderr
    assert "refusing" in result.stderr


def test_smtp_failure_reports_named_error_without_sending(tmp_path: Path) -> None:
    result = _run_alert(
        tmp_path,
        ["subject", "body"],
        VALID_ENV,
        fake_curl_exit_code=35,
        fake_curl_error_message="curl: (35) SSL connect error",
    )

    assert result.returncode != 0
    assert "SMTP send" in result.stderr
    assert "failed" in result.stderr
    assert "curl: (35) SSL connect error" in result.stderr
    assert "sent" not in result.stdout


@pytest.mark.parametrize("password", [VALID_ENV["SMTP_PASSWORD"], *GLOB_PASSWORDS])
def test_smtp_failure_never_leaks_password_in_output(tmp_path: Path, password: str) -> None:
    result = _run_alert(
        tmp_path,
        ["subject", "body"],
        {**VALID_ENV, "SMTP_PASSWORD": password},
        fake_curl_exit_code=1,
        fake_curl_error_message=f"auth rejected for password {password}",
    )

    assert result.returncode != 0
    assert password not in result.stderr
    assert password not in result.stdout
    assert "[REDACTED]" in result.stderr


def test_wrong_argument_count_fails_with_usage(tmp_path: Path) -> None:
    result = _run_alert(tmp_path, ["only-one-arg"], VALID_ENV)

    assert result.returncode != 0
    assert "usage" in result.stderr


# The generated app passwords this channel is configured with routinely
# carry characters that a naive substitution or an unquoted argument
# mangles — and a mangled credential only shows up when the first real
# alert tries to send.
AWKWARD_PASSWORDS = [
    "p&ss w0rd",
    "back\\slash",
    'quote"and|pipe',
    "hash#and space",
]


@pytest.mark.parametrize("password", AWKWARD_PASSWORDS)
def test_password_reaches_curl_off_the_command_line(tmp_path: Path, password: str) -> None:
    args_file = tmp_path / "curl-args.txt"
    config_file = tmp_path / "curl-config.txt"

    result = _run_alert(
        tmp_path,
        ["subject", "body"],
        {**VALID_ENV, "SMTP_PASSWORD": password},
        extra_env={
            "FAKE_CURL_ARGS_FILE": str(args_file),
            "FAKE_CURL_CONFIG_FILE": str(config_file),
        },
    )

    assert result.returncode == 0
    assert password not in args_file.read_text()
    assert config_file.read_text().strip() != ""


@pytest.fixture
def basic_auth_server() -> Iterator[tuple[str, dict[str, str]]]:
    """A loopback HTTP server; its URL and the credentials the last request sent."""
    received: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler protocol
            authorization = self.headers.get("Authorization", "")
            received["credentials"] = base64.b64decode(
                authorization.removeprefix("Basic "),
            ).decode()
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/", received
    finally:
        server.shutdown()


@pytest.mark.parametrize("password", AWKWARD_PASSWORDS)
def test_curl_reads_back_the_exact_credentials(
    tmp_path: Path,
    password: str,
    basic_auth_server: tuple[str, dict[str, str]],
) -> None:
    """The credentials alert.sh sends, parsed by the real curl.

    alert.sh itself runs and builds its --config; the fake curl passes that
    exact --config on to the real curl, which fetches a loopback server. What
    arrives there must be the byte-for-byte user and password, whatever the
    password contains.
    """
    server_url, received = basic_auth_server
    real_curl = shutil.which("curl")
    assert real_curl, "the real curl is needed to prove how it reads alert.sh's credentials"

    result = _run_alert(
        tmp_path,
        ["subject", "body"],
        {**VALID_ENV, "SMTP_PASSWORD": password},
        extra_env={
            "FAKE_CURL_FORWARD_CONFIG_TO_URL": server_url,
            "FAKE_CURL_REAL_CURL": real_curl,
        },
    )

    assert result.returncode == 0, result.stderr
    assert received["credentials"] == f"{VALID_ENV['SMTP_USER']}:{password}"


@pytest.mark.parametrize(
    "producer_body",
    ["return 23", 'kill -PIPE "$BASHPID"'],
    ids=["exits-with-status-23", "killed-by-sigpipe"],
)
def test_failing_credentials_producer_never_reports_sent(
    tmp_path: Path,
    producer_body: str,
) -> None:
    args_file = tmp_path / "curl-args.txt"

    result = _run_alert(
        tmp_path,
        ["subject", "body"],
        VALID_ENV,
        extra_env={"FAKE_CURL_ARGS_FILE": str(args_file)},
        script=_alert_script_whose_credentials_producer_is(tmp_path, producer_body),
    )

    assert result.returncode != 0
    assert "sent" not in result.stdout
    assert "credentials" in result.stderr
    assert not args_file.exists(), "curl must not start without its credentials"


def _assert_failed_with_reason_and_no_credentials(
    result: subprocess.CompletedProcess[str],
    password: str,
    recorded_files: list[Path],
) -> None:
    assert result.returncode != 0
    assert "sent" not in result.stdout
    assert password not in result.stderr
    assert password not in result.stdout
    for recorded in recorded_files:
        assert password not in recorded.read_text()


def test_silent_curl_failure_names_curl_and_its_status(tmp_path: Path) -> None:
    args_file = tmp_path / "curl-args.txt"
    env_file = tmp_path / "curl-env.txt"

    result = _run_alert(
        tmp_path,
        ["subject", "body"],
        VALID_ENV,
        fake_curl_exit_code=35,
        extra_env={"FAKE_CURL_ARGS_FILE": str(args_file), "FAKE_CURL_ENV_FILE": str(env_file)},
    )

    _assert_failed_with_reason_and_no_credentials(
        result,
        VALID_ENV["SMTP_PASSWORD"],
        [args_file, env_file],
    )
    assert "curl exit 35" in result.stderr


def test_failed_credential_write_names_the_write_and_its_status(tmp_path: Path) -> None:
    # Larger than a pipe holds, so the write fails once curl exits unread.
    password_larger_than_a_pipe_buffer = "SENTINEL" + "x" * 200_000
    args_file = tmp_path / "curl-args.txt"
    env_file = tmp_path / "curl-env.txt"

    result = _run_alert(
        tmp_path,
        ["subject", "body"],
        {**VALID_ENV, "SMTP_PASSWORD": password_larger_than_a_pipe_buffer},
        extra_env={
            "FAKE_CURL_UNREAD_CONFIG": "1",
            "FAKE_CURL_ARGS_FILE": str(args_file),
            "FAKE_CURL_ENV_FILE": str(env_file),
        },
    )

    _assert_failed_with_reason_and_no_credentials(
        result,
        password_larger_than_a_pipe_buffer,
        [args_file, env_file],
    )
    assert "curl exit 0, credential write exit" in result.stderr
    assert "credential write exit 0" not in result.stderr


def test_env_file_is_not_exported_into_curls_environment(tmp_path: Path) -> None:
    env_file = tmp_path / "curl-env.txt"

    result = _run_alert(
        tmp_path,
        ["subject", "body"],
        {**VALID_ENV, "POSTGRES_PASSWORD": "every-other-secret-in-dot-env"},
        extra_env={"FAKE_CURL_ENV_FILE": str(env_file)},
    )

    assert result.returncode == 0
    curl_environment = env_file.read_text()
    assert "every-other-secret-in-dot-env" not in curl_environment
    assert VALID_ENV["SMTP_PASSWORD"] not in curl_environment


@pytest.mark.parametrize(
    ("trace_flags", "shellopts", "separate_trace", "outcome"),
    [
        pytest.param(trace_flags, shellopts, separate_trace, outcome, id=f"{channel}-{outcome}")
        for channel, trace_flags, shellopts, separate_trace in [
            ("bash-x", ["-x"], "", False),
            ("inherited-xtrace", [], "xtrace", False),
            ("bash-v", ["-v"], "", False),
            ("inherited-verbose", [], "verbose", False),
            ("trace-fd", ["-x"], "", True),
        ]
        for outcome in ["sent", "smtp-failure", "missing-key", "journal"]
        # Bash disables verbose mode inside the journal's command substitution.
        if outcome != "journal" or channel not in {"bash-v", "inherited-verbose"}
    ],
)
def test_trace_channels_never_expose_config_values(
    tmp_path: Path,
    trace_flags: list[str],
    shellopts: str,
    separate_trace: bool,
    outcome: str,
) -> None:
    """1301-F12-TRACE: active tracing stays secret-free through send and load failure."""
    values = {**VALID_ENV, "SMTP_PASSWORD": "SENTINELPW", "OTHER": "SENTINELOTHER"}
    if outcome in {"missing-key", "journal"}:
        del values["SMTP_PORT"]
    env_file = _write_env_file(tmp_path, values)
    bin_dir = tmp_path / "bin"
    args_file = tmp_path / "curl-args.txt"
    _install_fake_curl(
        bin_dir,
        exit_code=35 if outcome == "smtp-failure" else 0,
        error_message="auth rejected for SENTINELPW",
    )
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "SONGMAKER_ALERT_ENV_FILE": str(env_file),
        "FAKE_CURL_ARGS_FILE": str(args_file),
    }
    if shellopts:
        env["SHELLOPTS"] = shellopts
    driver = tmp_path / "driver.sh"
    if outcome == "journal":
        # Same subshell/error-capture boundary as auto-deploy's alert guard.
        driver.write_text(
            ": TRACE_CONTROL\n"
            'if ! ALERT_CONFIG_ERROR="$( (\n'
            '    source "$1"\n'
            '    load_alert_config "$2"\n'
            ') 2>&1 )"; then\n'
            '    printf "journal: %s\\n" "$ALERT_CONFIG_ERROR" >&2\n'
            "    exit 1\n"
            "fi\n",
        )
        args = [str(ALERT_CONFIG_LIB), str(env_file)]
    else:
        driver.write_text(': TRACE_CONTROL\nsource "$1" subject body\n')
        args = [str(ALERT_SCRIPT)]
    trace_file = tmp_path / "trace.txt"
    with trace_file.open("w") as trace:
        if separate_trace:
            env["BASH_XTRACEFD"] = str(trace.fileno())
        result = subprocess.run(
            ["bash", *trace_flags, str(driver), *args],
            capture_output=True,
            text=True,
            env=env,
            pass_fds=(trace.fileno(),) if separate_trace else (),
            timeout=10,
        )
    trace_output = trace_file.read_text()
    assert "TRACE_CONTROL" in (trace_output if separate_trace else result.stderr)
    for output in (result.stdout, result.stderr, trace_output):
        assert "SENTINELPW" not in output
        assert "SENTINELOTHER" not in output
    if outcome == "sent":
        assert result.returncode == 0
        assert "sent" in result.stdout
        assert args_file.exists()
    else:
        assert result.returncode != 0
        assert "sent" not in result.stdout
        if outcome == "smtp-failure":
            assert "[REDACTED]" in result.stderr
            assert args_file.exists()
        else:
            assert "SMTP_PORT" in result.stderr
            assert not args_file.exists()
            if outcome == "journal":
                assert "journal:" in result.stderr

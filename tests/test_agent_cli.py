"""Tests for bounded probes of mounted agent CLIs."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from unittest.mock import patch

import pytest

from songmaker_cli.agent_cli import (
    AgentCliUnavailableError,
    CachedProbe,
    CliProbeBudgetExceeded,
    CliRun,
    _cli_output,
    claude_cli_login,
    clear_agent_cli_caches,
    codex_cli_login,
    grok_cli_status,
    run_cli,
    scrubbed_env,
)
from songmaker_cli.constants import (
    CLAUDE_CLI_AUTH_METHOD_FIELD,
    CLAUDE_CLI_LOGGED_IN_FIELD,
    CLI_OUTPUT_READ_LIMIT_BYTES,
    SECRET_ENV_KEYS,
)

GROK_LOGGED_IN = """You are logged in with grok.com.

Available models:
  * grok-4.6 (default)
  - grok-4.5
  - deepseek-v4-flash
"""
GROK_LOGGED_OUT = """You are not authenticated.

Available models:
  * grok-4.6 (default)
"""
CODEX_LOGGED_IN = "Logged in using ChatGPT"
CODEX_LOGGED_OUT = "Not logged in"


@pytest.fixture(autouse=True)
def _clear_probe_caches():
    clear_agent_cli_caches()
    yield
    clear_agent_cli_caches()


def _a_cli_that_says(output: str | None):
    return patch("songmaker_cli.agent_cli._cli_output", return_value=output)


def _a_claude_cli_that_says(output: str | None):
    return patch("songmaker_cli.agent_cli._claude_output", return_value=output)


def _a_shell_pretending_to_be_a_cli():
    return patch("songmaker_cli.agent_cli.shutil.which", return_value="/bin/sh")


def test_claude_reports_the_account_its_json_status_names() -> None:
    payload = json.dumps({
        CLAUDE_CLI_LOGGED_IN_FIELD: True,
        CLAUDE_CLI_AUTH_METHOD_FIELD: "claude.ai",
    })
    with _a_claude_cli_that_says(payload):
        login = claude_cli_login("/mounted/claude")

    assert login.logged_in is True
    assert login.auth_method == "claude.ai"


@pytest.mark.parametrize("output", (None, "not-json", "{}"))
def test_claude_without_a_parseable_status_is_logged_out(output: str | None) -> None:
    with _a_claude_cli_that_says(output):
        login = claude_cli_login("/mounted/claude")

    assert login.logged_in is False
    assert login.auth_method is None


def test_a_claude_probe_that_exceeds_its_caller_budget_is_logged_out(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()

    def _hanging_output(_binary: str) -> str | None:
        started.set()
        release.wait(timeout=1)
        return None

    monkeypatch.setattr("songmaker_cli.agent_cli._claude_output", _hanging_output)
    monkeypatch.setattr("songmaker_cli.agent_cli.CLI_PROBE_CALLER_TIMEOUT_SECONDS", 0.05)
    try:
        login = claude_cli_login("/mounted/claude")
    finally:
        release.set()

    assert started.is_set()
    assert login.logged_in is False


def test_grok_reports_the_account_it_is_signed_in_with() -> None:
    with _a_cli_that_says(GROK_LOGGED_IN):
        status = grok_cli_status()

    assert status.login.logged_in is True
    assert status.login.auth_method == "grok.com"


def test_grok_lists_the_models_under_its_login() -> None:
    with _a_cli_that_says(GROK_LOGGED_IN):
        status = grok_cli_status()

    assert status.model_names == ("grok-4.6", "grok-4.5", "deepseek-v4-flash")


def test_grok_without_a_login_reports_no_models_even_though_it_prints_some() -> None:
    with _a_cli_that_says(GROK_LOGGED_OUT):
        status = grok_cli_status()

    assert status.login.logged_in is False
    assert status.model_names == ()


def test_grok_that_cannot_be_asked_counts_as_logged_out() -> None:
    with _a_cli_that_says(None):
        assert grok_cli_status().login.logged_in is False


def test_grok_answering_in_words_we_do_not_know_raises() -> None:
    with _a_cli_that_says("Session ready.\n"), pytest.raises(
        AgentCliUnavailableError,
        match="login status",
    ):
        grok_cli_status()


def test_grok_that_is_signed_in_but_lists_nothing_raises() -> None:
    with _a_cli_that_says("You are logged in with grok.com.\n"), pytest.raises(
        AgentCliUnavailableError,
        match="model name",
    ):
        grok_cli_status()


def test_codex_reports_the_account_it_is_signed_in_with() -> None:
    with _a_cli_that_says(CODEX_LOGGED_IN):
        login = codex_cli_login()

    assert login.logged_in is True
    assert login.auth_method == "ChatGPT"


def test_codex_without_a_login_is_logged_out() -> None:
    with _a_cli_that_says(CODEX_LOGGED_OUT):
        login = codex_cli_login()

    assert login.logged_in is False
    assert login.auth_method is None


def test_codex_that_cannot_be_asked_counts_as_logged_out() -> None:
    with _a_cli_that_says(None):
        assert codex_cli_login().logged_in is False


def test_codex_answering_in_words_we_do_not_know_raises() -> None:
    with _a_cli_that_says("auth: unknown"), pytest.raises(
        AgentCliUnavailableError,
        match="login status",
    ):
        codex_cli_login()


@pytest.mark.parametrize(
    ("ask", "answer"),
    [(grok_cli_status, GROK_LOGGED_IN), (codex_cli_login, CODEX_LOGGED_IN)],
)
def test_a_second_ask_reuses_the_recent_answer(ask, answer) -> None:
    with _a_cli_that_says(answer) as spawn:
        first = ask()
        second = ask()

    assert first == second
    spawn.assert_called_once()


def test_a_second_claude_ask_reuses_the_recent_answer() -> None:
    with _a_claude_cli_that_says("{}") as spawn:
        first = claude_cli_login("/mounted/claude")
        second = claude_cli_login("/mounted/claude")

    assert first == second
    spawn.assert_called_once()


def test_expired_cache_asks_the_cli_again() -> None:
    with (
        _a_cli_that_says(CODEX_LOGGED_IN) as spawn,
        patch("songmaker_cli.agent_cli.CLI_LOGIN_STATUS_CACHE_SECONDS", 0),
    ):
        codex_cli_login()
        codex_cli_login()

    assert spawn.call_count == 2


def test_a_cli_we_cannot_read_is_not_re_asked_on_every_request() -> None:
    with _a_cli_that_says("nonsense the parser does not know") as spawn:
        for _ in range(3):
            with pytest.raises(AgentCliUnavailableError):
                grok_cli_status()

    spawn.assert_called_once()


def test_parallel_cold_asks_spawn_the_cli_once() -> None:
    started = threading.Event()
    release = threading.Event()
    answers: list[str] = []

    def probe() -> str:
        started.set()
        release.wait()
        return "answer"

    cached = CachedProbe(probe)
    first = threading.Thread(target=lambda: answers.append(cached.get()))
    second = threading.Thread(target=lambda: answers.append(cached.get()))
    first.start()
    assert started.wait(timeout=1)
    second.start()
    assert second.is_alive()
    release.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert answers == ["answer", "answer"]


def test_parallel_cold_asks_share_one_failure() -> None:
    started = threading.Event()
    release = threading.Event()
    failures: list[Exception] = []

    def probe() -> str:
        started.set()
        release.wait()
        raise AgentCliUnavailableError("bad answer")

    cached = CachedProbe(probe)

    def ask() -> None:
        with pytest.raises(AgentCliUnavailableError) as raised:
            cached.get()
        failures.append(raised.value)

    first = threading.Thread(target=ask)
    second = threading.Thread(target=ask)
    first.start()
    assert started.wait(timeout=1)
    second.start()
    assert second.is_alive()
    release.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert len(failures) == 2
    assert failures[0] is failures[1]


def test_a_follower_waits_only_its_own_single_flight_budget(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()

    def probe() -> str:
        started.set()
        release.wait()
        return "answer"

    cached = CachedProbe(probe)
    monkeypatch.setattr("songmaker_cli.agent_cli.CLI_PROBE_CALLER_TIMEOUT_SECONDS", 0.05)

    def first_ask() -> None:
        try:
            cached.get()
        except CliProbeBudgetExceeded:
            pass

    first = threading.Thread(target=first_ask)
    first.start()
    assert started.wait(timeout=1)

    started_waiting = time.monotonic()
    with pytest.raises(CliProbeBudgetExceeded, match="caller budget"):
        cached.get()
    assert time.monotonic() - started_waiting < 0.2

    release.set()
    first.join(timeout=1)
    assert not first.is_alive()
    assert cached.get() == "answer"


def test_run_cli_returns_after_its_answer_budget_and_cleanup_grace(monkeypatch) -> None:
    answer_budget = 0.05
    cleanup_grace = 0.05
    monkeypatch.setattr("songmaker_cli.agent_cli.COWRITER_MODELS_TIMEOUT_SECONDS", answer_budget)
    monkeypatch.setattr("songmaker_cli.agent_cli.CLI_TERMINATION_GRACE_SECONDS", cleanup_grace)

    started_at = time.monotonic()
    run = run_cli("/bin/sh", ("-c", "trap '' TERM; while :; do :; done"))
    elapsed = time.monotonic() - started_at

    assert run is not None
    assert run.complete is False
    assert elapsed < answer_budget + (2 * cleanup_grace) + 0.15


def test_clearing_a_probe_does_not_restore_its_pre_clear_result() -> None:
    started = threading.Event()
    release = threading.Event()
    results = iter(("before clear", "after clear"))

    def probe() -> str:
        started.set()
        release.wait(timeout=1)
        return next(results)

    cached = CachedProbe(probe)
    first_answer: list[str] = []
    first = threading.Thread(target=lambda: first_answer.append(cached.get()))
    first.start()
    assert started.wait(timeout=1)

    cached.clear()
    release.set()
    first.join(timeout=1)

    assert first_answer == ["before clear"]
    assert cached.get() == "after clear"


def test_a_cli_that_floods_us_is_read_only_up_to_the_limit() -> None:
    flood = "while :; do printf x; done"
    with _a_shell_pretending_to_be_a_cli():
        run = run_cli("/bin/sh", ("-c", flood))

    assert run is not None
    assert run.complete is False
    assert len(run.stdout) + len(run.stderr) <= CLI_OUTPUT_READ_LIMIT_BYTES


def test_a_cli_that_never_answers_is_given_up_on() -> None:
    with (
        _a_shell_pretending_to_be_a_cli(),
        patch("songmaker_cli.agent_cli.COWRITER_MODELS_TIMEOUT_SECONDS", 0.2),
    ):
        assert _cli_output("grok", ("-c", "while :; do :; done")) is None


def test_a_cli_that_leaves_a_child_behind_is_terminated_with_its_group() -> None:
    command = "{ while :; do :; done; } & wait"
    started: list[subprocess.Popen[bytes]] = []
    real_popen = subprocess.Popen

    def capture_process(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        started.append(process)
        return process

    with (
        _a_shell_pretending_to_be_a_cli(),
        patch("songmaker_cli.agent_cli.COWRITER_MODELS_TIMEOUT_SECONDS", 0.2),
        patch("songmaker_cli.agent_cli.subprocess.Popen", side_effect=capture_process),
    ):
        assert _cli_output("grok", ("-c", command)) is None

    assert started
    with pytest.raises(ProcessLookupError):
        os.killpg(started[0].pid, 0)


def test_a_sigterm_ignoring_cli_and_child_are_reaped_after_sigkill() -> None:
    command = "trap '' TERM; { trap '' TERM; while :; do :; done; } & while :; do :; done"
    started: list[subprocess.Popen[bytes]] = []
    real_popen = subprocess.Popen

    def capture_process(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        started.append(process)
        return process

    with (
        _a_shell_pretending_to_be_a_cli(),
        patch("songmaker_cli.agent_cli.COWRITER_MODELS_TIMEOUT_SECONDS", 0.05),
        patch("songmaker_cli.agent_cli.CLI_TERMINATION_GRACE_SECONDS", 0.1),
        patch("songmaker_cli.agent_cli.subprocess.Popen", side_effect=capture_process),
    ):
        assert _cli_output("grok", ("-c", command)) is None

    assert started[0].poll() is not None
    with pytest.raises(ProcessLookupError):
        os.killpg(started[0].pid, 0)


def test_a_spawn_that_returns_after_its_deadline_is_reaped() -> None:
    release_spawn = threading.Event()
    spawned = threading.Event()
    started: list[subprocess.Popen[bytes]] = []
    real_popen = subprocess.Popen

    def late_process(*args, **kwargs):
        release_spawn.wait()
        process = real_popen(*args, **kwargs)
        started.append(process)
        spawned.set()
        return process

    with (
        patch("songmaker_cli.agent_cli.COWRITER_MODELS_TIMEOUT_SECONDS", 0.1),
        patch("songmaker_cli.agent_cli.subprocess.Popen", side_effect=late_process),
    ):
        assert run_cli("/bin/sh", ("-c", "while :; do :; done")) is None
        release_spawn.set()
        assert spawned.wait(timeout=1)
        started[0].wait(timeout=1)

    with pytest.raises(ProcessLookupError):
        os.killpg(started[0].pid, 0)


@pytest.mark.parametrize(
    "run",
    [
        CliRun(returncode=1, stdout=CODEX_LOGGED_IN, stderr="", complete=True),
        CliRun(returncode=0, stdout=CODEX_LOGGED_IN, stderr="", complete=False),
    ],
)
def test_an_incomplete_or_failed_run_is_not_accepted_as_authenticated(run: CliRun) -> None:
    with patch("songmaker_cli.agent_cli.run_cli", return_value=run):
        login = codex_cli_login()

    assert login.logged_in is False


def test_claude_parses_only_stdout() -> None:
    stdout = json.dumps({CLAUDE_CLI_LOGGED_IN_FIELD: True})
    stderr = json.dumps({CLAUDE_CLI_LOGGED_IN_FIELD: False})
    run = CliRun(returncode=0, stdout=stdout, stderr=stderr, complete=True)
    with patch("songmaker_cli.agent_cli.run_cli", return_value=run):
        login = claude_cli_login("/mounted/claude")

    assert login.logged_in is True


@pytest.mark.parametrize(
    "run",
    [
        CliRun(returncode=1, stdout="{}", stderr="", complete=True),
        CliRun(returncode=0, stdout="{}", stderr="", complete=False),
    ],
)
def test_claude_does_not_accept_a_failed_or_incomplete_run(run: CliRun) -> None:
    with patch("songmaker_cli.agent_cli.run_cli", return_value=run):
        login = claude_cli_login("/mounted/claude")

    assert login.logged_in is False


def test_a_cli_that_is_not_installed_cannot_be_asked() -> None:
    with patch("songmaker_cli.agent_cli.shutil.which", return_value=None):
        assert _cli_output("grok", ("models",)) is None


def test_a_spawned_cli_never_sees_our_secrets(monkeypatch) -> None:
    for key in SECRET_ENV_KEYS:
        monkeypatch.setenv(key, "leaked-value")

    env = scrubbed_env()

    assert not [key for key in SECRET_ENV_KEYS if key in env]

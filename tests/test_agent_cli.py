"""Tests for bounded probes of mounted agent CLIs."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from unittest.mock import patch

import pytest

from songmaker_cli import agent_cli
from songmaker_cli.agent_cli import (
    CODEX_CLI_CREDENTIALS_INVALID_DETAIL,
    GROK_CLI_CREDENTIALS_INVALID_DETAIL,
    AgentCliUnavailableError,
    CachedProbe,
    CliLineChannel,
    CliProbeBudgetExceeded,
    CliRun,
    CliRunOutcome,
    CliRunReason,
    _cli_output,
    claude_cli_login,
    clear_agent_cli_caches,
    codex_cli_login,
    grok_cli_status,
    run_cli,
    run_cli_bounded,
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
    probe_calls = 0

    def probe() -> str:
        nonlocal probe_calls
        probe_calls += 1
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
    assert probe_calls == 1


def test_parallel_cold_asks_share_one_failure(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()
    follower_paused_after_miss = threading.Event()
    resume_follower = threading.Event()
    failures: list[Exception] = []
    probe_calls = 0

    def probe() -> str:
        nonlocal probe_calls
        probe_calls += 1
        started.set()
        release.wait()
        raise AgentCliUnavailableError("bad answer")

    cached = CachedProbe(probe)

    def ask() -> None:
        with pytest.raises(AgentCliUnavailableError) as raised:
            cached.get()
        failures.append(raised.value)

    first = threading.Thread(
        target=ask,
        name="single-flight leader caller",
        daemon=True,
    )
    second = threading.Thread(
        target=ask,
        name="single-flight follower caller",
    )
    real_refresh = cached.refresh

    def pause_follower_after_cache_miss() -> str:
        if threading.current_thread() is second:
            follower_paused_after_miss.set()
            assert resume_follower.wait(timeout=1)
        return real_refresh()

    monkeypatch.setattr(cached, "refresh", pause_follower_after_cache_miss)

    first_started = False
    second_started = False
    try:
        first.start()
        first_started = True
        assert started.wait(timeout=1)
        second.start()
        second_started = True
        assert follower_paused_after_miss.wait(timeout=1)
        release.set()
        first.join(timeout=1)
        assert not first.is_alive()
        resume_follower.set()
    finally:
        release.set()
        resume_follower.set()
        if first_started:
            first.join(timeout=1)
            assert not first.is_alive()
        if second_started:
            second.join(timeout=1)
            assert not second.is_alive()

    assert len(failures) == 2
    assert failures[0] is failures[1]
    assert probe_calls == 1


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
    flood = "while :; do printf stdout; printf stderr >&2; done"
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
    reaped = threading.Event()
    started: list[subprocess.Popen[bytes]] = []
    real_popen = subprocess.Popen
    real_reap = agent_cli._reap_process_group

    def late_process(*args, **kwargs):
        release_spawn.wait()
        process = real_popen(*args, **kwargs)
        started.append(process)
        spawned.set()
        return process

    def capture_reap(process: subprocess.Popen[bytes]) -> bool:
        try:
            return real_reap(process)
        finally:
            reaped.set()

    with (
        patch("songmaker_cli.agent_cli.COWRITER_MODELS_TIMEOUT_SECONDS", 0.1),
        patch("songmaker_cli.agent_cli.subprocess.Popen", side_effect=late_process),
        patch("songmaker_cli.agent_cli._reap_process_group", side_effect=capture_reap),
    ):
        assert run_cli("/bin/sh", ("-c", "while :; do :; done")) is None
        release_spawn.set()
        assert spawned.wait(timeout=1)
        assert reaped.wait(timeout=1)

    with pytest.raises(ProcessLookupError):
        os.killpg(started[0].pid, 0)


def test_bounded_runner_returns_on_a_stalled_spawn_and_reaps_its_late_process() -> None:
    release_spawn = threading.Event()
    spawned = threading.Event()
    reaped = threading.Event()
    callbacks_reaped = threading.Event()
    started: list[subprocess.Popen[bytes]] = []
    spawned_process_ids: list[int] = []
    reaped_processes: list[tuple[int, bool]] = []
    real_popen = subprocess.Popen
    real_reap = agent_cli._reap_process_group

    def late_process(*args, **kwargs):
        release_spawn.wait()
        process = real_popen(*args, **kwargs)
        started.append(process)
        spawned.set()
        return process

    def capture_reap(process: subprocess.Popen[bytes]) -> bool:
        try:
            return real_reap(process)
        finally:
            reaped.set()

    def record_reaped(process_id: int, became_zombie: bool) -> None:
        reaped_processes.append((process_id, became_zombie))
        callbacks_reaped.set()

    with (
        patch("songmaker_cli.agent_cli.subprocess.Popen", side_effect=late_process),
        patch("songmaker_cli.agent_cli._reap_process_group", side_effect=capture_reap),
    ):
        deadline = time.monotonic() + 0.05
        assert run_cli_bounded(
            ("/bin/sh", "-c", "while :; do :; done"),
            stdin_payload=None,
            read="all",
            deadline=deadline,
            on_spawned=spawned_process_ids.append,
            on_reaped=record_reaped,
        ).reason is CliRunReason.DEADLINE_BEFORE_SPAWN
        release_spawn.set()
        assert spawned.wait(timeout=1)
        assert reaped.wait(timeout=1)
        assert callbacks_reaped.wait(timeout=1)

    assert spawned_process_ids == [started[0].pid]
    assert reaped_processes == [(started[0].pid, False)]
    with pytest.raises(ProcessLookupError):
        os.killpg(started[0].pid, 0)


def test_bounded_runner_reports_a_spawn_error() -> None:
    error = OSError("cannot start")
    spawned_process_ids: list[int] = []
    reaped_processes: list[tuple[int, bool]] = []
    with patch("songmaker_cli.agent_cli.subprocess.Popen", side_effect=error):
        outcome = run_cli_bounded(
            ("missing-cli",),
            stdin_payload=None,
            read="all",
            deadline=time.monotonic() + 1,
            on_spawned=spawned_process_ids.append,
            on_reaped=lambda process_id, became_zombie: reaped_processes.append(
                (process_id, became_zombie),
            ),
        )

    assert outcome.started is False
    assert outcome.spawn_error is error
    assert outcome.returncode is None
    assert outcome.reason is CliRunReason.SPAWN_FAILED
    assert spawned_process_ids == []
    assert reaped_processes == []


def test_bounded_runner_reports_a_non_os_spawn_error_immediately() -> None:
    error = ValueError("empty argv")
    spawned_process_ids: list[int] = []
    reaped_processes: list[tuple[int, bool]] = []
    deadline = time.monotonic() + 1

    with patch("songmaker_cli.agent_cli.subprocess.Popen", side_effect=error):
        outcome = run_cli_bounded(
            (),
            stdin_payload=None,
            read="all",
            deadline=deadline,
            on_spawned=spawned_process_ids.append,
            on_reaped=lambda process_id, became_zombie: reaped_processes.append(
                (process_id, became_zombie),
            ),
        )

    assert outcome.reason is CliRunReason.SPAWN_FAILED
    assert outcome.spawn_error is error
    assert time.monotonic() < deadline - 0.5
    assert spawned_process_ids == []
    assert reaped_processes == []


def test_bounded_runner_carries_an_output_io_error(monkeypatch) -> None:
    error = OSError("cannot switch stream mode")

    def fail_to_set_blocking(_fd: int, _value: bool) -> None:
        raise error

    monkeypatch.setattr("songmaker_cli.agent_cli.os.set_blocking", fail_to_set_blocking)

    outcome = run_cli_bounded(
        ("/bin/sh", "-c", "printf output"),
        stdin_payload=None,
        read="all",
        deadline=time.monotonic() + 1,
    )

    assert outcome.reason is CliRunReason.IO_ERROR
    assert outcome.io_error is error


def test_bounded_runner_reports_a_stdin_close_error_after_spawning(monkeypatch) -> None:
    error = OSError("cannot close stdin")
    spawned_process_ids: list[int] = []
    reaped_processes: list[tuple[int, bool]] = []

    def fail_to_close_stdin(_process: subprocess.Popen[bytes]) -> None:
        raise error

    def record_reaped(process_id: int, became_zombie: bool) -> None:
        reaped_processes.append((process_id, became_zombie))

    monkeypatch.setattr("songmaker_cli.agent_cli._close_stdin", fail_to_close_stdin)
    outcome = run_cli_bounded(
        ("/bin/sh", "-c", "exec sleep 10"),
        stdin_payload=None,
        read="all",
        deadline=time.monotonic() + 1,
        on_spawned=spawned_process_ids.append,
        on_reaped=record_reaped,
    )

    assert outcome.reason is CliRunReason.IO_ERROR
    assert outcome.io_error is error
    assert len(spawned_process_ids) == 1
    assert reaped_processes == [(spawned_process_ids[0], False)]


def test_bounded_runner_returns_when_its_cleanup_margin_expires(monkeypatch) -> None:
    release_cleanup = threading.Event()
    reaped = threading.Event()
    real_reap = agent_cli._reap_process_group

    def delayed_reap(process: subprocess.Popen[bytes]) -> bool:
        release_cleanup.wait(timeout=1)
        try:
            return real_reap(process)
        finally:
            reaped.set()

    monkeypatch.setattr("songmaker_cli.agent_cli._reap_process_group", delayed_reap)
    outcome = run_cli_bounded(
        ("/bin/sh", "-c", "exec sleep 10"),
        stdin_payload=None,
        read="all",
        deadline=time.monotonic() + 0.02,
        cleanup_margin_seconds=0.01,
    )

    assert outcome.reason is CliRunReason.CLEANUP_OVERRAN
    release_cleanup.set()
    assert reaped.wait(timeout=1)


def test_bounded_runner_notifies_a_zombie_reap_only_after_background_confirmation(
    monkeypatch,
) -> None:
    background_started = threading.Event()
    allow_background_reap = threading.Event()
    callback_finished = threading.Event()
    spawned_process_ids: list[int] = []
    callbacks: list[tuple[int, bool]] = []

    def await_background_reap(process, callback) -> None:
        background_started.set()
        assert allow_background_reap.wait(timeout=1)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        process.wait()
        agent_cli._notify_reaped(callback, process.pid, became_zombie=True)

    def record_reaped(process_id: int, became_zombie: bool) -> None:
        callbacks.append((process_id, became_zombie))
        callback_finished.set()

    monkeypatch.setattr("songmaker_cli.agent_cli._reap_process_group", lambda _process: True)
    monkeypatch.setattr("songmaker_cli.agent_cli._reap_in_background", await_background_reap)

    outcome = run_cli_bounded(
        ("/bin/sh", "-c", "printf ready"),
        stdin_payload=None,
        read="all",
        deadline=time.monotonic() + 1,
        on_spawned=spawned_process_ids.append,
        on_reaped=record_reaped,
    )

    assert outcome.became_zombie is True
    assert background_started.wait(timeout=1)
    assert callbacks == []
    allow_background_reap.set()
    assert callback_finished.wait(timeout=1)
    assert callbacks == [(spawned_process_ids[0], True)]


def test_bounded_runner_stops_a_cli_that_never_reads_its_full_stdin_pipe() -> None:
    started: list[subprocess.Popen[bytes]] = []
    real_popen = subprocess.Popen

    def capture_process(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        started.append(process)
        return process

    with patch("songmaker_cli.agent_cli.subprocess.Popen", side_effect=capture_process):
        outcome = run_cli_bounded(
            ("/bin/sh", "-c", "exec sleep 10"),
            stdin_payload=b"x" * (1024 * 1024),
            read="all",
            deadline=time.monotonic() + 0.05,
        )

    assert outcome is not None
    assert outcome.complete is False
    assert started[0].poll() is not None


def test_bounded_runner_stops_a_cli_that_never_writes_output() -> None:
    started: list[subprocess.Popen[bytes]] = []
    real_popen = subprocess.Popen

    def capture_process(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        started.append(process)
        return process

    with patch("songmaker_cli.agent_cli.subprocess.Popen", side_effect=capture_process):
        outcome = run_cli_bounded(
            ("/bin/sh", "-c", "exec sleep 10"),
            stdin_payload=None,
            read="all",
            deadline=time.monotonic() + 0.05,
        )

    assert outcome is not None
    assert outcome.complete is False
    assert started[0].poll() is not None


def test_bounded_runner_marks_an_unconfirmed_sigkill_as_a_zombie(monkeypatch) -> None:
    started: list[subprocess.Popen[bytes]] = []
    real_popen = subprocess.Popen

    def capture_process(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        started.append(process)
        return process

    monkeypatch.setattr(
        "songmaker_cli.agent_cli._wait_for_process_group_exit",
        lambda _process, _timeout: False,
    )
    monkeypatch.setattr("songmaker_cli.agent_cli.CLI_TERMINATION_GRACE_SECONDS", 0.01)
    with patch("songmaker_cli.agent_cli.subprocess.Popen", side_effect=capture_process):
        outcome = run_cli_bounded(
            ("/bin/sh", "-c", "trap '' TERM; while :; do :; done"),
            stdin_payload=None,
            read="all",
            deadline=time.monotonic() + 0.02,
        )

    assert outcome is not None
    assert outcome.became_zombie is True
    started[0].wait(timeout=1)


def test_run_cli_logs_a_sigkill_survivor_without_starting_a_background_reaper(
    monkeypatch, caplog,
) -> None:
    reaper_may_finish = threading.Event()
    threads_before = {thread.ident for thread in threading.enumerate()}
    monkeypatch.setattr(
        "songmaker_cli.agent_cli._wait_for_process_group_exit",
        lambda _process, _timeout: False,
    )
    monkeypatch.setattr(
        "songmaker_cli.agent_cli._process_group_exists",
        lambda _process_id: not reaper_may_finish.is_set(),
    )
    monkeypatch.setattr("songmaker_cli.agent_cli.CLI_TERMINATION_GRACE_SECONDS", 0.01)
    caplog.set_level("WARNING")

    try:
        run = run_cli("/bin/sh", ("-c", "printf ready"))
        threads_after = {thread.ident for thread in threading.enumerate()}
    finally:
        reaper_may_finish.set()

    assert run == CliRun(returncode=0, stdout="ready", stderr="", complete=True)
    assert threads_after == threads_before
    assert any("survived its SIGKILL grace period" in record.message for record in caplog.records)


def test_background_reap_notifies_when_process_group_check_fails(
    monkeypatch, caplog,
) -> None:
    process = subprocess.Popen(
        ("/bin/sh", "-c", "printf ready"),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    callbacks: list[tuple[int, bool]] = []
    error = OSError("cannot check process group")
    monkeypatch.setattr(
        "songmaker_cli.agent_cli._process_group_exists",
        lambda _process_id: (_ for _ in ()).throw(error),
    )
    caplog.set_level("ERROR")

    agent_cli._reap_in_background(
        process,
        lambda process_id, became_zombie: callbacks.append((process_id, became_zombie)),
    )
    process.communicate()

    assert callbacks == [(process.pid, True)]
    assert any(
        "background reap of agent CLI process group" in record.message
        for record in caplog.records
    )


def test_bounded_runner_stops_collecting_at_the_byte_limit(monkeypatch) -> None:
    monkeypatch.setattr("songmaker_cli.agent_cli.CLI_OUTPUT_READ_LIMIT_BYTES", 32)

    outcome = run_cli_bounded(
        ("/bin/sh", "-c", "while :; do printf x; done"),
        stdin_payload=None,
        read="all",
        deadline=time.monotonic() + 1,
    )

    assert outcome is not None
    assert outcome.complete is False
    assert len(outcome.stdout) + len(outcome.stderr) == 32


def test_run_cli_discards_partial_output_when_its_read_deadline_expires(monkeypatch) -> None:
    monkeypatch.setattr("songmaker_cli.agent_cli.COWRITER_MODELS_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr("songmaker_cli.agent_cli.CLI_TERMINATION_GRACE_SECONDS", 0.01)

    run = run_cli("/bin/sh", ("-c", "printf partial; exec sleep 10"))

    assert run == CliRun(returncode=-15, stdout="", stderr="", complete=False)


def test_run_cli_keeps_a_started_cli_result_when_cleanup_reports_a_zombie(monkeypatch) -> None:
    started: list[subprocess.Popen[bytes]] = []
    real_popen = subprocess.Popen

    def capture_process(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        started.append(process)
        return process

    monkeypatch.setattr("songmaker_cli.agent_cli.COWRITER_MODELS_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr("songmaker_cli.agent_cli.CLI_TERMINATION_GRACE_SECONDS", 0.01)
    monkeypatch.setattr(
        "songmaker_cli.agent_cli._wait_for_process_group_exit",
        lambda _process, _timeout: False,
    )
    with patch("songmaker_cli.agent_cli.subprocess.Popen", side_effect=capture_process):
        run = run_cli("/bin/sh", ("-c", "trap '' TERM; while :; do :; done"))

    assert run is not None
    assert run.complete is False
    started[0].wait(timeout=1)


def test_bounded_runner_delivers_stdin_without_a_blocking_write() -> None:
    outcome = run_cli_bounded(
        ("/bin/sh", "-c", "IFS= read -r line; printf '<%s>' \"$line\""),
        stdin_payload=b"delivered\n",
        read="all",
        deadline=time.monotonic() + 1,
    )

    assert outcome is not None
    assert outcome.complete is True
    assert outcome.stdout == "<delivered>"


def test_run_cli_closes_stdin_so_the_child_observes_eof() -> None:
    run = run_cli(
        "/bin/sh",
        ("-c", "if IFS= read -r line; then printf data; else printf eof; fi"),
    )

    assert run == CliRun(returncode=0, stdout="eof", stderr="", complete=True)


def test_bounded_runner_returns_only_the_first_stdout_line() -> None:
    outcome = run_cli_bounded(
        ("/bin/sh", "-c", "printf 'first\\nsecond\\n'; exec sleep 10"),
        stdin_payload=None,
        read="first_line",
        deadline=time.monotonic() + 1,
    )

    assert outcome is not None
    assert outcome.complete is True
    assert outcome.stdout == "first\n"


def test_bounded_runner_returns_the_last_stdout_bytes_at_eof_in_first_line_mode() -> None:
    outcome = run_cli_bounded(
        ("/bin/sh", "-c", "printf final"),
        stdin_payload=None,
        read="first_line",
        deadline=time.monotonic() + 1,
    )

    assert outcome is not None
    assert outcome.complete is True
    assert outcome.stdout == "final"


def test_bounded_runner_drains_both_output_streams_in_all_mode() -> None:
    outcome = run_cli_bounded(
        ("/bin/sh", "-c", "printf stdout; printf stderr >&2"),
        stdin_payload=None,
        read="all",
        deadline=time.monotonic() + 1,
    )

    assert outcome is not None
    assert outcome.complete is True
    assert outcome.stdout == "stdout"
    assert outcome.stderr == "stderr"


def test_bounded_runner_applies_its_byte_limit_to_both_streams(monkeypatch) -> None:
    monkeypatch.setattr("songmaker_cli.agent_cli.CLI_OUTPUT_READ_LIMIT_BYTES", 4)

    outcome = run_cli_bounded(
        ("/bin/sh", "-c", "printf 123; printf abc >&2"),
        stdin_payload=None,
        read="all",
        deadline=time.monotonic() + 1,
    )

    assert outcome.complete is False
    assert outcome.reason is CliRunReason.OUTPUT_LIMIT_REACHED
    assert len(outcome.stdout) + len(outcome.stderr) == 4


def test_bounded_runner_can_discard_stderr() -> None:
    outcome = run_cli_bounded(
        ("/bin/sh", "-c", "printf stdout; printf stderr >&2"),
        stdin_payload=None,
        read="all",
        deadline=time.monotonic() + 1,
        stderr="devnull",
    )

    assert outcome.complete is True
    assert outcome.stdout == "stdout"
    assert outcome.stderr == ""


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


def test_child_environment_additions_are_local_to_the_spawned_cli(monkeypatch) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)

    child_env = agent_cli._child_env({"CODEX_HOME": "/private/codex-home"})

    assert child_env["CODEX_HOME"] == "/private/codex-home"
    assert "CODEX_HOME" not in os.environ


def test_bounded_runner_can_unset_an_inherited_child_variable(monkeypatch) -> None:
    monkeypatch.setenv("GROK_HOME", "/outside/profile")

    outcome = run_cli_bounded(
        ("/bin/sh", "-c", 'test -z "${GROK_HOME+x}"'),
        stdin_payload=None,
        read="all",
        deadline=time.monotonic() + 1,
        unset_env=("GROK_HOME",),
    )

    assert outcome.complete is True
    assert outcome.returncode == 0


def test_bounded_runner_does_not_pass_secrets_to_the_spawned_cli(monkeypatch) -> None:
    for key in SECRET_ENV_KEYS:
        monkeypatch.setenv(key, "leaked-value")
    secret_checks = " && ".join(f'test -z "${{{key}}}"' for key in SECRET_ENV_KEYS)

    outcome = run_cli_bounded(
        ("/bin/sh", "-c", secret_checks),
        stdin_payload=None,
        read="all",
        deadline=time.monotonic() + 1,
    )

    assert outcome.complete is True
    assert outcome.returncode == 0


def test_bounded_runner_sends_complete_stdout_lines_and_then_its_outcome() -> None:
    channel = CliLineChannel(maximum_lines=2)

    outcome = run_cli_bounded(
        ("/bin/sh", "-c", "printf 'one\\ntwo\\n'"),
        stdin_payload=None,
        read="all",
        deadline=time.monotonic() + 1,
        stdout_line_channel=channel,
    )

    assert channel.receive(timeout=1) == b"one\n"
    assert channel.receive(timeout=1) == b"two\n"
    assert channel.receive(timeout=1) == outcome


def test_bounded_runner_sends_a_final_stdout_line_without_a_newline() -> None:
    channel = CliLineChannel(maximum_lines=1)

    outcome = run_cli_bounded(
        ("/bin/sh", "-c", 'printf \'{"type":"end","stopReason":"stop"}\''),
        stdin_payload=None,
        read="all",
        deadline=time.monotonic() + 1,
        stdout_line_channel=channel,
    )

    assert channel.receive(timeout=1) == b'{"type":"end","stopReason":"stop"}'
    assert channel.receive(timeout=1) == outcome


def test_bounded_runner_names_a_full_stdout_line_channel() -> None:
    channel = CliLineChannel(maximum_lines=1)

    outcome = run_cli_bounded(
        ("/bin/sh", "-c", "printf 'first\\nsecond\\n'"),
        stdin_payload=None,
        read="all",
        deadline=time.monotonic() + 1,
        stdout_line_channel=channel,
    )

    assert outcome.reason is CliRunReason.OUTPUT_CHANNEL_FULL
    assert outcome.complete is False
    assert channel.receive(timeout=1) == outcome


def test_bounded_runner_reaps_after_a_line_consumer_requests_cancellation() -> None:
    channel = CliLineChannel(maximum_lines=2)
    outcomes = []

    runner = threading.Thread(
        target=lambda: outcomes.append(run_cli_bounded(
            ("/bin/sh", "-c", "printf 'first\\n'; exec sleep 10"),
            stdin_payload=None,
            read="all",
            deadline=time.monotonic() + 1,
            stdout_line_channel=channel,
        )),
    )
    runner.start()

    assert channel.receive(timeout=1) == b"first\n"
    channel.request_abort()
    runner.join(timeout=2)

    assert not runner.is_alive()
    assert outcomes[0].reason is CliRunReason.CANCELLED
    assert outcomes[0].complete is False
    assert channel.receive(timeout=1) == outcomes[0]


def test_bounded_runner_uses_and_removes_a_private_prompt_file() -> None:
    observed = []
    real_popen = subprocess.Popen

    def capture_process(command, **kwargs):
        prompt_path = command[4]
        observed.append((prompt_path, os.stat(prompt_path).st_mode & 0o777))
        return real_popen(command, **kwargs)

    with patch("songmaker_cli.agent_cli.subprocess.Popen", side_effect=capture_process):
        outcome = run_cli_bounded(
            ("/bin/sh", "-c", "cat \"$1\"", "unused", "placeholder"),
            stdin_payload=None,
            read="all",
            deadline=time.monotonic() + 1,
            prompt_file_bytes=b"private prompt",
            prompt_file_arg_index=4,
        )

    assert outcome.stdout == "private prompt"
    assert observed[0][1] == 0o600
    assert not os.path.exists(observed[0][0])


def test_bounded_runner_treats_a_missing_prompt_file_as_already_removed(monkeypatch) -> None:
    prompt_paths: list[str] = []
    real_popen = subprocess.Popen
    real_unlink = os.unlink

    def capture_process(command, **kwargs):
        prompt_paths.append(command[4])
        return real_popen(command, **kwargs)

    def report_missing_file(_path: str) -> None:
        raise FileNotFoundError

    try:
        with patch("songmaker_cli.agent_cli.subprocess.Popen", side_effect=capture_process):
            monkeypatch.setattr(agent_cli.os, "unlink", report_missing_file)
            outcome = run_cli_bounded(
                ("/bin/sh", "-c", ":", "unused", "placeholder"),
                stdin_payload=None,
                read="all",
                deadline=time.monotonic() + 1,
                prompt_file_bytes=b"private prompt",
                prompt_file_arg_index=4,
            )
    finally:
        for prompt_path in prompt_paths:
            real_unlink(prompt_path)

    assert outcome.complete is True
    assert outcome.reason is CliRunReason.COMPLETE


def test_bounded_runner_publishes_prompt_unlink_errors_to_waiting_consumers(monkeypatch) -> None:
    channel = CliLineChannel(maximum_lines=1)
    prompt_paths: list[str] = []
    received: list[CliRunOutcome] = []
    ready_to_receive = threading.Event()
    real_popen = subprocess.Popen
    real_unlink = os.unlink

    def capture_process(command, **kwargs):
        prompt_paths.append(command[4])
        return real_popen(command, **kwargs)

    def wait_for_outcome() -> None:
        ready_to_receive.set()
        received.append(channel.receive(timeout=1))

    def fail_to_unlink(_path: str) -> None:
        raise OSError("prompt cleanup failed")

    consumer = threading.Thread(target=wait_for_outcome)
    consumer.start()
    assert ready_to_receive.wait(timeout=1)
    try:
        with patch("songmaker_cli.agent_cli.subprocess.Popen", side_effect=capture_process):
            monkeypatch.setattr(agent_cli.os, "unlink", fail_to_unlink)
            outcome = run_cli_bounded(
                ("/bin/sh", "-c", ":", "unused", "placeholder"),
                stdin_payload=None,
                read="all",
                deadline=time.monotonic() + 1,
                stdout_line_channel=channel,
                prompt_file_bytes=b"private prompt",
                prompt_file_arg_index=4,
            )
    finally:
        for prompt_path in prompt_paths:
            real_unlink(prompt_path)
    consumer.join(timeout=1)

    assert not consumer.is_alive()
    assert outcome.reason is CliRunReason.IO_ERROR
    assert outcome.complete is False
    assert isinstance(outcome.io_error, OSError)
    assert received == [outcome]


def test_bounded_runner_creates_no_prompt_file_without_prompt_bytes() -> None:
    with patch("songmaker_cli.agent_cli.tempfile.mkstemp") as create_prompt_file:
        outcome = run_cli_bounded(
            ("/bin/sh", "-c", "printf ready"),
            stdin_payload=None,
            read="all",
            deadline=time.monotonic() + 1,
        )

    assert outcome.stdout == "ready"
    create_prompt_file.assert_not_called()


@pytest.mark.parametrize(
    ("prompt_file_bytes", "prompt_file_arg_index", "message"),
    (
        (None, 0, "requires prompt bytes"),
        (b"private prompt", None, "require a prompt file index"),
        (b"private prompt", -1, "outside the CLI command"),
        (b"private prompt", 3, "outside the CLI command"),
    ),
)
def test_bounded_runner_rejects_an_invalid_private_prompt_contract(
    prompt_file_bytes: bytes | None,
    prompt_file_arg_index: int | None,
    message: str,
) -> None:
    outcome = run_cli_bounded(
        ("/bin/sh", "-c", ":"),
        stdin_payload=None,
        read="all",
        deadline=time.monotonic() + 1,
        prompt_file_bytes=prompt_file_bytes,
        prompt_file_arg_index=prompt_file_arg_index,
    )

    assert outcome.started is False
    assert outcome.reason is CliRunReason.SPAWN_FAILED
    assert isinstance(outcome.spawn_error, ValueError)
    assert message in str(outcome.spawn_error)


def test_bounded_runner_removes_a_private_prompt_file_when_writing_it_fails(
    monkeypatch,
    tmp_path,
) -> None:
    created_paths: list[str] = []
    real_mkstemp = tempfile.mkstemp

    def create_prompt_file(*, prefix: str) -> tuple[int, str]:
        descriptor, path = real_mkstemp(dir=tmp_path, prefix=prefix)
        created_paths.append(path)
        return descriptor, path

    def fail_to_open(descriptor: int, *_args, **_kwargs):
        os.close(descriptor)
        raise OSError("cannot write private prompt")

    monkeypatch.setattr(agent_cli.tempfile, "mkstemp", create_prompt_file)
    monkeypatch.setattr(agent_cli.os, "fdopen", fail_to_open)

    outcome = run_cli_bounded(
        ("/bin/sh", "-c", ":", "placeholder"),
        stdin_payload=None,
        read="all",
        deadline=time.monotonic() + 1,
        prompt_file_bytes=b"private prompt",
        prompt_file_arg_index=3,
    )

    assert outcome.started is False
    assert outcome.reason is CliRunReason.SPAWN_FAILED
    assert isinstance(outcome.spawn_error, OSError)
    assert created_paths
    assert not os.path.exists(created_paths[0])


def test_cancelling_a_line_channel_discards_unread_output() -> None:
    channel = CliLineChannel(maximum_lines=1)
    outcome = CliRunOutcome(
        started=True,
        spawn_error=None,
        returncode=-15,
        stdout="",
        stderr="",
        complete=False,
        became_zombie=False,
        reason=CliRunReason.CANCELLED,
    )

    assert channel._send(b"discard\n")
    channel.request_abort()
    channel._close(outcome)

    assert channel.receive(timeout=1) == outcome


@pytest.mark.parametrize(
    ("checker", "payload", "detail"),
    [
        ("grok", "not json", GROK_CLI_CREDENTIALS_INVALID_DETAIL),
        ("grok", "[]", GROK_CLI_CREDENTIALS_INVALID_DETAIL),
        ("grok", '{"realm": []}', GROK_CLI_CREDENTIALS_INVALID_DETAIL),
        ("grok", '{"realm": {"key": 3}}', GROK_CLI_CREDENTIALS_INVALID_DETAIL),
        ("codex", "not json", CODEX_CLI_CREDENTIALS_INVALID_DETAIL),
        ("codex", "[]", CODEX_CLI_CREDENTIALS_INVALID_DETAIL),
        ("codex", '{"tokens": []}', CODEX_CLI_CREDENTIALS_INVALID_DETAIL),
        ("codex", '{"tokens": {"access_token": 3}}', CODEX_CLI_CREDENTIALS_INVALID_DETAIL),
    ],
)
def test_credential_probe_names_malformed_mounted_credentials(
    tmp_path, monkeypatch, checker: str, payload: str, detail: str,
) -> None:
    credential_file = tmp_path / f"{checker}.json"
    credential_file.write_text(payload)
    function = (
        agent_cli.grok_cli_token_is_present
        if checker == "grok"
        else agent_cli.codex_cli_access_token_is_present
    )
    constant = "GROK_CLI_AUTH_FILE" if checker == "grok" else "CODEX_CLI_AUTH_FILE"
    monkeypatch.setattr(agent_cli, constant, credential_file)

    with pytest.raises(AgentCliUnavailableError, match=detail):
        function()

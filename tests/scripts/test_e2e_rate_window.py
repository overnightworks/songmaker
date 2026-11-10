"""defect:#1555 -- the E2E API budget is sized from the busiest measured window."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from songmaker_cli.request_policies import (
    BACKCHANNEL_LOGOUT_PATH,
    SIGN_IN_PATHS,
    build_rate_limit_policy,
)
from songmaker_cli.settings import Settings

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import e2e_rate_window as rate_window  # noqa: E402

RUN_START = datetime.fromisoformat("2026-10-17T10:00:00.000000Z")
RUNNER_IP = "172.18.0.1"


@pytest.fixture
def policy():
    return build_rate_limit_policy(Settings())


def access_line(path: str, seconds: float, ip: str = RUNNER_IP) -> str:
    at = RUN_START + timedelta(seconds=seconds)
    return json.dumps({
        "ip": ip,
        "method": "GET",
        "path": path,
        "event": f"ACCESS {ip} GET {path} 200 (3ms)",
        "level": "info",
        "logger": "songmaker_cli.middleware.access_log",
        "timestamp": at.isoformat().replace("+00:00", "Z"),
    })


@pytest.mark.parametrize(
    "line",
    [
        "Running migrations...",
        json.dumps({"event": "Application startup complete.", "timestamp": "x"}),
        "",
    ],
    ids=["entrypoint text", "other structured event", "blank line"],
)
def test_a_line_without_an_access_record_is_skipped(line: str) -> None:
    """defect:#1555 -- only the access middleware's records are counted."""
    assert rate_window.parse_access_record(line) is None


def test_an_access_line_yields_its_client_path_and_time() -> None:
    """defect:#1555 -- the record keeps the fields the limiter keys on."""
    record = rate_window.parse_access_record(access_line("/api/albums", 1.5))

    assert record == rate_window.AccessRecord(
        at=RUN_START + timedelta(seconds=1.5), client_ip=RUNNER_IP, path="/api/albums",
    )


@pytest.mark.parametrize(
    ("seconds", "request_count", "starts_at"),
    [
        pytest.param((0, 10, 59.9, 60, 61, 62, 200), 5, 10, id="burst"),
        pytest.param((0, 60), 1, 0, id="exact-boundary"),
        pytest.param((60, 0, 59), 2, 0, id="unordered"),
    ],
)
def test_the_busiest_window_counts_only_requests_inside_one_budget_window(
    policy, seconds: tuple[float, ...], request_count: int, starts_at: float,
) -> None:
    """defect:#1555 -- a burst is judged inside the limiter's 60 s, not across the run."""
    lines = [access_line("/api/albums", second) for second in seconds]

    peak = rate_window.busiest_window(lines, policy, policy.default)

    assert peak == rate_window.WindowPeak(
        RUNNER_IP, request_count, RUN_START + timedelta(seconds=starts_at),
    )


def test_each_client_address_has_its_own_window(policy) -> None:
    """defect:#1555 -- the limiter buckets per address, so the peak does too."""
    lines = [
        access_line("/api/albums", 0, ip="10.0.0.1"),
        access_line("/api/albums", 1, ip="10.0.0.2"),
        access_line("/api/albums", 2, ip="10.0.0.2"),
    ]

    peak = rate_window.busiest_window(lines, policy, policy.default)

    assert (peak.client_ip, peak.request_count) == ("10.0.0.2", 2)


@pytest.mark.parametrize(
    ("path", "spends_api_budget"),
    [
        ("/api/albums", True),
        ("/library", True),
        ("/health", True),
        ("/favicon.svg", False),
        ("/_app/immutable/entry.js", False),
        ("/audio/take.mp3", False),
        ("/api/jobs/job-1/stream", False),
        (SIGN_IN_PATHS.start, False),
        (SIGN_IN_PATHS.callback, False),
        (SIGN_IN_PATHS.logout, False),
    ],
)
def test_the_rate_limit_policy_decides_which_requests_spend_the_api_budget(
    policy, path: str, spends_api_budget: bool,
) -> None:
    """defect:#1555 -- exempt, media and stream paths stay out; documents count."""
    peak = rate_window.busiest_window([access_line(path, 0)], policy, policy.default)

    assert (peak is not None) is spends_api_budget


def test_a_log_without_api_requests_has_no_peak(policy) -> None:
    """defect:#1555 -- a missing measurement is reported, never read as zero."""
    assert rate_window.busiest_window(["Running migrations..."], policy, policy.default) is None


@pytest.mark.parametrize(
    ("path", "spends_sign_in_budget"),
    [
        (SIGN_IN_PATHS.start, True),
        (SIGN_IN_PATHS.callback, True),
        (SIGN_IN_PATHS.logout, True),
        (BACKCHANNEL_LOGOUT_PATH, False),
        ("/api/albums", False),
    ],
)
def test_start_callback_and_logout_spend_the_sign_in_budget(
    policy, path: str, spends_sign_in_budget: bool,
) -> None:
    peak = rate_window.busiest_window([access_line(path, 0)], policy, policy.sign_in)

    assert (peak is not None) is spends_sign_in_budget


@pytest.mark.parametrize(
    ("path", "budget_of"),
    [
        pytest.param("/api/albums", lambda policy: policy.default, id="api"),
        pytest.param(SIGN_IN_PATHS.start, lambda policy: policy.sign_in, id="sign-in"),
    ],
)
def test_each_budget_is_measured_over_its_own_window(policy, path: str, budget_of) -> None:
    budget = budget_of(policy)
    lines = [access_line(path, 0), access_line(path, budget.window_seconds - 1)]
    beyond = [access_line(path, 0), access_line(path, budget.window_seconds)]

    assert rate_window.busiest_window(lines, policy, budget).request_count == 2
    assert rate_window.busiest_window(beyond, policy, budget).request_count == 1

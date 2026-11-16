"""defect:#1555 -- the E2E API budget is sized from the busiest measured window."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from logline import REQUEST_EVENT
from logline.testing import configured
from support.request_lines import request_lines
from support.web_app import make_test_app

from songmaker_cli.request_policies import (
    API_BUDGET_NAME,
    BACKCHANNEL_LOGOUT_PATH,
    SIGN_IN_PATHS,
    STREAM_BUDGET_NAME,
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


def request_line(route: str | None, seconds: float, ip: str = RUNNER_IP) -> str:
    at = RUN_START + timedelta(seconds=seconds)
    return json.dumps({
        "ts": at.isoformat().replace("+00:00", "Z"),
        "level": "info",
        "service": "songmaker-web",
        "event": REQUEST_EVENT,
        "outcome": "ok",
        "method": "GET",
        "route": route,
        "status": 200,
        "ip": ip,
    })


@pytest.mark.parametrize(
    "line",
    [
        "Running migrations...",
        json.dumps({"event": "Application startup complete.", "ts": "x"}),
        "",
        request_line(None, 0),
    ],
    ids=["entrypoint text", "other structured event", "blank line", "request no route answered"],
)
def test_a_line_without_a_routed_request_is_skipped(line: str) -> None:
    """defect:#1555 -- only the request lines that name a route are counted."""
    assert rate_window.parse_request_record(line) is None


def test_a_request_line_yields_its_client_route_and_time() -> None:
    """defect:#1555 -- the record keeps the fields the limiter keys on."""
    record = rate_window.parse_request_record(request_line("/api/albums", 1.5))

    assert record == rate_window.RequestRecord(
        at=RUN_START + timedelta(seconds=1.5), client_ip=RUNNER_IP, route="/api/albums",
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
    lines = [request_line("/api/albums", second) for second in seconds]

    peak = rate_window.busiest_window(lines, policy, policy.default)

    assert peak == rate_window.WindowPeak(
        RUNNER_IP, request_count, RUN_START + timedelta(seconds=starts_at),
    )


def test_each_client_address_has_its_own_window(policy) -> None:
    """defect:#1555 -- the limiter buckets per address, so the peak does too."""
    lines = [
        request_line("/api/albums", 0, ip="10.0.0.1"),
        request_line("/api/albums", 1, ip="10.0.0.2"),
        request_line("/api/albums", 2, ip="10.0.0.2"),
    ]

    peak = rate_window.busiest_window(lines, policy, policy.default)

    assert (peak.client_ip, peak.request_count) == ("10.0.0.2", 2)


@pytest.mark.parametrize(
    ("path", "spends_api_budget"),
    [
        ("/api/albums", True),
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
    """defect:#1555 -- exempt, media and stream routes stay out."""
    peak = rate_window.busiest_window([request_line(path, 0)], policy, policy.default)

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
    peak = rate_window.busiest_window([request_line(path, 0)], policy, policy.sign_in)

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
    lines = [request_line(path, 0), request_line(path, budget.window_seconds - 1)]
    beyond = [request_line(path, 0), request_line(path, budget.window_seconds)]

    assert rate_window.busiest_window(lines, policy, budget).request_count == 2
    assert rate_window.busiest_window(beyond, policy, budget).request_count == 1


@pytest.mark.parametrize(
    ("path", "route", "budget_name"),
    [
        ("/api/songs/proof", "/api/songs/{song_id}", API_BUDGET_NAME),
        ("/api/jobs/proof/stream", "/api/jobs/{job_id}/stream", STREAM_BUDGET_NAME),
    ],
)
def test_the_request_line_the_server_writes_names_a_route_that_spends_its_paths_budget(
    tmp_path: Path, pg_factory, capsys: pytest.CaptureFixture[str], policy,
    path: str, route: str, budget_name: str,
) -> None:
    """defect:#1576 -- the report that sizes the E2E rate limit reads the line the server writes."""
    server_app, _ = make_test_app(tmp_path, factory=pg_factory)

    async def request() -> None:
        transport = httpx.ASGITransport(app=server_app.app, client=(RUNNER_IP, 55000))
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
            assert (await client.get(path)).status_code == 401

    before = datetime.now(timezone.utc)
    with configured("songmaker-web"):
        asyncio.run(request())
    after = datetime.now(timezone.utc)

    (line,) = request_lines(capsys.readouterr().out)
    record = rate_window.parse_request_record(json.dumps(line))
    assert record is not None
    assert (record.client_ip, record.route) == (RUNNER_IP, route)
    assert rate_window.budget_spent_by(record, policy).name == budget_name
    assert before <= record.at <= after

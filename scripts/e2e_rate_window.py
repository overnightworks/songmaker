"""Report the busiest API and sign-in rate-limit windows of one E2E run from the access log.

The E2E stack's ``IP_RATE_LIMIT`` override is sized from the API peak, and the
sign-in peak shows whether webauth's sign-in budget still fits the suite, so the
CI workflow prints both after every Playwright run instead of trusting a dated
measurement. Each budget is measured over its own window. Run inside the web
container, where the rate-limit policy that classifies each path is importable:

    docker compose logs --no-color --no-log-prefix songmaker-web \\
        | docker compose exec -T songmaker-web /app/.venv/bin/python \\
            scripts/e2e_rate_window.py

The access log is written inside the rate limiter, so a request the limiter
refused with 429 never reaches it: on a run that hit the limit, the reported
peak is a lower bound of what was attempted.
"""
# ruff: noqa: T201 - this report prints the busiest rate-limit window

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

from webauth.policies import RateLimitBudget, RateLimitPolicy

from songmaker_cli.request_policies import SIGN_IN_PATHS, build_rate_limit_policy
from songmaker_cli.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

ACCESS_EVENT_PREFIX: Final = "ACCESS "
# The paths the webauth installer spends the policy's sign-in budget on; the policy built
# here is the one before installation, which does not know them yet.
SIGN_IN_BUDGET_PATHS: Final = frozenset(
    {SIGN_IN_PATHS.start, SIGN_IN_PATHS.callback, SIGN_IN_PATHS.logout},
)


@dataclass(frozen=True)
class AccessRecord:
    at: datetime
    client_ip: str
    path: str


@dataclass(frozen=True)
class WindowPeak:
    client_ip: str
    request_count: int
    starts_at: datetime


def parse_access_record(line: str) -> AccessRecord | None:
    """The access record a JSON log line carries, or None for any other line."""
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(entry, dict) or not str(entry.get("event", "")).startswith(
        ACCESS_EVENT_PREFIX,
    ):
        return None
    return AccessRecord(
        at=datetime.fromisoformat(entry["timestamp"]),
        client_ip=entry["ip"],
        path=entry["path"],
    )


def budget_spent_by(record: AccessRecord, policy: RateLimitPolicy) -> RateLimitBudget | None:
    if policy.is_exempt(record.path):
        return None
    if record.path in SIGN_IN_BUDGET_PATHS:
        return policy.sign_in
    return policy.budget_for(record.path)


def busiest_window_of_one_client(
    client_ip: str, times: Sequence[datetime], window: timedelta,
) -> WindowPeak:
    peak = WindowPeak(client_ip, 0, times[0])
    first = 0
    for last, at in enumerate(times):
        while at - times[first] >= window:
            first += 1
        if last - first + 1 > peak.request_count:
            peak = WindowPeak(client_ip, last - first + 1, times[first])
    return peak


def busiest_window(
    lines: Iterable[str], policy: RateLimitPolicy, budget: RateLimitBudget,
) -> WindowPeak | None:
    """The most requests spending ``budget`` one client sent inside one of its windows."""
    window = timedelta(seconds=budget.window_seconds)
    times_by_client: dict[str, list[datetime]] = defaultdict(list)
    for line in lines:
        record = parse_access_record(line)
        if record is not None and budget_spent_by(record, policy) is budget:
            times_by_client[record.client_ip].append(record.at)
    return max(
        (
            busiest_window_of_one_client(client_ip, sorted(times), window)
            for client_ip, times in times_by_client.items()
        ),
        key=lambda peak: peak.request_count,
        default=None,
    )


def describe_peak(label: str, peak: WindowPeak, budget: RateLimitBudget) -> str:
    return (
        f"Busiest {budget.window_seconds} s {label} window: {peak.request_count} requests "
        f"from {peak.client_ip} starting {peak.starts_at.isoformat()}; "
        f"the {label} budget is {budget.max_requests} "
        f"({budget.max_requests / peak.request_count:.1f}x headroom)."
    )


def main() -> int:
    policy = build_rate_limit_policy(get_settings())
    lines = sys.stdin.readlines()
    api_peak = busiest_window(lines, policy, policy.default)
    if api_peak is None:
        print("No API-class access record in the log; the measurement is broken.", file=sys.stderr)
        return 1
    print(describe_peak("API", api_peak, policy.default))
    sign_in_peak = busiest_window(lines, policy, policy.sign_in)
    if sign_in_peak is None:
        print(
            f"No sign-in request in the log; the sign-in budget is "
            f"{policy.sign_in.max_requests} per {policy.sign_in.window_seconds} s.",
        )
    else:
        print(describe_peak("sign-in", sign_in_peak, policy.sign_in))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Report the busiest API rate-limit window of one E2E run from the access log.

The E2E stack's ``IP_RATE_LIMIT`` override is sized from this number, so the
CI workflow prints it after every Playwright run instead of trusting a dated
measurement. Run inside the web container, where the rate-limit policy that
classifies each path is importable:

    docker compose logs --no-color --no-log-prefix songmaker-web \\
        | docker compose exec -T songmaker-web /app/.venv/bin/python \\
            scripts/e2e_rate_window.py

The access log is written inside the rate limiter, so a request the limiter
refused with 429 never reaches it: on a run that hit the limit, the reported
peak is a lower bound of what was attempted.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

from webauth.policies import RateLimitPolicy

from songmaker_cli.request_policies import build_rate_limit_policy
from songmaker_cli.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

ACCESS_EVENT_PREFIX: Final = "ACCESS "


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


def spends_api_budget(record: AccessRecord, policy: RateLimitPolicy) -> bool:
    return not policy.is_exempt(record.path) and policy.budget_for(record.path) is policy.default


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


def busiest_api_window(
    lines: Iterable[str], policy: RateLimitPolicy,
) -> WindowPeak | None:
    """The most API-class requests one client sent inside one budget window."""
    window = timedelta(seconds=policy.default.window_seconds)
    times_by_client: dict[str, list[datetime]] = defaultdict(list)
    for line in lines:
        record = parse_access_record(line)
        if record is not None and spends_api_budget(record, policy):
            times_by_client[record.client_ip].append(record.at)
    return max(
        (
            busiest_window_of_one_client(client_ip, sorted(times), window)
            for client_ip, times in times_by_client.items()
        ),
        key=lambda peak: peak.request_count,
        default=None,
    )


def main() -> int:
    policy = build_rate_limit_policy(get_settings())
    peak = busiest_api_window(sys.stdin, policy)
    if peak is None:
        print("No API-class access record in the log; the measurement is broken.", file=sys.stderr)
        return 1
    budget = policy.default
    print(
        f"Busiest {budget.window_seconds} s API window: {peak.request_count} requests "
        f"from {peak.client_ip} starting {peak.starts_at.isoformat()}; "
        f"IP_RATE_LIMIT is {budget.max_requests} "
        f"({budget.max_requests / peak.request_count:.1f}x headroom).",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

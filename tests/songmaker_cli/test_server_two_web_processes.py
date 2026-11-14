"""Two web processes started from the CLI share their sessions and their IP rate window."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from redis import Redis
from support.app_processes import HEALTH_PATH, WebProcess, WebProcesses, web_processes
from support.web_app import issued_cookies, seed_user

from songmaker_cli.app_context import AppContext, build_web_auth_config
from songmaker_cli.auth_stores import DatabaseSessionRecordStore
from songmaker_cli.request_policies import build_rate_limit_policy

SIGNED_IN_PATH = "/api/auth/me"
PERSON_NAME = "pat"
REQUEST_TIMEOUT_SECONDS = 10.0
CHILD_DEATH_DEADLINE_SECONDS = 10.0
_HOLDER_SCRIPT = """
import sys, time
from pathlib import Path
from support.app_processes import web_processes
root, database_url, redis_url = sys.argv[1:]
with web_processes(Path(root), database_url=database_url, redis_url=redis_url) as cluster:
    print(cluster.start("a").process.pid, flush=True)
    time.sleep(600)
"""


@pytest.fixture
def case_factory(extra_pg_factory):
    """A session factory on a database of the case's own, which the per-test reset leaves alone."""
    return extra_pg_factory()


@pytest.fixture
def database_url(case_factory) -> str:
    return case_factory.kw["bind"].url.render_as_string(hide_password=False)


@pytest.fixture
def web_cluster(tmp_path: Path, case_factory, database_url: str, redis_url: str):
    """The processes of one case, on a database and a Redis of its own; none is started yet."""
    with web_processes(tmp_path, database_url=database_url, redis_url=redis_url) as cluster:
        yield cluster, case_factory


@pytest.fixture
def two_processes(web_cluster):
    """A and B, running against one database and one Redis."""
    cluster, factory = web_cluster
    return cluster, factory, cluster.start("a"), cluster.start("b")


def _signed_in_cookies(cluster: WebProcesses, factory, redis_url: str) -> dict[str, str]:
    """Open a session through the production session store and issue its cookie."""
    now = datetime.now(timezone.utc)
    settings = cluster.settings()
    with factory() as session:
        person = seed_user(session, PERSON_NAME)
        record = DatabaseSessionRecordStore(session).create(
            person.id,
            now=now,
            expires_at=now + timedelta(seconds=settings.session_idle_seconds),
            refresh_token=None,
            id_token=None,
            account_language=None,
        )
        session.commit()
        session_id = record.id
    context = AppContext(
        db=factory,
        audio_dir=cluster.audio_dir,
        data_dir=cluster.root,
        signing_key=cluster.session_secret.encode(),
        redis=Redis.from_url(redis_url),
    )
    return issued_cookies(session_id, build_web_auth_config(context, settings))


def _is_alive(pid: int) -> bool:
    """A zombie awaiting its reaper no longer runs."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        return False
    return state != "Z"


def _get(web_process: WebProcess, path: str, **kwargs) -> httpx.Response:
    return httpx.get(f"{web_process.url}{path}", timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)


def test_a_session_seeded_in_the_database_answers_on_both_processes(
    two_processes, redis_url: str,
) -> None:
    cluster, factory, process_a, process_b = two_processes
    cookies = _signed_in_cookies(cluster, factory, redis_url)

    answers = [_get(each, SIGNED_IN_PATH, cookies=cookies) for each in (process_a, process_b)]

    assert [(answer.status_code, answer.json()["username"]) for answer in answers] == [
        (200, PERSON_NAME),
        (200, PERSON_NAME),
    ]


def test_an_ip_rate_window_spent_on_one_process_refuses_on_the_other(two_processes) -> None:
    cluster, _, process_a, process_b = two_processes
    budget = build_rate_limit_policy(cluster.settings()).default.max_requests

    statuses_on_a = [_get(process_a, HEALTH_PATH).status_code for _ in range(budget + 1)]
    answer_on_b = _get(process_b, HEALTH_PATH)

    assert (statuses_on_a[-1], answer_on_b.status_code) == (429, 429)


def test_a_killed_process_leaves_the_other_serving(two_processes) -> None:
    _, _, process_a, process_b = two_processes

    process_a.kill()

    assert (process_a.process.returncode, _get(process_b, HEALTH_PATH).status_code) == (
        -signal.SIGKILL,
        200,
    )


def _fail_after_starting_two(
    tmp_path: Path, database_url: str, redis_url: str, started: list[WebProcess],
) -> None:
    with web_processes(tmp_path, database_url=database_url, redis_url=redis_url) as cluster:
        started.extend([cluster.start("a"), cluster.start("b")])
        started[0].kill()
        raise AssertionError("the case fails")


def test_a_failing_case_leaves_no_child_behind(
    tmp_path: Path, database_url: str, redis_url: str,
) -> None:
    started: list[WebProcess] = []

    with pytest.raises(AssertionError):
        _fail_after_starting_two(tmp_path, database_url, redis_url, started)

    assert [each.process.poll() is not None for each in started] == [True, True]


def test_the_children_die_with_a_test_process_that_is_killed(
    tmp_path: Path, database_url: str, redis_url: str,
) -> None:
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER_SCRIPT, str(tmp_path), database_url, redis_url],
        stdout=subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )
    try:
        child_pid = int(holder.stdout.readline())
        holder.kill()
        holder.wait()
        deadline = time.monotonic() + CHILD_DEATH_DEADLINE_SECONDS
        while _is_alive(child_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _is_alive(child_pid)
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait()
        holder.stdout.close()

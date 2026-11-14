"""Two web processes started from the CLI share their sessions and their IP rate window."""

from __future__ import annotations

import signal
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


@pytest.fixture
def web_cluster(tmp_path: Path, extra_pg_factory, redis_url: str):
    """The processes of one case, on a database and a Redis of its own; none is started yet."""
    factory = extra_pg_factory()
    database_url = factory.kw["bind"].url.render_as_string(hide_password=False)
    with web_processes(tmp_path, database_url=database_url, redis_url=redis_url) as cluster:
        yield cluster, factory


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


def test_a_killed_process_leaves_the_other_serving_and_no_child_behind(two_processes) -> None:
    _, _, process_a, process_b = two_processes

    process_a.kill()

    assert (process_a.process.returncode, _get(process_b, HEALTH_PATH).status_code) == (
        -signal.SIGKILL,
        200,
    )


def test_a_process_killed_before_the_case_ends_leaves_no_child(web_cluster) -> None:
    cluster, _ = web_cluster
    started = [cluster.start("a"), cluster.start("b")]
    started[0].kill()

    cluster.stop_all()

    assert [each.process.poll() is not None for each in started] == [True, True]

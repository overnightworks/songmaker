"""Two web processes: a turn held at the gateway on one has its reply read on the other."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import httpx
from support.app_processes import WebProcess, poll_until
from support.web_cluster_world import SCRIPTED_REPLY, StandInCluster

PERSON_NAME = "pat"
REFRESH_TOKEN = "refresh-token-of-pat"  # noqa: S105
QUESTION = "Which key suits a lullaby?"
REQUEST_TIMEOUT_SECONDS = 10.0
GATEWAY_DEADLINE_SECONDS = 20.0
TURN_DEADLINE_SECONDS = 20.0


def _frames(web_process: WebProcess, cookies: dict[str, str]) -> list[dict]:
    """Send the question as a turn from the process's own page and read its stream to the end."""
    with httpx.stream(
        "POST",
        f"{web_process.url}/api/chat/turn",
        json={"message": QUESTION},
        cookies=cookies,
        headers={"Origin": web_process.url},
        timeout=TURN_DEADLINE_SECONDS,
    ) as response:
        response.raise_for_status()
        return [
            json.loads(line[len("data: "):])
            for line in response.iter_lines()
            if line.startswith("data: ")
        ]


def _conversation(web_process: WebProcess, cookies: dict[str, str]) -> dict:
    listed = httpx.get(
        f"{web_process.url}/api/conversations", cookies=cookies, timeout=REQUEST_TIMEOUT_SECONDS,
    ).json()
    conversation_id = listed["conversations"][0]["id"]
    return httpx.get(
        f"{web_process.url}/api/conversations/{conversation_id}",
        cookies=cookies,
        timeout=REQUEST_TIMEOUT_SECONDS,
    ).json()


def test_a_turn_held_at_the_gateway_on_one_process_stores_the_reply_the_other_reads(
    stand_in_cluster: StandInCluster, redis_url: str,
) -> None:
    process_a = stand_in_cluster.cluster.start("a")
    process_b = stand_in_cluster.cluster.start("b")
    cookies = stand_in_cluster.sign_in(
        redis_url, PERSON_NAME, refresh_token=REFRESH_TOKEN,
    ).cookies
    gateway = stand_in_cluster.gateway

    with ThreadPoolExecutor(max_workers=1) as executor:
        turn = executor.submit(_frames, process_a, cookies)
        reached_gateway = gateway.received.wait(GATEWAY_DEADLINE_SECONDS)
        while_held = _conversation(process_b, cookies)
        gateway.released.set()
        frames = turn.result(timeout=TURN_DEADLINE_SECONDS)
    stored = poll_until(
        lambda: _conversation(process_b, cookies)["turn_running"] is False,
        deadline_seconds=TURN_DEADLINE_SECONDS,
    )
    after = _conversation(process_b, cookies)

    assert (
        reached_gateway,
        while_held["turn_running"],
        [message["content"] for message in while_held["messages"]],
        stand_in_cluster.issuer.realm.grants_seen,
        frames[-1]["type"],
        stored,
        [message["content"] for message in after["messages"]],
    ) == (
        True,
        True,
        [QUESTION],
        ["refresh_token"],
        "final",
        True,
        [QUESTION, SCRIPTED_REPLY],
    )

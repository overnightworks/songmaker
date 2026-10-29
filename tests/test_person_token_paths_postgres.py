"""A first token call racing a first sign-in on PostgreSQL: one account, one audit."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fake_oidc_issuer import Person
from postgres_lock_harness import in_thread
from sqlalchemy.orm import sessionmaker
from support.oidc_world import World
from support.token_world import TokenWorld, make_token_world


def test_t18_a_first_token_call_and_a_first_sign_in_race_into_one_account_and_one_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory: sessionmaker,
) -> None:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    world = make_token_world(tmp_path, monkeypatch, factory=pg_factory)
    browser = World(world.client, pg_factory, world.issuer)
    started = browser.start()
    start_together = threading.Barrier(2)
    answers: dict[str, object] = {}

    def token_call() -> object:
        start_together.wait()
        return world.client.get("/api/songs", headers=world.bearer())

    def sign_in() -> object:
        start_together.wait()
        return browser.callback(Person(TokenWorld.ALICE, "alice"), started)

    threads = [in_thread(answers, "token", token_call), in_thread(answers, "sign-in", sign_in)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert (answers["token"].status_code, answers["sign-in"].status_code) == (200, 303)
    assert [row[0] for row in world.users()] == [TokenWorld.ALICE]
    assert world.audits().count((None, "create", "user", TokenWorld.ALICE)) == 1

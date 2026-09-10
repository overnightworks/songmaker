"""Startup pins the judge's existing transport once, independently of settings requests."""

from __future__ import annotations

import pytest
from conftest import TEST_SECRET, make_fake_redis, make_test_app, override_provider_runtime
from sqlalchemy import event

from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import SETTING_JUDGE_PROVIDER, SETTING_JUDGE_ROUTE
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import RateLimitSetting
from songmaker_cli.db.queries import (
    get_judge_route,
    set_claude_model,
)
from songmaker_cli.lifecycle import pin_judge_route


@pytest.fixture
def ctx(tmp_path):
    return AppContext(
        db=init_test_db(tmp_path / "judge-boot.db"),
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        signing_key=TEST_SECRET,
        redis=make_fake_redis(),
    )


@pytest.mark.parametrize("provider", [None, "", "claude", "grok", "codex", "retired"])
@pytest.mark.parametrize("key_is_set", [False, True])
def test_boot_pins_the_existing_provider_call_path(ctx, provider, key_is_set, caplog):
    if provider is not None:
        with ctx.db() as session:
            set_claude_model(session, SETTING_JUDGE_PROVIDER, provider)
            session.commit()
    override_provider_runtime(anthropic_api_key="test-key" if key_is_set else None)
    caplog.set_level("INFO", logger="songmaker_cli.lifecycle")

    pin_judge_route(ctx)

    expected = "cli" if provider in (None, "", "claude") and not key_is_set else "api"
    with ctx.db() as session:
        assert get_judge_route(session) == expected
        assert session.query(RateLimitSetting).filter_by(
            setting_key=SETTING_JUDGE_ROUTE,
        ).count() == 1
    assert any(expected in record.message for record in caplog.records)
    assert "test-key" not in caplog.text

    override_provider_runtime(anthropic_api_key=None if key_is_set else "test-key")
    pin_judge_route(ctx)
    with ctx.db() as session:
        assert get_judge_route(session) == expected


@pytest.mark.parametrize("route", ["cli", "api", "", "unknown"])
def test_boot_preserves_an_existing_route_even_when_invalid(ctx, route):
    with ctx.db() as session:
        set_claude_model(session, SETTING_JUDGE_ROUTE, route)
        session.commit()

    pin_judge_route(ctx)

    with ctx.db() as session:
        assert session.query(RateLimitSetting).filter_by(
            setting_key=SETTING_JUDGE_ROUTE,
        ).one().value_text == route


def test_concurrent_startup_keeps_the_first_committed_route(ctx, caplog):
    competing_boot_finished = False

    def finish_competing_boot(_mapper, _connection, row):
        nonlocal competing_boot_finished
        if row.setting_key != SETTING_JUDGE_ROUTE or competing_boot_finished:
            return
        competing_boot_finished = True
        override_provider_runtime(anthropic_api_key="test-key")
        pin_judge_route(ctx)

    override_provider_runtime(anthropic_api_key=None)
    caplog.set_level("INFO", logger="songmaker_cli.lifecycle")
    event.listen(RateLimitSetting, "before_insert", finish_competing_boot)
    try:
        pin_judge_route(ctx)
    finally:
        event.remove(RateLimitSetting, "before_insert", finish_competing_boot)

    with ctx.db() as session:
        row = session.query(RateLimitSetting).filter_by(setting_key=SETTING_JUDGE_ROUTE).one()
        assert row.value_text == "api"
    assert any("concurrent" in record.message for record in caplog.records)


def test_unexpected_pin_failure_remains_visible(ctx, monkeypatch):
    def unavailable_database(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("songmaker_cli.db.queries.pin_judge_route_if_unset", unavailable_database)

    with pytest.raises(RuntimeError, match="database unavailable"):
        pin_judge_route(ctx)


@pytest.mark.parametrize("key_is_set,expected", [(False, "cli"), (True, "api")])
def test_server_startup_pins_the_route_before_serving_requests(
    tmp_path, mock_arq_pool, key_is_set, expected,
):
    client, factory = make_test_app(tmp_path)
    with factory() as session:
        session.query(RateLimitSetting).filter_by(setting_key=SETTING_JUDGE_ROUTE).delete()
        session.commit()
    override_provider_runtime(anthropic_api_key="test-key" if key_is_set else None)

    with client:
        with factory() as session:
            assert get_judge_route(session) == expected

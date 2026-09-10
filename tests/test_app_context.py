"""How songmaker assembles the configuration the auth library reads."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import TEST_SECRET, make_fake_redis
from webauth.proxies import TrustedProxies

from songmaker_cli.app_context import (
    AppContext,
    build_web_auth_config,
    parse_trusted_proxies,
)
from songmaker_cli.constants import (
    ROLE_ADMIN,
)
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.settings import get_settings


@pytest.fixture
def ctx(tmp_path: Path) -> AppContext:
    return AppContext(
        db=init_test_db(tmp_path / "songmaker.db"),
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        signing_key=TEST_SECRET,
        redis=make_fake_redis(),
        trusted_proxies=TrustedProxies.parse("172.16.0.0/12"),
        allowed_hosts_exact=frozenset({"songmaker.example"}),
        allowed_hosts_patterns=[re.compile(r"^[^:]+\.example$")],
    )


def test_the_configuration_carries_the_deployments_own_facts(ctx: AppContext) -> None:
    config = build_web_auth_config(ctx, get_settings())

    assert config.signing_key == TEST_SECRET
    assert "172.18.0.1" in config.trusted_proxies
    assert config.allowed_hosts_exact == frozenset({"songmaker.example"})
    assert [pattern.pattern for pattern in config.allowed_hosts_patterns] == [
        r"^[^:]+\.example$",
    ]


def test_the_configuration_takes_the_session_and_login_limits_from_settings(
    ctx: AppContext,
) -> None:
    settings = get_settings()

    config = build_web_auth_config(ctx, settings)

    assert config.session_max_age_seconds == settings.session_max_age_seconds
    assert config.login_rate_limit == settings.login_rate_limit
    assert config.login_lockout_threshold == settings.login_lockout_threshold
    assert config.login_lockout_window_seconds == settings.login_lockout_window_seconds


def test_the_configuration_names_songmakers_admin_role(ctx: AppContext) -> None:
    assert build_web_auth_config(ctx, get_settings()).admin_role == ROLE_ADMIN


def test_trusted_proxies_are_read_from_the_configured_networks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.1, 172.16.0.0/12")

    proxies = parse_trusted_proxies(get_settings())

    assert "10.0.0.1" in proxies
    assert "172.20.3.4" in proxies
    assert "203.0.113.9" not in proxies


def test_no_configured_proxy_trusts_nobody(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)

    proxies = parse_trusted_proxies(get_settings())

    assert not proxies
    assert "172.18.0.1" not in proxies


@pytest.mark.parametrize("entry", ["not-an-ip", "10.0.0.0/33", "fe80::1%eth0"])
def test_an_unusable_entry_names_the_variable_that_carries_it(
    monkeypatch: pytest.MonkeyPatch, entry: str,
) -> None:
    """The operator has to find the wrong line in .env, so the failure says
    which variable it came from, not only which value was unusable."""
    monkeypatch.setenv("TRUSTED_PROXIES", entry)

    with pytest.raises(ValueError, match="TRUSTED_PROXIES"):
        parse_trusted_proxies(get_settings())

"""The deployment facts the auth machinery reads, and the rules they must meet."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from webauth.config import (
    MIN_SESSION_SECRET_CHARS,
    RateLimitKeyPrefixes,
    SessionKeyPrefixes,
    WebAuthConfig,
    install_web_auth_config,
    web_auth_config,
)
from webauth.proxies import TrustedProxies


def _config(**overrides: object) -> WebAuthConfig:
    defaults = {
        "session_secret": SecretStr("s" * MIN_SESSION_SECRET_CHARS),
        "redis": object(),
        "trusted_proxies": TrustedProxies.parse("172.16.0.0/12"),
        "session_key_prefixes": SessionKeyPrefixes(
            session="app:session", user_sessions="app:user_sessions",
        ),
        "rate_limit_key_prefixes": RateLimitKeyPrefixes(
            api="rl:ip", media="rl:ip-media", stream="rl:ip-stream",
        ),
        "allowed_hosts_exact": frozenset({"songmaker.example"}),
        "allowed_hosts_patterns": (re.compile(r"^[^:]+\.example(:\d+)?$"),),
        "session_max_age_seconds": 3600,
        "session_absolute_max_age_seconds": 86400,
        "login_rate_limit": 5,
        "login_lockout_threshold": 15,
        "login_lockout_window_seconds": 3600,
    }
    return WebAuthConfig(**{**defaults, **overrides})


def test_a_secret_shorter_than_the_floor_is_refused() -> None:
    """It signs every session cookie, so a guessable one hands out sessions."""
    short = SecretStr("s" * (MIN_SESSION_SECRET_CHARS - 1))

    with pytest.raises(ValueError, match="at least 32 characters"):
        _config(session_secret=short)


def test_a_secret_at_the_floor_is_accepted() -> None:
    assert _config().session_secret.get_secret_value() == "s" * MIN_SESSION_SECRET_CHARS


def test_the_signing_key_is_the_secret_the_signatures_take() -> None:
    assert _config().signing_key == b"s" * MIN_SESSION_SECRET_CHARS


def test_the_secret_never_shows_up_in_the_configuration_it_belongs_to() -> None:
    """A configuration lands in logs and tracebacks; the secret must not."""
    assert "s" * MIN_SESSION_SECRET_CHARS not in repr(_config())


def test_names_and_roles_default_to_the_conventional_ones() -> None:
    config = _config()

    assert config.session_cookie_name == "session_id"
    assert config.csrf_cookie_name == "csrf_token"
    assert config.csrf_header_name == "x-csrf-token"
    assert config.admin_role == "admin"
    assert config.user_role == "user"
    assert config.login_rate_window_seconds == 300


def test_a_deployment_may_name_the_cookies_itself() -> None:
    config = _config(session_cookie_name="sid", csrf_cookie_name="xsrf")

    assert config.session_cookie_name == "sid"
    assert config.csrf_cookie_name == "xsrf"


def test_a_request_reads_the_configuration_installed_on_its_application() -> None:
    config = _config()
    app = FastAPI()
    install_web_auth_config(app, config)

    @app.get("/config-secret-length")
    def config_secret_length(installed: WebAuthConfig = Depends(web_auth_config)) -> dict:
        return {"length": len(installed.signing_key)}

    with TestClient(app) as client:
        assert client.get("/config-secret-length").json() == {
            "length": MIN_SESSION_SECRET_CHARS,
        }


def test_the_configuration_cannot_be_changed_after_it_is_installed() -> None:
    """Every reader must see the same facts for the life of the process."""
    config = _config()

    with pytest.raises(AttributeError):
        config.session_max_age_seconds = 1

    assert replace(config, session_max_age_seconds=1).session_max_age_seconds == 1

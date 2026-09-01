"""Tests for auth utilities — password hashing, HMAC signing, password strength."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from songmaker_cli import auth
from songmaker_cli.auth import (
    BCRYPT_ROUNDS,
    MAX_ADDRESS_CHARS,
    MAX_FORWARDED_FOR_HOPS,
    MIN_PASSWORD_LENGTH,
    RATE_LIMIT_WINDOW_SECONDS,
    ROLE_ADMIN,
    TrustedProxies,
    check_password_strength,
    ensure_session_secret,
    generate_csrf_token,
    get_client_ip,
    hash_password,
    parse_trusted_proxies,
    sign_session_id,
    verify_csrf_token,
    verify_password,
    verify_session_cookie,
)
from songmaker_cli.settings import get_settings

_TEST_SECRET = b"a" * 64


def test_hash_and_verify_password() -> None:
    hashed = hash_password("testpassword123")
    assert hashed != "testpassword123"
    assert verify_password("testpassword123", hashed)


def test_verify_wrong_password() -> None:
    hashed = hash_password("correct-password")
    assert not verify_password("wrong-password", hashed)


def test_hash_produces_different_hashes() -> None:
    h1 = hash_password("same-password")
    h2 = hash_password("same-password")
    assert h1 != h2


def test_constants() -> None:
    assert BCRYPT_ROUNDS == 12
    assert ROLE_ADMIN == "admin"
    assert MIN_PASSWORD_LENGTH == 8
    assert RATE_LIMIT_WINDOW_SECONDS == 3600


def test_default_settings_values() -> None:
    settings = get_settings()
    assert settings.login_rate_limit == 5
    assert settings.session_max_age_seconds == 60 * 60 * 24 * 30
    assert settings.session_absolute_max_age_seconds == 60 * 60 * 24 * 90
    assert settings.generation_rate_limit_user == 3
    assert settings.scoring_rate_limit_user == 10
    assert settings.max_queue_depth == 100
    assert settings.max_user_active_jobs == 10
    assert settings.login_lockout_threshold == 15
    assert settings.login_lockout_window_seconds == 3600
    assert settings.max_concurrent_sessions_per_user == 10


# -- HMAC session signing ---------------------------------------------------


def test_sign_and_verify_session() -> None:
    signed = sign_session_id("my-session-token", _TEST_SECRET)
    assert "." in signed
    assert verify_session_cookie(signed, _TEST_SECRET) == "my-session-token"


def test_verify_rejects_tampered_signature() -> None:
    signed = sign_session_id("my-session-token", _TEST_SECRET)
    tampered = signed[:-4] + "XXXX"
    assert verify_session_cookie(tampered, _TEST_SECRET) is None


def test_verify_rejects_no_dot() -> None:
    assert verify_session_cookie("no-dot-here", _TEST_SECRET) is None


def test_verify_rejects_empty_parts() -> None:
    assert verify_session_cookie(".abc", _TEST_SECRET) is None
    assert verify_session_cookie("abc.", _TEST_SECRET) is None


def test_ensure_session_secret_returns_settings_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_SECRET", "c" * 64)
    result = ensure_session_secret(tmp_path)
    assert result == "c" * 64


def test_ensure_session_secret_rejects_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_SECRET", "short")
    with pytest.raises(RuntimeError, match="too short"):
        ensure_session_secret(tmp_path)


# -- Password strength -------------------------------------------------------


def test_common_password_rejected() -> None:
    with pytest.raises(ValueError, match="too common"):
        check_password_strength("password")


def test_low_entropy_rejected() -> None:
    with pytest.raises(ValueError, match="unique characters"):
        check_password_strength("aaaaaaaa")


def test_strong_password_accepted() -> None:
    assert check_password_strength("s3cur3P@ss!") == "s3cur3P@ss!"


# -- CSRF token binding ------------------------------------------------------


def test_generate_csrf_token_deterministic() -> None:
    t1 = generate_csrf_token("session-abc", _TEST_SECRET)
    t2 = generate_csrf_token("session-abc", _TEST_SECRET)
    assert t1 == t2


def test_generate_csrf_token_differs_per_session() -> None:
    t1 = generate_csrf_token("session-1", _TEST_SECRET)
    t2 = generate_csrf_token("session-2", _TEST_SECRET)
    assert t1 != t2


def test_verify_csrf_token_valid() -> None:
    token = generate_csrf_token("my-session", _TEST_SECRET)
    assert verify_csrf_token(token, "my-session", _TEST_SECRET) is True


def test_verify_csrf_token_wrong_session() -> None:
    token = generate_csrf_token("session-a", _TEST_SECRET)
    assert verify_csrf_token(token, "session-b", _TEST_SECRET) is False


def test_verify_csrf_token_forged() -> None:
    assert verify_csrf_token("forged-token", "session-a", _TEST_SECRET) is False


def test_none_password_passes() -> None:
    assert check_password_strength(None) is None


# -- Trusted proxies ---------------------------------------------------------


@pytest.mark.parametrize(
    ("configured", "peer", "trusted"),
    [
        ("172.16.0.0/12", "172.18.0.1", True),
        ("172.16.0.0/12", "172.31.255.254", True),
        ("172.16.0.0/12", "10.0.0.1", False),
        ("10.0.0.1", "10.0.0.1", True),
        ("10.0.0.1", "10.0.0.2", False),
        ("10.0.0.1, 172.16.0.0/12", "172.18.0.1", True),
        ("10.0.0.1, 172.16.0.0/12", "10.0.0.1", True),
        ("10.0.0.1, 172.16.0.0/12", "203.0.113.9", False),
        ("172.16.0.0/12", "::ffff:172.18.0.1", True),
        ("2001:db8::/32", "2001:db8::5", True),
        ("2001:db8::/32", "172.18.0.1", False),
        ("172.16.0.0/12", "testclient", False),
        ("", "172.18.0.1", False),
    ],
)
def test_trusted_proxies_membership(configured: str, peer: str, trusted: bool) -> None:
    assert (peer in TrustedProxies.parse(configured)) is trusted


def test_parse_trusted_proxies_reads_configured_networks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.1, 172.16.0.0/12")
    proxies = parse_trusted_proxies()
    assert "10.0.0.1" in proxies
    assert "172.20.3.4" in proxies
    assert "203.0.113.9" not in proxies


def test_parse_trusted_proxies_empty_default_trusts_nobody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    proxies = parse_trusted_proxies()
    assert not proxies
    assert "172.18.0.1" not in proxies


@pytest.mark.parametrize("entry", ["not-an-ip", "10.0.0.0/33", "10.0.0.1/24"])
def test_parse_trusted_proxies_rejects_unparsable_entry(
    monkeypatch: pytest.MonkeyPatch, entry: str,
) -> None:
    monkeypatch.setenv("TRUSTED_PROXIES", entry)
    with pytest.raises(ValueError, match="TRUSTED_PROXIES"):
        parse_trusted_proxies()


def test_parse_trusted_proxies_rejects_a_zone_scoped_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zone is local to one host and vanishes when an address is matched
    against a network, so the entry would silently widen to every interface."""
    monkeypatch.setenv("TRUSTED_PROXIES", "fe80::1%eth0")
    with pytest.raises(ValueError, match="zone"):
        parse_trusted_proxies()


# -- get_client_ip -----------------------------------------------------------

_PROXY_NETWORK = "172.16.0.0/12"
_TRUSTED_PEER = "172.18.0.1"
_TRUSTED_HOP = "172.18.0.9"
_CLIENT = "203.0.113.7"
_CLIENT_AT_THE_HOP_BOUND = ", ".join(
    [_CLIENT, *[_TRUSTED_HOP] * (MAX_FORWARDED_FOR_HOPS - 1)],
)
_CLIENT_BEYOND_THE_HOP_BOUND = ", ".join(
    [_CLIENT, *[_TRUSTED_HOP] * MAX_FORWARDED_FOR_HOPS],
)


@pytest.mark.parametrize(
    ("forwarded_for", "expected"),
    [
        pytest.param([], _TRUSTED_PEER, id="no header at all"),
        pytest.param([_CLIENT], _CLIENT, id="single hop"),
        pytest.param(
            [f"{_CLIENT}, {_TRUSTED_HOP}"], _CLIENT, id="rightmost untrusted hop",
        ),
        pytest.param(
            [_CLIENT, _TRUSTED_HOP], _CLIENT, id="chain split across fields",
        ),
        pytest.param(
            ["10.9.9.9", _CLIENT], _CLIENT, id="a later field is not hidden by the first",
        ),
        pytest.param(
            [f"{_TRUSTED_HOP}, 172.18.0.8"], _TRUSTED_PEER, id="every hop trusted",
        ),
        pytest.param(["   "], _TRUSTED_PEER, id="whitespace only"),
        pytest.param([""], _TRUSTED_PEER, id="empty header"),
        pytest.param([f"{_CLIENT}, "], _TRUSTED_PEER, id="empty entry right of the client"),
        pytest.param([f", {_CLIENT}"], _CLIENT, id="empty entry left of the client"),
        pytest.param(["garbage"], _TRUSTED_PEER, id="not an address"),
        pytest.param(
            [f"garbage, {_CLIENT}, {_TRUSTED_HOP}"], _CLIENT,
            id="poisoned prefix left of a trusted hop",
        ),
        pytest.param(
            ["garbage", _CLIENT], _CLIENT, id="poisoned prefix in an earlier field",
        ),
        pytest.param([f"{_CLIENT}:443"], _TRUSTED_PEER, id="address with a port"),
        pytest.param(["fe80::1%eth0"], _TRUSTED_PEER, id="zone-scoped hop"),
        pytest.param([f"::ffff:{_CLIENT}"], _CLIENT, id="IPv4-mapped hop"),
        pytest.param(["2001:0DB8:0000::0001"], "2001:db8::1", id="uncompressed IPv6 hop"),
        pytest.param([_CLIENT_AT_THE_HOP_BOUND], _CLIENT, id="client at the hop bound"),
        pytest.param(
            [_CLIENT_BEYOND_THE_HOP_BOUND], _TRUSTED_PEER, id="client beyond the hop bound",
        ),
    ],
)
def test_client_ip_behind_a_trusted_proxy(
    forwarded_for: list[str], expected: str,
) -> None:
    """The chain is read from the right, where our own proxies appended.

    The first hop no trusted proxy vouches for is the client; entries further
    left are never read. When the readable part names nobody the request keys
    on the peer, because an empty or nonsense identity binds a session and
    buys a rate-limit budget.
    """
    proxies = TrustedProxies.parse(_PROXY_NETWORK)
    assert get_client_ip(_TRUSTED_PEER, forwarded_for, proxies) == expected


def test_a_poisoned_prefix_cannot_move_a_client_onto_the_gateway_identity() -> None:
    """A client's own address is appended after whatever it sent, never before.

    So junk it writes sits left of that entry and is never read: it keeps its
    own rate-limit key instead of escaping onto the peer's, which every other
    visitor behind the same gateway shares. Junk to the right of the client is
    a different story — there the chain says nothing believable, and the
    request keys on the peer.
    """
    proxies = TrustedProxies.parse(_PROXY_NETWORK)
    assert get_client_ip(_TRUSTED_PEER, [f"garbage, {_CLIENT}"], proxies) == _CLIENT
    assert get_client_ip(_TRUSTED_PEER, [f"{_CLIENT}, garbage"], proxies) == _TRUSTED_PEER


class _CountedChain(str):
    """A header field that records every piece ever cut out of it.

    A chain is read from the right and only as far as the answer needs, so the
    pieces it hands out are what a huge header actually costs.
    """

    pieces: list[str]

    def __new__(cls, value: str) -> _CountedChain:
        chain = super().__new__(cls, value)
        chain.pieces = []
        return chain

    def split(self, sep: str | None = None, maxsplit: int = -1) -> list[str]:
        pieces = super().split(sep, maxsplit)
        self.pieces.extend(pieces)
        return pieces

    def __getitem__(self, key: int | slice) -> str:
        piece = super().__getitem__(key)
        self.pieces.append(piece)
        return piece


_HOPS_BEYOND_ANY_DEPLOYMENT = 10_000


@pytest.mark.parametrize(
    ("chain", "expected"),
    [
        pytest.param(
            [*[_TRUSTED_HOP] * _HOPS_BEYOND_ANY_DEPLOYMENT, _CLIENT], _CLIENT,
            id="the client sits at the right end",
        ),
        pytest.param(
            [_TRUSTED_HOP] * _HOPS_BEYOND_ANY_DEPLOYMENT, _TRUSTED_PEER,
            id="every read hop is trusted",
        ),
    ],
)
def test_a_huge_chain_costs_only_the_entries_it_reads(
    chain: list[str], expected: str,
) -> None:
    """A client may send as many entries as the header size allows, and the
    hop bound must limit the work rather than only the parsing: the entries
    left of the answer are never cut out of the field at all."""
    header_field = _CountedChain(", ".join(chain))
    proxies = TrustedProxies.parse(_PROXY_NETWORK)
    assert get_client_ip(_TRUSTED_PEER, [header_field], proxies) == expected
    assert len(header_field.pieces) <= MAX_FORWARDED_FOR_HOPS + 1


def test_an_entry_too_long_to_be_an_address_is_never_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No address is written in more than 45 characters, so longer text names
    nobody either way — but handing it to ipaddress would cut it into thousands
    of pieces along its dots, the very cost the bounded scan avoids."""
    parsed_hosts: list[str] = []
    parse_address = auth.ip_address

    def record_parse(host: str) -> auth.IpAddress:
        parsed_hosts.append(host)
        return parse_address(host)

    monkeypatch.setattr(auth, "ip_address", record_parse)
    proxies = TrustedProxies.parse(_PROXY_NETWORK)
    entry_of_nothing_but_separators = "1." * _HOPS_BEYOND_ANY_DEPLOYMENT

    assert get_client_ip(
        _TRUSTED_PEER, [entry_of_nothing_but_separators], proxies,
    ) == _TRUSTED_PEER
    assert all(len(host) <= MAX_ADDRESS_CHARS for host in parsed_hosts)


@pytest.mark.parametrize(
    "forwarded_for",
    [
        pytest.param(["garbage"], id="an entry that is not an address"),
        pytest.param(
            [_CLIENT_BEYOND_THE_HOP_BOUND], id="more trusted hops than the bound",
        ),
    ],
)
def test_a_chain_that_names_nobody_is_logged(
    forwarded_for: list[str], caplog: pytest.LogCaptureFixture,
) -> None:
    """Keying on the peer pools unrelated visitors into one budget, so a chain
    the proxy should have written correctly is a fault to see, not a default."""
    proxies = TrustedProxies.parse(_PROXY_NETWORK)
    with caplog.at_level(logging.WARNING, logger="songmaker_cli.auth"):
        assert get_client_ip(_TRUSTED_PEER, forwarded_for, proxies) == _TRUSTED_PEER
    assert [record.levelno for record in caplog.records] == [logging.WARNING]


def test_client_ip_ignores_a_chain_from_an_untrusted_peer() -> None:
    proxies = TrustedProxies.parse(_PROXY_NETWORK)
    assert get_client_ip("203.0.113.50", ["10.9.9.9"], proxies) == "203.0.113.50"


def test_client_ip_ignores_a_chain_when_no_proxy_is_configured() -> None:
    assert get_client_ip("1.2.3.4", ["5.6.7.8", "9.10.11.12"], TrustedProxies()) == "1.2.3.4"


def test_client_ip_canonicalizes_an_ipv4_mapped_peer() -> None:
    """Same client, one identity — otherwise a form switch doubles the budget."""
    proxies = TrustedProxies.parse(_PROXY_NETWORK)
    assert get_client_ip("::ffff:203.0.113.50", [], proxies) == "203.0.113.50"


def test_client_ip_of_a_peer_that_is_not_an_address() -> None:
    proxies = TrustedProxies.parse(_PROXY_NETWORK)
    assert get_client_ip("testclient", ["203.0.113.7"], proxies) == "testclient"

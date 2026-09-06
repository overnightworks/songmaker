"""Which peer may name a client, and the identity that follows from the chain."""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from webauth_arrangement import a_web_auth_config

from webauth import proxies
from webauth.config import install_web_auth_config
from webauth.proxies import (
    MAX_ADDRESS_CHARS,
    MAX_FORWARDED_FOR_HOPS,
    TrustedProxies,
    get_client_ip,
)

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


@pytest.mark.parametrize("entry", ["not-an-ip", "10.0.0.0/33", "10.0.0.1/24"])
def test_parsing_rejects_an_entry_that_is_not_a_network(entry: str) -> None:
    with pytest.raises(ValueError, match="not an IP address or CIDR network"):
        TrustedProxies.parse(entry)


def test_parsing_rejects_a_zone_scoped_entry() -> None:
    """A zone is local to one host and vanishes when an address is matched
    against a network, so the entry would silently widen to every interface."""
    with pytest.raises(ValueError, match="zone"):
        TrustedProxies.parse("fe80::1%eth0")


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
    trusted = TrustedProxies.parse(_PROXY_NETWORK)
    assert get_client_ip(_TRUSTED_PEER, forwarded_for, trusted) == expected


def test_a_poisoned_prefix_cannot_move_a_client_onto_the_gateway_identity() -> None:
    """A client's own address is appended after whatever it sent, never before.

    So junk it writes sits left of that entry and is never read: it keeps its
    own rate-limit key instead of escaping onto the peer's, which every other
    visitor behind the same gateway shares. Junk to the right of the client is
    a different story — there the chain says nothing believable, and the
    request keys on the peer.
    """
    trusted = TrustedProxies.parse(_PROXY_NETWORK)
    assert get_client_ip(_TRUSTED_PEER, [f"garbage, {_CLIENT}"], trusted) == _CLIENT
    assert get_client_ip(_TRUSTED_PEER, [f"{_CLIENT}, garbage"], trusted) == _TRUSTED_PEER


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
    trusted = TrustedProxies.parse(_PROXY_NETWORK)
    assert get_client_ip(_TRUSTED_PEER, [header_field], trusted) == expected
    assert len(header_field.pieces) <= MAX_FORWARDED_FOR_HOPS + 1


def test_an_entry_too_long_to_be_an_address_is_never_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No address is written in more than 45 characters, so longer text names
    nobody either way — but handing it to ipaddress would cut it into thousands
    of pieces along its dots, the very cost the bounded scan avoids."""
    parsed_hosts: list[str] = []
    parse_address = proxies.ip_address

    def record_parse(host: str) -> proxies.IpAddress:
        parsed_hosts.append(host)
        return parse_address(host)

    monkeypatch.setattr(proxies, "ip_address", record_parse)
    trusted = TrustedProxies.parse(_PROXY_NETWORK)
    entry_of_nothing_but_separators = "1." * _HOPS_BEYOND_ANY_DEPLOYMENT

    assert get_client_ip(
        _TRUSTED_PEER, [entry_of_nothing_but_separators], trusted,
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
    trusted = TrustedProxies.parse(_PROXY_NETWORK)
    with caplog.at_level(logging.WARNING, logger="webauth.proxies"):
        assert get_client_ip(_TRUSTED_PEER, forwarded_for, trusted) == _TRUSTED_PEER
    assert [record.levelno for record in caplog.records] == [logging.WARNING]


def test_client_ip_ignores_a_chain_from_an_untrusted_peer() -> None:
    trusted = TrustedProxies.parse(_PROXY_NETWORK)
    assert get_client_ip("203.0.113.50", ["10.9.9.9"], trusted) == "203.0.113.50"


def test_client_ip_ignores_a_chain_when_no_proxy_is_configured() -> None:
    assert get_client_ip("1.2.3.4", ["5.6.7.8", "9.10.11.12"], TrustedProxies()) == "1.2.3.4"


def test_client_ip_canonicalizes_an_ipv4_mapped_peer() -> None:
    """Same client, one identity — otherwise a form switch doubles the budget."""
    trusted = TrustedProxies.parse(_PROXY_NETWORK)
    assert get_client_ip("::ffff:203.0.113.50", [], trusted) == "203.0.113.50"


def test_client_ip_of_a_peer_that_is_not_an_address() -> None:
    trusted = TrustedProxies.parse(_PROXY_NETWORK)
    assert get_client_ip("testclient", ["203.0.113.7"], trusted) == "testclient"


def _client_ip_app() -> FastAPI:
    app = FastAPI()

    @app.get("/client-ip")
    def client_ip(request: Request) -> dict:
        return {"ip": proxies.resolve_client_ip(request)}

    return app


def test_the_client_identity_of_a_configured_application() -> None:
    app = _client_ip_app()
    install_web_auth_config(app, a_web_auth_config())

    with TestClient(app, client=(_TRUSTED_PEER, 55000)) as client:
        response = client.get("/client-ip", headers={"x-forwarded-for": _CLIENT})

    assert response.json() == {"ip": _CLIENT}


def test_an_application_without_a_configuration_names_nobody() -> None:
    """Guessing here would hand a forged header the identity that binds a
    session and buys a rate-limit budget, so a missing configuration has to
    stop the request instead of falling back to the peer."""
    app = _client_ip_app()

    with (
        TestClient(app, client=(_TRUSTED_PEER, 55000)) as client,
        pytest.raises(RuntimeError, match="install_web_auth_config"),
    ):
        client.get("/client-ip", headers={"x-forwarded-for": _CLIENT})

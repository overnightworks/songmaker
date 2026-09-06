"""Which peers may name a client, and the client identity that follows from it."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from ipaddress import (
    IPv4Address,
    IPv4Network,
    IPv6Address,
    IPv6Network,
    ip_address,
    ip_network,
)
from itertools import islice
from typing import TYPE_CHECKING, Final

from webauth.config import web_auth_config

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from starlette.requests import Request

log = logging.getLogger(__name__)

IpAddress = IPv4Address | IPv6Address
IpNetwork = IPv4Network | IPv6Network
FORWARDED_FOR_HEADER: Final[str] = "x-forwarded-for"
FORWARDED_PROTO_HEADER: Final[str] = "x-forwarded-proto"
HTTPS_SCHEME: Final[str] = "https"

# The identity used when the connection has no address at all (an ASGI
# transport without a client, as in tests). It is not an IP, so it is never
# trusted and never matches a configured network.
UNKNOWN_CLIENT_IP: Final[str] = "unknown"

# A zone identifier ("fe80::1%eth0") is meaningful only on the host that owns
# the interface, and Python compares a scoped address against a network by its
# numeric value alone -- the zone silently disappears from the decision. So no
# address carrying one is ever matched or used as an identity here.
ZONE_SEPARATOR: Final[str] = "%"

# The longest an address can be written is an IPv6 with an embedded IPv4 tail:
# "0000:0000:0000:0000:0000:0000:255.255.255.255", 45 characters. Longer text
# is not an address, and saying so without parsing keeps a header field full of
# dots or colons from being cut into thousands of pieces inside ipaddress. This
# is not a limit on what may be an identity -- nothing it rejects could parse.
MAX_ADDRESS_CHARS: Final[int] = 45

# How many hops of a chain are ever read. Only the entries our own proxies
# appended decide the identity, and a real deployment appends three: the CDN
# edge, the tunnel, the container gateway. Reaching 16 means the server sits
# behind more trusted proxies than anyone configured -- the public client
# cannot cause it, because everything it writes lands left of the hop that
# decides; a caller on the host itself reaches the server through the bridge
# gateway, a trusted pass-through hop, and therefore can.
MAX_FORWARDED_FOR_HOPS: Final[int] = 16


@dataclass(frozen=True)
class TrustedProxies:
    """The peers whose forwarding headers this server believes.

    Every entry is an IP network, so a CIDR block from configuration matches
    each address inside it and a bare address matches only itself. A peer
    whose address is not an IP at all (a unix socket, a test transport) is
    never trusted, and no entries means no peer is trusted.
    """

    networks: tuple[IpNetwork, ...] = ()

    @classmethod
    def parse(cls, raw: str) -> TrustedProxies:
        """Build from a CSV of addresses and CIDR blocks. Raises on garbage."""
        entries = (entry.strip() for entry in raw.split(","))
        return cls(tuple(_proxy_network(entry) for entry in entries if entry))

    def trusts(self, address: IpAddress) -> bool:
        return any(address in network for network in self.networks)

    def __contains__(self, host: str) -> bool:
        address = _canonical_address(host)
        return address is not None and self.trusts(address)

    def __bool__(self) -> bool:
        return bool(self.networks)


def _proxy_network(entry: str) -> IpNetwork:
    if ZONE_SEPARATOR in entry:
        raise ValueError(
            f"Trusted proxy entry {entry!r} carries an interface zone: a zone is "
            "local to one host and is ignored when an address is matched against a "
            "network, so it would widen the entry to every interface. Configure the "
            "address or network without it.",
        )
    try:
        return ip_network(entry)
    except ValueError as exc:
        raise ValueError(
            f"Trusted proxy entry {entry!r} is not an IP address or CIDR network: {exc}",
        ) from exc


def _canonical_address(host: str) -> IpAddress | None:
    """The one form of ``host`` every decision keys on, or None if it is not an IP.

    An IPv4-mapped IPv6 address collapses to its IPv4 form, so a client cannot
    hold two per-IP budgets by switching notation.
    """
    if len(host) > MAX_ADDRESS_CHARS or ZONE_SEPARATOR in host:
        return None
    try:
        address = ip_address(host)
    except ValueError:
        return None
    if isinstance(address, IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def _canonical_host(host: str) -> str:
    address = _canonical_address(host)
    return host if address is None else str(address)


def _forwarded_entries(header_values: Sequence[str]) -> Iterator[str]:
    """The entries of a forwarded header from right to left, newest hop first.

    A chain may arrive split across several header fields; together they are
    one ordered list, so the fields are walked back to front as well -- reading
    only one of them would let a client hide hops in another.

    Each entry is cut out by index from the right rather than by splitting the
    field, so a header carrying thousands of separators costs only the handful
    of entries the caller actually reads.
    """
    for header_value in reversed(header_values):
        end = len(header_value)
        while True:
            separator = header_value.rfind(",", 0, end)
            yield header_value[separator + 1:end].strip()
            if separator < 0:
                break
            end = separator


def _client_from_chain(
    entries: Iterator[str], trusted_proxies: TrustedProxies,
) -> IpAddress | None:
    """The rightmost hop no trusted proxy vouches for, or None when there is none.

    ``entries`` starts at the hop our own proxy appended, and each trusted hop
    is stepped over until one that is not trusted appears: that is the client.
    Whatever a client writes into the header itself ends up left of the entry
    its proxy appended for it, so it is never read -- a poisoned prefix cannot
    change this answer. An entry that is not an address, or a chain of trusted
    hops deeper than the deployment can plausibly be, names nobody; the entry
    is logged only as far as an address could reach, so a huge one identifies
    the fault without filling the log.
    """
    for entry in islice(entries, MAX_FORWARDED_FOR_HOPS):
        hop = _canonical_address(entry)
        if hop is None:
            log.warning(
                "X-Forwarded-For carries %r where the nearest proxy should have "
                "appended an address; keying this request on the direct peer.",
                entry[:MAX_ADDRESS_CHARS],
            )
            return None
        if not trusted_proxies.trusts(hop):
            return hop
    if next(entries, None) is not None:
        log.warning(
            "X-Forwarded-For names more than %d trusted hops in a row; keying this "
            "request on the direct peer.", MAX_FORWARDED_FOR_HOPS,
        )
    return None


def get_client_ip(
    peer: str, forwarded_for_fields: Sequence[str], trusted_proxies: TrustedProxies,
) -> str:
    """The client's identity: the rightmost hop no trusted proxy vouches for.

    Only a request arriving from a trusted peer may name a client other than
    the peer itself, and the chain is then read from the right, where our own
    proxies appended. A client cannot change that answer by prepending entries
    of its own: forged or not, they sit left of the one hop that decides. When
    no hop names anybody the request keys on the peer -- a truncated or empty
    header must never become somebody's identity, because that identity binds
    a session and buys a rate-limit budget.
    """
    if peer not in trusted_proxies:
        return _canonical_host(peer)
    client = _client_from_chain(_forwarded_entries(forwarded_for_fields), trusted_proxies)
    return _canonical_host(peer) if client is None else str(client)


def _peer_host(request: Request) -> str:
    return request.client.host if request.client else UNKNOWN_CLIENT_IP


def resolve_client_ip(request: Request) -> str:
    """The client identity of ``request`` -- the one owner of that decision."""
    return get_client_ip(
        _peer_host(request),
        request.headers.getlist(FORWARDED_FOR_HEADER),
        web_auth_config(request).trusted_proxies,
    )


def request_is_https(request: Request) -> bool:
    """Whether the client's own connection is HTTPS, forwarding included.

    Like the client address, a forwarded protocol counts only from a trusted
    peer and only in its rightmost value -- the one the closest proxy appended,
    cut out the same bounded way. A client that prepends its own
    ``X-Forwarded-Proto`` cannot outvote it.
    """
    if request.url.scheme == HTTPS_SCHEME:
        return True
    if _peer_host(request) not in web_auth_config(request).trusted_proxies:
        return False
    newest = next(_forwarded_entries(request.headers.getlist(FORWARDED_PROTO_HEADER)), "")
    return newest.lower() == HTTPS_SCHEME

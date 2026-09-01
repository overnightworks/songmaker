"""Authentication utilities — password hashing, session signing, constants."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
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

import bcrypt

from songmaker_cli.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from starlette.requests import Request

    from songmaker_cli.app_context import AppContext

log = logging.getLogger(__name__)

BCRYPT_ROUNDS = 12

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
            f"TRUSTED_PROXIES entry {entry!r} carries an interface zone: a zone is "
            "local to one host and is ignored when an address is matched against a "
            "network, so it would widen the entry to every interface. Configure the "
            "address or network without it.",
        )
    try:
        return ip_network(entry)
    except ValueError as exc:
        raise ValueError(
            f"TRUSTED_PROXIES entry {entry!r} is not an IP address or CIDR network: {exc}",
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


def parse_trusted_proxies() -> TrustedProxies:
    """Read TRUSTED_PROXIES from Settings. Raises at startup on an unparsable entry."""
    return TrustedProxies.parse(get_settings().trusted_proxies)


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
    ctx: AppContext = request.app.state.ctx
    return get_client_ip(
        _peer_host(request),
        request.headers.getlist(FORWARDED_FOR_HEADER),
        ctx.trusted_proxies,
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
    ctx: AppContext = request.app.state.ctx
    if _peer_host(request) not in ctx.trusted_proxies:
        return False
    newest = next(_forwarded_entries(request.headers.getlist(FORWARDED_PROTO_HEADER)), "")
    return newest.lower() == HTTPS_SCHEME


LOGIN_RATE_WINDOW_SECONDS = 300
RATE_LIMIT_WINDOW_SECONDS = 3600

ROLE_ADMIN = "admin"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "x-csrf-token"

MIN_PASSWORD_LENGTH = 8


_DUMMY_HASH = bcrypt.hashpw(b"dummy", bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def verify_password_constant_time(password: str, password_hash: str | None) -> bool:
    """Verify password, using a dummy hash if None to prevent timing oracle."""
    return bcrypt.checkpw(password.encode(), (password_hash or _DUMMY_HASH).encode())


# ── Password strength ──────────────────────────────────────────────

_COMMON_PASSWORDS = frozenset({
    "password", "12345678", "123456789", "1234567890", "qwerty123",
    "password1", "iloveyou", "sunshine1", "princess1", "football1",
    "trustno1", "letmein1", "baseball1", "abc12345", "monkey123",
    "dragon12", "michael1", "jennifer1", "superman1", "shadow12",
    "password123", "admin123", "welcome1", "changeme1", "passw0rd",
    "p@ssw0rd", "p@ssword", "abcd1234", "1q2w3e4r", "qwer1234",
    "asdfghjk", "zxcvbnm1", "11111111", "00000000", "12341234",
    "abcdefgh", "87654321", "master12", "access14", "charlie1",
    "qwerty12", "iloveu12", "starwars", "whatever", "computer",
    "corvette", "maverick", "steelers",
    "admin1234", "welcome123", "password12", "letmein12", "master123",
    "login123", "welcome12", "mustang1", "jordan23", "buster12",
    "ranger12", "batman12", "thomas12", "robert12", "soccer12",
    "hockey12", "hunter12", "george12", "andrew12", "harley12",
    "daniel12", "matthew1", "jessica1", "william1", "anthony1",
    "summer12", "winter12", "spring12", "autumn12", "january1",
    "february", "december", "saturday", "thursday", "midnight",
    "sunshine", "princess", "football", "baseball", "trustno12",
    "qwerty1234", "asdf1234", "zxcv1234", "q1w2e3r4", "1234qwer",
    "pass1234", "test1234", "temp1234", "user1234", "guest1234",
    "default1", "system12", "server12", "network1", "internet",
    "security", "password1234", "admin12345", "root1234", "toor1234",
    "samsung1", "ferrari1", "porsche1", "mercedes", "corvett1",
    "elephant", "giraffe1", "dolphins", "predator", "scorpion",
    "spiderman", "ironman1", "avengers", "deadpool", "thanos12",
    "iloveyou1", "iloveyou2", "loveyou1", "mylove12", "forever1",
    "diamond1", "crystal1", "rainbow1", "butterfly", "angelica",
    "carolina", "virginia", "colorado", "portland", "california",
    "newyork1", "london12", "paris123", "tokyo123", "berlin12",
    "samsung123", "apple123", "google12", "amazon12", "facebook",
    "twitter1", "youtube1", "spotify1", "netflix1", "linkedin",
    "sunshine123", "chocolate", "strawberry", "blueberry", "mountain",
    "password!", "p@ss1234", "p@$$w0rd", "pa$$word", "pa55word",
    "trustme1", "believe1", "freedom1", "justice1", "liberty1",
    "american", "patriots", "yankees1", "lakers12", "cowboys1",
    "packers1", "arsenal1", "chelsea1", "liverpool", "barcelona",
    "realmadrid", "juventus", "manchester",
    "summer2024", "summer2025", "summer2026", "winter2024", "winter2025",
    "spring2024", "spring2025", "spring2026", "welcome2024", "welcome2025",
    "january2024", "january2025", "january2026",
    "qwertyui", "asdfghjkl", "zxcvbnm12", "1qaz2wsx", "2wsx3edc",
    "qazwsxed", "q1w2e3r4t5", "1q2w3e4r5t",
})

MIN_UNIQUE_CHARS = 4


def check_password_strength(cls_or_value: str, *_args: object) -> str:
    """Pydantic-compatible validator: reject common and low-entropy passwords.

    Works both as a standalone function and as a Pydantic field_validator
    (which passes `cls` as first arg in classmethod mode, but we accept
    the value in either position via the *_args fallback).
    """
    password = cls_or_value
    if password is None:
        return password
    if password.lower() in _COMMON_PASSWORDS:
        raise ValueError("Password is too common — choose something less predictable")
    if len(set(password)) < MIN_UNIQUE_CHARS:
        raise ValueError(
            f"Password must contain at least {MIN_UNIQUE_CHARS} unique characters"
        )
    return password


# ── HMAC session signing ───────────────────────────────────────────


def ensure_session_secret(_output_dir_path: str | os.PathLike) -> str:
    """Return the validated session signing secret from Settings.

    Settings.session_secret is required (W1 contract). ``_output_dir_path``
    is kept for call-site compatibility — the previous file-based fallback
    is gone now that secrets must come from .env.
    """
    secret = get_settings().session_secret.get_secret_value()
    if len(secret) < 32:
        raise RuntimeError(
            "SESSION_SECRET is too short — must be at least 32 characters",
        )
    return secret


def sign_session_id(session_id: str, secret: bytes) -> str:
    """Return ``session_id.hmac_hex`` for use as a cookie value."""
    sig = hmac.new(secret, session_id.encode(), hashlib.sha256).hexdigest()
    return f"{session_id}.{sig}"


def verify_session_cookie(cookie_value: str, secret: bytes) -> str | None:
    """Verify the HMAC signature and return the raw session_id, or None."""
    if "." not in cookie_value:
        return None
    session_id, sig = cookie_value.rsplit(".", 1)
    if not session_id or not sig:
        return None
    expected = hmac.new(secret, session_id.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected):
        return session_id
    return None


def generate_csrf_token(session_id: str, secret: bytes) -> str:
    """Generate a CSRF token cryptographically bound to the session."""
    return hmac.new(secret, f"csrf:{session_id}".encode(), hashlib.sha256).hexdigest()


def verify_csrf_token(token: str, session_id: str, secret: bytes) -> bool:
    """Verify a CSRF token is valid for the given session."""
    expected = generate_csrf_token(session_id, secret)
    return hmac.compare_digest(token, expected)

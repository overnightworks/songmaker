"""A Keycloak stand-in for sign-in tests: an RS256 key, its key set and a token endpoint.

The sign-in routes run the real relying party; only its outbound calls are
replaced, so the ID token is verified exactly as in production.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from webauth.https_client import KeySetFetchError
from webauth.oidc import (
    TokenEndpointAnswer,
    TokenEndpointError,
    TokenRequest,
)
from webauth.web_auth import IssuerCalls

from songmaker_cli.settings import RealmSettings, get_settings

KEY_ID = "test-key"
RSA_PUBLIC_EXPONENT = 65537
RSA_KEY_BITS = 2048
ID_TOKEN_LIFETIME_SECONDS = 300
USER_ACCESS_TOKEN = "fake-user-access-token"
BACKCHANNEL_LOGOUT_EVENT = "http://schemas.openid.net/event/backchannel-logout"  # NOSONAR(S5332)


@dataclass(frozen=True)
class Person:
    """Who the realm vouches for at the next token exchange."""

    subject: str
    username: str = "someone"
    groups: tuple[str, ...] = ("/apps/songmaker",)
    refresh_token: str | None = None


@dataclass
class FakeIssuer:
    issuer: str
    client_id: str
    now: float = field(default_factory=time.time)
    unreachable: bool = False
    token_issuer: str | None = None
    person: Person | None = None
    _key: rsa.RSAPrivateKey = field(
        default_factory=lambda: rsa.generate_private_key(RSA_PUBLIC_EXPONENT, RSA_KEY_BITS),
    )
    _nonce_by_code: dict[str, str] = field(default_factory=dict)
    # What the next refresh-token grant answers: a new refresh token to rotate to, or the
    # issuer's error code instead of an access token. A grant the test never configures
    # answers the access token and keeps the refresh token.
    rotates_refresh_token_to: str | None = None
    refuses_refresh_with: str | None = None
    grants_seen: list[str] = field(default_factory=list)
    # Runs when a refresh-token grant arrives, before the realm answers it.
    before_renewal: Callable[[], None] | None = None

    def clock(self) -> float:
        return self.now

    def remember_authorization(self, authorization_url: str) -> tuple[str, str]:
        """Record the nonce an authorization URL asks for; return its state and a code."""
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(authorization_url).query)
        state, nonce = query["state"][0], query["nonce"][0]
        code = f"code-for-{state}"
        self._nonce_by_code[code] = nonce
        return state, code

    def key_set(self, _url: str) -> bytes:
        if self.unreachable:
            raise KeySetFetchError("the issuer is unreachable")
        jwk = json.loads(RSAAlgorithm.to_jwk(self._key.public_key()))
        return json.dumps({"keys": [{**jwk, "kid": KEY_ID, "alg": "RS256", "use": "sig"}]}).encode()

    def token_answer(self, request: TokenRequest) -> TokenEndpointAnswer:
        if self.unreachable:
            raise TokenEndpointError("the issuer is unreachable")
        grant = request.form["grant_type"]
        self.grants_seen.append(grant)
        if grant == "refresh_token":
            return self._renewal()
        assert self.person is not None, "the test names who signs in"
        nonce = self._nonce_by_code[request.form["code"]]
        claims = {
            "iss": self.token_issuer or self.issuer,
            "aud": self.client_id,
            "sub": self.person.subject,
            "preferred_username": self.person.username,
            "groups": list(self.person.groups),
            "nonce": nonce,
            "iat": int(self.now),
            "exp": int(self.now) + ID_TOKEN_LIFETIME_SECONDS,
        }
        id_token = jwt.encode(claims, self._key, algorithm="RS256", headers={"kid": KEY_ID})
        answer = {"id_token": id_token}
        if self.person.refresh_token is not None:
            answer["refresh_token"] = self.person.refresh_token
        return TokenEndpointAnswer(status=200, body=json.dumps(answer).encode())

    def _renewal(self) -> TokenEndpointAnswer:
        if self.before_renewal is not None:
            self.before_renewal()
        if self.refuses_refresh_with is not None:
            body = json.dumps({"error": self.refuses_refresh_with}).encode()
            return TokenEndpointAnswer(status=400, body=body)
        answer = {"access_token": USER_ACCESS_TOKEN, "token_type": "Bearer"}
        if self.person is not None:
            answer["id_token"] = self._renewed_id_token(self.person)
        if self.rotates_refresh_token_to is not None:
            answer["refresh_token"] = self.rotates_refresh_token_to
        return TokenEndpointAnswer(status=200, body=json.dumps(answer).encode())

    def _renewed_id_token(self, person: Person) -> str:
        """The ID token a refresh grant answers: the person's current groups, and no nonce."""
        claims = {
            "iss": self.token_issuer or self.issuer,
            "aud": self.client_id,
            "sub": person.subject,
            "preferred_username": person.username,
            "groups": list(person.groups),
            "iat": int(self.now),
            "exp": int(self.now) + ID_TOKEN_LIFETIME_SECONDS,
        }
        return jwt.encode(claims, self._key, algorithm="RS256", headers={"kid": KEY_ID})

    def logout_token(self, subject: str, **overrides: object) -> str:
        """A Logout Token the realm would send; ``overrides`` replace or (None) drop claims."""
        claims: dict[str, object] = {
            "iss": self.issuer,
            "aud": self.client_id,
            "sub": subject,
            "iat": int(self.now),
            "exp": int(self.now) + ID_TOKEN_LIFETIME_SECONDS,
            "jti": "logout-token-id",
            "events": {BACKCHANNEL_LOGOUT_EVENT: {}},
        }
        claims.update(overrides)
        return self.sign({name: value for name, value in claims.items() if value is not None})

    def sign(
        self,
        claims: dict[str, object],
        *,
        token_type: str = "logout+jwt",
        key: rsa.RSAPrivateKey | None = None,
    ) -> str:
        return jwt.encode(
            claims,
            key or self._key,
            algorithm="RS256",
            headers={"kid": KEY_ID, "typ": token_type},
        )

    def serve(self, app) -> None:
        """Make this issuer the realm the app's relying party talks to, and its clock the app's."""
        app.state.issuer_slot.issuer = self


@dataclass
class IssuerSlot:
    """The realm one test app's relying party talks to, which a test fills with a FakeIssuer.

    The app is built with the slot's calls; the relying party is bound at build time, so the slot
    is what lets a test name its issuer afterwards. Until it does, the realm is unreachable.
    """

    issuer: FakeIssuer | None = None

    def calls(self) -> IssuerCalls:
        return IssuerCalls(
            post_token_request=self._post_token_request,
            fetch_key_set=self._fetch_key_set,
            monotonic_clock=self.clock,
        )

    def clock(self) -> float:
        return time.time() if self.issuer is None else self.issuer.clock()

    def _post_token_request(self, request: TokenRequest) -> TokenEndpointAnswer:
        if self.issuer is None:
            raise TokenEndpointError("no issuer is served")
        return self.issuer.token_answer(request)

    def _fetch_key_set(self, url: str) -> bytes:
        if self.issuer is None:
            raise KeySetFetchError("no issuer is served")
        return self.issuer.key_set(url)


def a_fake_issuer() -> FakeIssuer:
    settings = get_settings()
    assert settings.oidc_issuer
    return FakeIssuer(settings.oidc_issuer, RealmSettings().client_id)



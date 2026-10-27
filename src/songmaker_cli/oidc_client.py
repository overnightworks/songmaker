"""songmaker's relying party at the Keycloak realm, and who it admits.

Built once where the web app is created, so workers and the migrate step start
without the realm's settings. A missing or unreadable secret file stops the web
app and names only the path, never the secret.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, overload

from fastapi import HTTPException
from pydantic import SecretStr
from webauth.https_client import fetch_key_set_over_https
from webauth.oidc import OidcClientConfig, OidcRelyingParty
from webauth.oidc_login import AdmissionConfig
from webauth.oidc_transport import post_token_request_over_https

from songmaker_cli.api_helpers import resolve_public_base_url
from songmaker_cli.constants import (
    OIDC_ADMIN_GROUP,
    OIDC_CALLBACK_PATH,
    OIDC_LEEWAY_SECONDS,
    OIDC_LOGIN_GROUP,
    SIGNED_OUT_PATH,
)

if TYPE_CHECKING:
    from pathlib import Path

    from songmaker_cli.settings import Settings

_REALM_ENDPOINT_PREFIX = "protocol/openid-connect"


@overload
def normalised_oidc_issuer(configured_issuer: str) -> str: ...
@overload
def normalised_oidc_issuer(configured_issuer: str | None) -> str | None: ...
def normalised_oidc_issuer(configured_issuer: str | None) -> str | None:
    """The configured issuer in the form tokens carry it: no trailing slash."""
    return configured_issuer.rstrip("/") if configured_issuer else None


def read_client_secret(secret_file: Path) -> SecretStr:
    try:
        secret = secret_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        raise ValueError(f"OIDC_CLIENT_SECRET_FILE {secret_file} cannot be read") from None
    if not secret:
        raise ValueError(f"OIDC_CLIENT_SECRET_FILE {secret_file} is empty")
    return SecretStr(secret)


def build_oidc_client_config(settings: Settings) -> OidcClientConfig:
    if not settings.oidc_issuer or not settings.oidc_client_id:
        raise ValueError("OIDC_ISSUER and OIDC_CLIENT_ID are required to serve the web app")
    if settings.oidc_client_secret_file is None:
        raise ValueError("OIDC_CLIENT_SECRET_FILE is required to serve the web app")
    try:
        public_base_url = resolve_public_base_url()
    except HTTPException as error:
        raise ValueError(f"PUBLIC_BASE_URL is required for sign-in: {error.detail}") from None
    issuer = normalised_oidc_issuer(settings.oidc_issuer)
    endpoints = f"{issuer}/{_REALM_ENDPOINT_PREFIX}"
    return OidcClientConfig(
        issuer=issuer,
        authorization_endpoint=f"{endpoints}/auth",
        token_endpoint=f"{endpoints}/token",
        jwks_url=f"{endpoints}/certs",
        end_session_endpoint=f"{endpoints}/logout",
        client_id=settings.oidc_client_id,
        client_secret=read_client_secret(settings.oidc_client_secret_file),
        redirect_uri=f"{public_base_url}{OIDC_CALLBACK_PATH}",
        post_logout_redirect_uri=f"{public_base_url}{SIGNED_OUT_PATH}",
        leeway_seconds=OIDC_LEEWAY_SECONDS,
    )


def build_relying_party(client_config: OidcClientConfig) -> OidcRelyingParty:
    return OidcRelyingParty(
        client_config,
        post_token_request=post_token_request_over_https,
        fetch_key_set=fetch_key_set_over_https,
        wall_clock=time.time,
        monotonic_clock=time.monotonic,
    )


def build_admission_config(client_config: OidcClientConfig) -> AdmissionConfig:
    return AdmissionConfig(
        bound_issuer=client_config.issuer,
        login_group=OIDC_LOGIN_GROUP,
        admin_group=OIDC_ADMIN_GROUP,
    )


@dataclass(frozen=True)
class OidcSignIn:
    """What the sign-in routes need, built once and kept on the app."""

    relying_party: OidcRelyingParty
    admission: AdmissionConfig


def build_oidc_sign_in(settings: Settings) -> OidcSignIn:
    client_config = build_oidc_client_config(settings)
    return OidcSignIn(
        relying_party=build_relying_party(client_config),
        admission=build_admission_config(client_config),
    )

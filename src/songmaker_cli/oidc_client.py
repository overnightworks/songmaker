"""songmaker's relying party at the Keycloak realm, and who it admits.

Built once where the web app is created, so workers, which never create the web
app, start without the realm's settings. A missing or unreadable secret file stops the web
app and names only the path, never the secret.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, overload

from pydantic import SecretStr
from webauth.admission import AdmissionConfig
from webauth.middleware.bearer_gate import BearerGate, PersonPaths, ProtectedResource
from webauth.oidc import OidcClientConfig
from webauth.policies import AuthorizedParties, PathRules

from songmaker_cli.constants import (
    OIDC_CALLBACK_PATH,
    OIDC_LEEWAY_SECONDS,
    SIGNED_OUT_PATH,
)
from songmaker_cli.request_policies import API_PATH_PREFIX, MEDIA_PATH_PREFIX

if TYPE_CHECKING:
    from pathlib import Path

    from songmaker_cli.settings import RealmSettings, Settings

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


def build_oidc_client_config(settings: Settings, realm: RealmSettings) -> OidcClientConfig:
    if not settings.oidc_issuer:
        raise ValueError("OIDC_ISSUER is required to serve the web app")
    if settings.oidc_client_secret_file is None:
        raise ValueError("OIDC_CLIENT_SECRET_FILE is required to serve the web app")
    if not settings.public_base_url:
        raise ValueError("PUBLIC_BASE_URL is required to serve the web app")
    issuer = normalised_oidc_issuer(settings.oidc_issuer)
    endpoints = f"{issuer}/{_REALM_ENDPOINT_PREFIX}"
    return OidcClientConfig(
        issuer=issuer,
        authorization_endpoint=f"{endpoints}/auth",
        token_endpoint=f"{endpoints}/token",
        jwks_url=f"{endpoints}/certs",
        end_session_endpoint=f"{endpoints}/logout",
        client_id=realm.client_id,
        client_secret=read_client_secret(settings.oidc_client_secret_file),
        redirect_uri=f"{settings.public_base_url}{OIDC_CALLBACK_PATH}",
        post_logout_redirect_uri=f"{settings.public_base_url}{SIGNED_OUT_PATH}",
        leeway_seconds=OIDC_LEEWAY_SECONDS,
    )


def build_admission_config(
    client_config: OidcClientConfig, realm: RealmSettings,
) -> AdmissionConfig:
    return AdmissionConfig(
        bound_issuer=client_config.issuer,
        login_group=realm.login_group,
        admin_group=realm.admin_group,
    )


def build_bearer_gate(
    settings: Settings,
    resource: ProtectedResource | None = None,
) -> BearerGate | None:
    """The gate that admits a token: a person's on the person paths while a client is named,
    and the person's own agent's at ``resource``; none while neither is configured."""
    if not settings.token_client_ids and resource is None:
        return None
    person_paths = (
        PersonPaths(
            PathRules(prefixes=(API_PATH_PREFIX, MEDIA_PATH_PREFIX)),
            AuthorizedParties(settings.token_client_ids),
        )
        if settings.token_client_ids
        else None
    )
    return BearerGate(person_paths=person_paths, resource=resource)

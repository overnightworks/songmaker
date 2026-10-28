"""Auth endpoints: the signed-in account, and the composition of webauth's sign-in routes."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from webauth.oidc import OidcRefusal
from webauth.ports import AuthenticatedUser
from webauth.sign_in_routes import (
    RefusalPage,
    SignInRefusal,
    install_sign_in_routes,
)

from songmaker_cli.api_helpers import resolve_public_base_url
from songmaker_cli.api_models import AuthMeResponse
from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.auth_stores import DatabaseSignInTransaction
from songmaker_cli.constants import NO_ACCESS_PATH
from songmaker_cli.oidc_client import normalised_oidc_issuer
from songmaker_cli.request_policies import SIGN_IN_PATHS
from songmaker_cli.settings import DEFAULT_SERVER_PORT, get_settings

if TYPE_CHECKING:
    from webauth.oidc import OidcRelyingParty

log = logging.getLogger(__name__)

SIGN_IN_FAILED_STATUS: int = 403
# Shown on the logout page only where no script runs; the account menu words the same button.
LOGOUT_BUTTON_LABEL: Final[str] = "Sign out"

router = APIRouter(prefix="/auth", tags=["auth"])


class BackchannelHostMismatch(Exception):  # noqa: N818 -- answered by a handler, never an error
    """The back-channel call carries a Host other than the private network's."""


def backchannel_logout_host() -> str:
    """The Host the realm's call carries: the public host on the container port."""
    return f"{urlsplit(resolve_public_base_url()).hostname}:{DEFAULT_SERVER_PORT}"


def _require_backchannel_host(request: Request) -> None:
    """Keycloak's back-channel logout; only the private network's Host reaches it."""
    if request.headers.get("host") != backchannel_logout_host():
        raise BackchannelHostMismatch


def _answer_backchannel_host_mismatch(_request: Request, _exc: Exception) -> Response:
    return Response(status_code=404)


def _relying_party(request: Request) -> OidcRelyingParty:
    return request.app.state.oidc_sign_in.relying_party


def _refuse_sign_in(request: Request, refusal: SignInRefusal) -> Response:
    if refusal.page is RefusalPage.NO_ACCESS:
        log.info("Sign-in refused: not a member")
        return RedirectResponse(NO_ACCESS_PATH, status_code=303)
    cause = refusal.cause
    log.info("Sign-in refused: %s", cause.reason if isinstance(cause, OidcRefusal) else cause)
    shell = request.app.state.spa_index
    if shell.exists():
        return HTMLResponse(shell.read_bytes(), status_code=SIGN_IN_FAILED_STATUS)
    return JSONResponse({"detail": "Login failed"}, status_code=SIGN_IN_FAILED_STATUS)


def install_sign_in(app: FastAPI) -> None:
    """Register webauth's start, callback, logout and back-channel routes on the app."""
    settings = get_settings()
    app.add_exception_handler(BackchannelHostMismatch, _answer_backchannel_host_mismatch)
    install_sign_in_routes(
        app,
        paths=SIGN_IN_PATHS,
        relying_party=_relying_party,
        admission=app.state.oidc_sign_in.admission,
        transaction=DatabaseSignInTransaction(app.state.ctx.db),
        refused=_refuse_sign_in,
        keeps_id_token=True,
        max_sessions=settings.max_concurrent_sessions_per_user,
        logout_button_label=lambda _request: LOGOUT_BUTTON_LABEL,
        backchannel_dependencies=[Depends(_require_backchannel_host)],
    )


def _account_console_url() -> str | None:
    issuer = normalised_oidc_issuer(get_settings().oidc_issuer)
    return f"{issuer}/account" if issuer else None


@router.get("/me")
def me(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> AuthMeResponse:
    return AuthMeResponse(
        id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        account_console_url=_account_console_url(),
    )

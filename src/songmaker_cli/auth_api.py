"""Auth endpoints: the signed-in account, and the composition of webauth's sign-in routes."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Final

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from webauth.oidc import OidcRefusal
from webauth.ports import AuthenticatedUser
from webauth.sign_in_routes import (
    LogoutPageText,
    RefusalPage,
    SignInRefusal,
    install_sign_in_routes,
)

from songmaker_cli.agent.mcp import ToolEffect, agent_tool
from songmaker_cli.api_models import AuthMeResponse
from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.auth_stores import DatabaseSignInTransaction
from songmaker_cli.constants import NO_ACCESS_PATH
from songmaker_cli.request_policies import SIGN_IN_PATHS
from songmaker_cli.settings import get_settings

if TYPE_CHECKING:
    from webauth.oidc import OidcRelyingParty

log = logging.getLogger(__name__)

SIGN_IN_FAILED_STATUS: int = 403
# Shown on the logout page only where no script runs; the account menu words the same button.
LOGOUT_BUTTON_LABEL: Final[str] = "Log out"

router = APIRouter(prefix="/auth", tags=["auth"])


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
    install_sign_in_routes(
        app,
        paths=SIGN_IN_PATHS,
        relying_party=_relying_party,
        admission=app.state.oidc_sign_in.admission,
        transaction=DatabaseSignInTransaction(app.state.ctx.db),
        refused=_refuse_sign_in,
        keeps_id_token=True,
        ui_language=lambda _request: None,
        max_sessions=settings.max_concurrent_sessions_per_user,
        logout_page_text=lambda _request: LogoutPageText(
            language="en", button_label=LOGOUT_BUTTON_LABEL
        ),
    )


_GET_ACCOUNT_DESCRIPTION = (
    "Read who the person is: id, username, role and the link to the account console."
)


@router.get(
    "/me",
    description=_GET_ACCOUNT_DESCRIPTION,
    openapi_extra=agent_tool(name="get_account", effect=ToolEffect.READ_ONLY),
)
def me(
    request: Request,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AuthMeResponse:
    return AuthMeResponse(
        id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        account_console_url=f"{request.app.state.oidc_sign_in.admission.bound_issuer}/account",
    )

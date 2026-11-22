"""Auth endpoints: the signed-in account, and the pages around webauth's sign-in routes."""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from webauth.ports import AuthenticatedUser
from webauth.sign_in_routes import LogoutPageText, RefusalPage, SignInRefusal
from webauth.web_auth import SignInPages

from songmaker_cli.agent.mcp import ToolEffect, agent_tool
from songmaker_cli.api_models import AuthMeResponse
from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.constants import NO_ACCESS_PATH
from songmaker_cli.page_language import request_language
from songmaker_cli.words import text

SIGN_IN_FAILED_STATUS: int = 403
# The answer of a checkout without a built page; a machine reads it, no person.
SIGN_IN_FAILED_DETAIL: Final[str] = "Login failed"

router = APIRouter(prefix="/auth", tags=["auth"])


def _refuse_sign_in(request: Request, refusal: SignInRefusal) -> Response:
    if refusal.page is RefusalPage.NO_ACCESS:
        return RedirectResponse(NO_ACCESS_PATH, status_code=303)
    shell = request.app.state.page_shell
    if shell is not None:
        return shell.answer(request, status_code=SIGN_IN_FAILED_STATUS)
    return JSONResponse({"detail": SIGN_IN_FAILED_DETAIL}, status_code=SIGN_IN_FAILED_STATUS)


def _logout_page_text(request: Request) -> LogoutPageText:
    language = request_language(request)
    return LogoutPageText(language=language, button_label=text(language, "logoutPage.logOut"))


def sign_in_pages() -> SignInPages:
    """What the composition call shows around the sign-in routes."""
    return SignInPages(
        refused=_refuse_sign_in,
        logout_page_text=_logout_page_text,
        ui_language=request_language,
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
        account_console_url=f"{request.app.state.web_auth.admission.bound_issuer}/account",
    )

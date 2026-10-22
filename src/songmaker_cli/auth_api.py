"""Auth endpoints — sign-in through the Keycloak realm, logout, and the signed-in account."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session
from webauth.config import WebAuthConfig, web_auth_config
from webauth.cookies import issue_session_cookies
from webauth.oidc import OidcRefusal
from webauth.oidc_login import AdmissionRefusal, finish_login, log_out, open_session, start_login
from webauth.ports import AuthenticatedUser

from songmaker_cli.api_models import AuthMeResponse, LogoutResponse
from songmaker_cli.app_context import get_db_session
from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.auth_stores import (
    DatabaseAuditSink,
    DatabaseSessionRecordStore,
    DatabaseSubjectUserStore,
    DatabaseWriteLock,
)
from songmaker_cli.constants import (
    LOGOUT_PATH,
    NO_ACCESS_PATH,
    OIDC_CALLBACK_PATH,
    OIDC_START_PATH,
)
from songmaker_cli.settings import get_settings

if TYPE_CHECKING:
    from songmaker_cli.oidc_client import OidcSignIn

log = logging.getLogger(__name__)

SIGN_IN_FAILED_STATUS: int = 403
DEFAULT_LANDING_PATH = "/"

router = APIRouter(prefix="/auth", tags=["auth"])
sign_in_router = APIRouter(tags=["auth"])


def _sign_in(request: Request) -> OidcSignIn:
    return request.app.state.oidc_sign_in


@sign_in_router.get(OIDC_START_PATH)
def start_sign_in(
    request: Request,
    next: str | None = None,
    config: WebAuthConfig = Depends(web_auth_config),
) -> Response:
    response = Response(status_code=303)
    response.headers["location"] = start_login(
        _sign_in(request).relying_party, request, response, config, return_to=next,
    )
    return response


@sign_in_router.get(OIDC_CALLBACK_PATH)
def finish_sign_in(
    request: Request,
    db: Session = Depends(get_db_session),
    config: WebAuthConfig = Depends(web_auth_config),
) -> Response:
    sign_in = _sign_in(request)
    # The library writes its cookie changes onto this response, so every outcome
    # is answered with it.
    response = Response()
    lock = DatabaseWriteLock(db)
    outcome = finish_login(
        sign_in.relying_party, request, response, config,
        admission=sign_in.admission,
        accounts=DatabaseSubjectUserStore(db),
        lock=lock,
        audit=DatabaseAuditSink(db),
    )
    if isinstance(outcome, (OidcRefusal, AdmissionRefusal)):
        db.rollback()
        return _refused(request, response, outcome)
    session = open_session(
        request, config, outcome,
        sessions=DatabaseSessionRecordStore(db),
        lock=lock,
        max_sessions=get_settings().max_concurrent_sessions_per_user,
    )
    db.commit()
    issue_session_cookies(response, session.id, config)
    return _redirect(response, outcome.return_to or DEFAULT_LANDING_PATH)


def _redirect(response: Response, location: str) -> Response:
    response.status_code = 303
    response.headers["location"] = location
    return response


def _refused(
    request: Request, response: Response, refusal: OidcRefusal | AdmissionRefusal,
) -> Response:
    if refusal is AdmissionRefusal.NOT_A_MEMBER:
        log.info("Sign-in refused: not a member")
        return _redirect(response, NO_ACCESS_PATH)
    log.info("Sign-in refused: %s", refusal.reason if isinstance(refusal, OidcRefusal) else refusal)
    shell = request.app.state.spa_index
    response.status_code = SIGN_IN_FAILED_STATUS
    if shell.exists():
        body = shell.read_bytes()
        response.body = body
        response.headers["content-type"] = "text/html; charset=utf-8"
    else:
        response.body = b'{"detail":"Login failed"}'
        response.headers["content-type"] = "application/json"
    response.headers["content-length"] = str(len(response.body))
    return response


@sign_in_router.post(LOGOUT_PATH)
def sign_out(
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
    config: WebAuthConfig = Depends(web_auth_config),
) -> LogoutResponse:
    logout_url = log_out(
        _sign_in(request).relying_party, request, response, config,
        sessions=DatabaseSessionRecordStore(db),
        lock=DatabaseWriteLock(db),
    )
    db.commit()
    return LogoutResponse(logout_url=logout_url)


def _account_console_url() -> str | None:
    issuer = get_settings().oidc_issuer
    return f"{issuer.rstrip('/')}/account" if issuer else None


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

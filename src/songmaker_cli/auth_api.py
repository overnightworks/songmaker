"""Auth endpoints — sign-in through the Keycloak realm, logout, and the signed-in account."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from webauth.config import WebAuthConfig, web_auth_config
from webauth.cookies import issue_session_cookies
from webauth.oidc import OidcRefusal
from webauth.oidc_login import (
    AdmissionRefusal,
    BackchannelLogoutResult,
    finish_login,
    log_out,
    open_session,
    receive_backchannel_logout,
    start_login,
)
from webauth.ports import AuthenticatedUser

from songmaker_cli.api_helpers import resolve_public_base_url
from songmaker_cli.api_models import AuthMeResponse
from songmaker_cli.app_context import get_db_session
from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.auth_stores import (
    DatabaseAuditSink,
    DatabaseSessionRecordStore,
    DatabaseSubjectUserStore,
    DatabaseWriteLock,
)
from songmaker_cli.constants import (
    LOGOUT_BUTTON_LABEL,
    LOGOUT_PATH,
    NO_ACCESS_PATH,
    OIDC_CALLBACK_PATH,
    OIDC_START_PATH,
)
from songmaker_cli.oidc_client import normalised_oidc_issuer
from songmaker_cli.request_policies import BACKCHANNEL_LOGOUT_PATH
from songmaker_cli.settings import DEFAULT_SERVER_PORT, get_settings

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

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
        keeps_id_token=True,
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
    db: Session = Depends(get_db_session),
    config: WebAuthConfig = Depends(web_auth_config),
) -> Response:
    answer = log_out(
        _sign_in(request).relying_party, request, config,
        sessions=DatabaseSessionRecordStore(db),
        lock=DatabaseWriteLock(db),
        button_label=LOGOUT_BUTTON_LABEL,
    )
    db.commit()
    return answer


def _end_subject_sessions(
    sign_in: OidcSignIn, factory: sessionmaker[Session], form_body: bytes, content_type: str | None,
) -> bool:
    """Run the logout in its own session and transaction; True only once committed."""
    try:
        with factory() as db:
            result = receive_backchannel_logout(
                sign_in.relying_party, form_body, content_type,
                accounts=DatabaseSubjectUserStore(db),
                sessions=DatabaseSessionRecordStore(db),
                lock=DatabaseWriteLock(db),
                audit=DatabaseAuditSink(db),
            )
            if result is not BackchannelLogoutResult.ACCEPTED:
                db.rollback()
                return False
            db.commit()
    except Exception:
        log.exception("Back-channel logout failed")
        return False
    return True


def _backchannel_logout_host() -> str:
    """The Host the realm's call carries: the public host on the container port."""
    return f"{urlsplit(resolve_public_base_url()).hostname}:{DEFAULT_SERVER_PORT}"


@sign_in_router.post(BACKCHANNEL_LOGOUT_PATH)
async def end_sessions_on_realm_logout(request: Request) -> Response:
    """Keycloak's back-channel logout; only the private network's Host reaches it."""
    if request.headers.get("host") != _backchannel_logout_host():
        return Response(status_code=404)
    accepted = await run_in_threadpool(
        _end_subject_sessions,
        _sign_in(request),
        request.app.state.ctx.db,
        await request.body(),
        request.headers.get("content-type"),
    )
    return Response(status_code=200 if accepted else 400)


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

"""Auth API endpoints — login, logout, current user."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from webauth.config import WebAuthConfig, web_auth_config
from webauth.dependencies import AuthenticatedUser
from webauth.login import (
    INVALID_CREDENTIALS_DETAIL,
    LoginOutcome,
    clear_session_cookies,
    http_refusal,
    issue_session_cookies,
    judge_credentials,
    login_attempt_budget,
)
from webauth.proxies import client_user_agent, resolve_client_ip
from webauth.session_ending import end_session, prune_sessions

from songmaker_cli.api_helpers import _SESSION_CAP_LOCK_ID, _begin_exclusive
from songmaker_cli.api_models import (
    AuthMeResponse,
    LoginRequest,
    StatusResponse,
    UserResponse,
)
from songmaker_cli.app_context import get_db_session
from songmaker_cli.auth_dependencies import (
    _session_record_store,
    get_current_user,
    get_verified_session_id,
)
from songmaker_cli.auth_stores import DatabaseLoginAttemptStore, DatabaseSessionRecordStore
from songmaker_cli.db.queries.auth import (
    create_session,
    get_user_by_username,
    record_login_attempt,
)
from songmaker_cli.settings import get_settings

if TYPE_CHECKING:
    from songmaker_cli.db.models import User

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post(
    "/login",
    responses={
        401: {"description": "Credentials are invalid"},
        429: {"description": "Too many login attempts"},
    },
)
def login(
    req: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
    config: WebAuthConfig = Depends(web_auth_config),
    sessions: DatabaseSessionRecordStore = Depends(_session_record_store),
) -> UserResponse:
    ip = resolve_client_ip(request)

    refusal = login_attempt_budget(
        DatabaseLoginAttemptStore(db),
        ip_address=ip,
        username=req.username,
        config=config,
    )
    if refusal is not None:
        raise http_refusal(refusal)
    user = _authenticate_login(db, ip, req, config)

    assert not db.new and not db.dirty and not db.deleted, (
        "login: session has uncommitted mutations — "
        "the commit() below would persist them unconditionally"
    )
    db.commit()
    _begin_exclusive(db, _SESSION_CAP_LOCK_ID)

    record_login_attempt(db, ip, req.username, success=True)
    ua = client_user_agent(request)
    expires = datetime.now(timezone.utc) + timedelta(
        seconds=config.session_max_age_seconds,
    )
    user_session = create_session(
        db, user.id, expires,
        ip_address=ip, user_agent=ua,
    )
    prune_sessions(
        sessions, user.id, get_settings().max_concurrent_sessions_per_user,
    )
    db.commit()

    issue_session_cookies(response, user_session.id, config)
    return UserResponse.from_orm(user)


def _authenticate_login(
    db: Session, ip: str, req: LoginRequest, config: WebAuthConfig,
) -> User:
    user = get_user_by_username(db, req.username)
    outcome = judge_credentials(req.password, user, hasher=config.password_hasher)
    if outcome is LoginOutcome.ADMITTED:
        return user
    record_login_attempt(db, ip, req.username, success=False)
    db.commit()
    raise HTTPException(401, INVALID_CREDENTIALS_DETAIL)


@router.delete("/session")
def logout(
    response: Response,
    db: Session = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(get_current_user),
    session_id: str = Depends(get_verified_session_id),
    config: WebAuthConfig = Depends(web_auth_config),
    sessions: DatabaseSessionRecordStore = Depends(_session_record_store),
) -> StatusResponse:
    end_session(sessions, session_id=session_id)
    db.commit()

    clear_session_cookies(response, config)
    return StatusResponse(status="ok")


@router.get("/me")
def me(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> AuthMeResponse:
    return AuthMeResponse(
        id=current_user.id,
        username=current_user.username,
        role=current_user.role,
    )

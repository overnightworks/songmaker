"""Auth API endpoints — login, logout, setup, password change."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from songmaker_cli.api_models import (
    AuthMeResponse,
    ChangePasswordRequest,
    LoginRequest,
    SetupRequest,
    SetupRequiredResponse,
    StatusResponse,
    UserResponse,
)
from songmaker_cli.auth import (
    LOGIN_RATE_LIMIT,
    LOGIN_RATE_WINDOW_SECONDS,
    ROLE_ADMIN,
    SESSION_MAX_AGE_SECONDS,
    hash_password,
    verify_password,
)
from songmaker_cli.db.engine import get_db_session
from songmaker_cli.db.queries import (
    count_recent_failed_attempts,
    create_session,
    create_user,
    delete_session,
    delete_user_sessions,
    get_user,
    get_user_by_username,
    record_login_attempt,
    user_count,
)
from songmaker_cli.middleware import (
    SESSION_COOKIE,
    AuthenticatedUser,
    get_current_user,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


_get_session = get_db_session


_MAX_USER_AGENT_LENGTH = 500


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _client_user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")[:_MAX_USER_AGENT_LENGTH]


def _set_session_cookie(
    response: Response, session_id: str, request: Request | None = None,
) -> None:
    secure = False
    if request:
        forwarded = request.headers.get("x-forwarded-proto", "")
        secure = forwarded == "https" or request.url.scheme == "https"
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/",
    )


@router.get("/setup-required")
def setup_required(db: Session = Depends(_get_session)) -> SetupRequiredResponse:
    return SetupRequiredResponse(required=user_count(db) == 0)


@router.post("/setup")
def setup(
    req: SetupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(_get_session),
) -> UserResponse:
    db.execute(text("BEGIN IMMEDIATE"))
    if user_count(db) > 0:
        raise HTTPException(403, "Setup already completed")

    try:
        user = create_user(db, req.username, hash_password(req.password), role=ROLE_ADMIN)
        db.flush()
        if user_count(db) > 1:
            db.rollback()
            raise HTTPException(403, "Setup already completed")
        expires = datetime.now(timezone.utc) + timedelta(seconds=SESSION_MAX_AGE_SECONDS)
        user_session = create_session(
            db, user.id, expires,
            ip_address=_client_ip(request),
            user_agent=_client_user_agent(request),
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(403, "Setup already completed")

    _set_session_cookie(response, user_session.id, request)
    log.info("Setup completed: admin user '%s' created", req.username)
    return UserResponse.from_orm(user)


@router.post("/login")
def login(
    req: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(_get_session),
) -> UserResponse:
    ip = _client_ip(request)

    ip_failures = count_recent_failed_attempts(db, ip, LOGIN_RATE_WINDOW_SECONDS)
    user_failures = count_recent_failed_attempts(
        db, ip, LOGIN_RATE_WINDOW_SECONDS, username=req.username,
    )
    if ip_failures >= LOGIN_RATE_LIMIT or user_failures >= LOGIN_RATE_LIMIT:
        raise HTTPException(
            429,
            "Too many login attempts. Try again later.",
            headers={"Retry-After": str(LOGIN_RATE_WINDOW_SECONDS)},
        )

    user = get_user_by_username(db, req.username)
    if not user or not verify_password(req.password, user.password_hash):
        record_login_attempt(db, ip, req.username, success=False)
        db.commit()
        raise HTTPException(401, "Invalid username or password")

    if not user.is_active:
        record_login_attempt(db, ip, req.username, success=False)
        db.commit()
        raise HTTPException(403, "Account disabled")

    record_login_attempt(db, ip, req.username, success=True)
    delete_user_sessions(db, user.id)

    expires = datetime.now(timezone.utc) + timedelta(seconds=SESSION_MAX_AGE_SECONDS)
    user_session = create_session(
        db, user.id, expires,
        ip_address=ip,
        user_agent=_client_user_agent(request),
    )
    db.commit()

    _set_session_cookie(response, user_session.id, request)
    return UserResponse.from_orm(user)


@router.delete("/session")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(_get_session),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> StatusResponse:
    session_id = getattr(request.state, "session_id", None)
    if session_id:
        delete_session(db, session_id)
        db.commit()

    response.delete_cookie(SESSION_COOKIE, path="/")
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


@router.put("/password")
def change_password(
    req: ChangePasswordRequest,
    request: Request,
    response: Response,
    db: Session = Depends(_get_session),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> StatusResponse:
    user = get_user(db, current_user.id)

    if not verify_password(req.current, user.password_hash):
        raise HTTPException(401, "Current password is incorrect")

    user.password_hash = hash_password(req.new)
    delete_user_sessions(db, current_user.id)

    expires = datetime.now(timezone.utc) + timedelta(seconds=SESSION_MAX_AGE_SECONDS)
    new_session = create_session(
        db, current_user.id, expires,
        ip_address=_client_ip(request),
        user_agent=_client_user_agent(request),
    )
    db.commit()

    _set_session_cookie(response, new_session.id, request)
    return StatusResponse(status="ok")

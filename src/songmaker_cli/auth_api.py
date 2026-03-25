"""Auth API endpoints — login, logout, setup, password change."""

from __future__ import annotations

import logging
import secrets
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
    get_client_ip,
    hash_password,
    sign_session_id,
    verify_password_constant_time,
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
    direct_ip = request.client.host if request.client else "unknown"
    return get_client_ip(direct_ip, request.headers.get("x-forwarded-for"))


def _client_user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")[:_MAX_USER_AGENT_LENGTH]


def _is_trusted_proxy(request: Request) -> bool:
    from songmaker_cli.auth import TRUSTED_PROXIES
    if not TRUSTED_PROXIES:
        return False
    direct_ip = request.client.host if request.client else ""
    return direct_ip in TRUSTED_PROXIES


def _detect_secure(request: Request | None) -> bool:
    if not request:
        return False
    if _is_trusted_proxy(request):
        return request.headers.get("x-forwarded-proto", "") == "https"
    return request.url.scheme == "https"


def _set_session_cookie(
    response: Response, session_id: str, request: Request | None = None,
) -> None:
    from songmaker_cli.auth import CSRF_COOKIE
    secure = _detect_secure(request)
    signed = sign_session_id(session_id)
    response.set_cookie(
        SESSION_COOKIE,
        signed,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/",
    )
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=False,
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
    password_valid = verify_password_constant_time(
        req.password, user.password_hash if user else None,
    )
    if not user or not password_valid:
        record_login_attempt(db, ip, req.username, success=False)
        db.commit()
        raise HTTPException(401, "Invalid username or password")

    if not user.is_active:
        record_login_attempt(db, ip, req.username, success=False)
        db.commit()
        raise HTTPException(403, "Account disabled")

    record_login_attempt(db, ip, req.username, success=True)
    # Security: wipe all existing sessions on login to prevent session accumulation.
    # Tradeoff: logging in from a new device logs out all others.
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

    from songmaker_cli.auth import CSRF_COOKIE
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
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
    ip = _client_ip(request)

    ip_failures = count_recent_failed_attempts(
        db, ip, LOGIN_RATE_WINDOW_SECONDS, username=f"__pwchange__{current_user.username}",
    )
    if ip_failures >= LOGIN_RATE_LIMIT:
        raise HTTPException(
            429, "Too many password change attempts. Try again later.",
            headers={"Retry-After": str(LOGIN_RATE_WINDOW_SECONDS)},
        )

    if not verify_password_constant_time(req.current, user.password_hash):
        record_login_attempt(db, ip, f"__pwchange__{current_user.username}", success=False)
        db.commit()
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

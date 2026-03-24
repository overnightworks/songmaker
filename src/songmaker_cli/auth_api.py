"""Auth API endpoints — login, logout, setup, password change."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
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
from songmaker_cli.db.engine import get_session_factory
from songmaker_cli.db.queries import (
    count_recent_failed_attempts,
    create_session,
    create_user,
    delete_session,
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


def _get_session() -> Session:  # type: ignore[misc]
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_session_cookie(response: Response, session_id: str, secure: bool = False) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
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
    if user_count(db) > 0:
        raise HTTPException(403, "Setup already completed")

    user = create_user(db, req.username, hash_password(req.password), role=ROLE_ADMIN)
    expires = datetime.now(timezone.utc) + timedelta(seconds=SESSION_MAX_AGE_SECONDS)
    user_session = create_session(
        db, user.id, expires,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )
    db.commit()

    _set_session_cookie(response, user_session.id)
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

    failed_count = count_recent_failed_attempts(db, ip, LOGIN_RATE_WINDOW_SECONDS)
    if failed_count >= LOGIN_RATE_LIMIT:
        record_login_attempt(db, ip, req.username, success=False)
        db.commit()
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

    expires = datetime.now(timezone.utc) + timedelta(seconds=SESSION_MAX_AGE_SECONDS)
    user_session = create_session(
        db, user.id, expires,
        ip_address=ip,
        user_agent=request.headers.get("user-agent", ""),
    )
    db.commit()

    _set_session_cookie(response, user_session.id)
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
    db: Session = Depends(_get_session),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> StatusResponse:
    user = get_user(db, current_user.id)

    if not verify_password(req.current, user.password_hash):
        raise HTTPException(401, "Current password is incorrect")

    user.password_hash = hash_password(req.new)
    db.commit()
    return StatusResponse(status="ok")

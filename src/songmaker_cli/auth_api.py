"""Auth API endpoints — login, logout, setup, password change."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import _SESSION_CAP_LOCK_ID, _begin_exclusive
from songmaker_cli.api_models import (
    AuthMeResponse,
    ChangePasswordRequest,
    LoginRequest,
    SetupRequest,
    SetupRequiredResponse,
    StatusResponse,
    UserResponse,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.auth import (
    CSRF_COOKIE,
    LOGIN_RATE_WINDOW_SECONDS,
    ROLE_ADMIN,
    generate_csrf_token,
    hash_password,
    request_is_https,
    resolve_client_ip,
    sign_session_id,
    verify_password_constant_time,
)
from songmaker_cli.constants import HTTP_MAX_USER_AGENT_LENGTH
from songmaker_cli.db.queries import (
    count_recent_failed_attempts,
    create_session,
    create_user,
    delete_session,
    delete_user_sessions,
    get_user,
    get_user_by_username,
    prune_overflow_sessions,
    record_login_attempt,
    user_count,
)
from songmaker_cli.middleware import (
    SESSION_COOKIE,
    AuthenticatedUser,
    get_current_user,
)
from songmaker_cli.redis_client import SessionCache
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])




def _cache_session(
    request: Request, session_id: str, user, ip: str, ua: str, expires, created_at,
) -> None:
    session_cache: SessionCache | None = getattr(request.app.state, "session_cache", None)
    if not session_cache:
        return
    try:
        session_cache.store(
            session_id, user.id, user.username, user.role, user.is_active,
            ip, ua, expires, created_at, get_settings().session_max_age_seconds,
        )
    except Exception:
        log.warning("Redis session cache write failed on login")


def _clear_user_cache(request: Request, user_id: str) -> None:
    session_cache: SessionCache | None = getattr(request.app.state, "session_cache", None)
    if not session_cache:
        return
    try:
        session_cache.delete_user_sessions(user_id)
    except Exception:
        log.warning("Redis session cache clear failed")


def _client_user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")[:HTTP_MAX_USER_AGENT_LENGTH]


def _set_session_cookie(
    response: Response, session_id: str, ctx: AppContext, request: Request,
) -> None:
    secure = request_is_https(request)
    signed = sign_session_id(session_id, ctx.session_secret)
    max_age = get_settings().session_max_age_seconds
    response.set_cookie(
        SESSION_COOKIE,
        signed,
        max_age=max_age,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/",
    )
    csrf_token = generate_csrf_token(session_id, ctx.session_secret)
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,  # NOSONAR The client must read this CSRF token for double-submit.
        samesite="strict",
        secure=secure,
        path="/",
    )


@router.get("/setup-required")
def setup_required(db: Session = Depends(get_db_session)) -> SetupRequiredResponse:
    return SetupRequiredResponse(required=user_count(db) == 0)


@router.post("/setup")
def setup(
    req: SetupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> UserResponse:
    _begin_exclusive(db)
    if user_count(db) > 0:
        raise HTTPException(403, "Setup already completed")

    ip = resolve_client_ip(request)
    ua = _client_user_agent(request)
    try:
        user = create_user(db, req.username, hash_password(req.password), role=ROLE_ADMIN)
        db.flush()
        if user_count(db) > 1:
            db.rollback()
            raise HTTPException(403, "Setup already completed")
        expires = datetime.now(timezone.utc) + timedelta(
            seconds=get_settings().session_max_age_seconds,
        )
        user_session = create_session(
            db, user.id, expires,
            ip_address=ip, user_agent=ua,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(403, "Setup already completed")

    _cache_session(request, user_session.id, user, ip, ua, expires, user_session.created_at)
    _set_session_cookie(response, user_session.id, ctx, request)
    log.info("Setup completed: admin user '%s' created", req.username)
    return UserResponse.from_orm(user)


@router.post("/login")
def login(
    req: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> UserResponse:
    ip = resolve_client_ip(request)
    settings = get_settings()

    lockout_failures = count_recent_failed_attempts(
        db, ip, settings.login_lockout_window_seconds, username=req.username,
    )
    if lockout_failures >= settings.login_lockout_threshold:
        raise HTTPException(
            429,
            "Account temporarily locked due to repeated failed attempts. Try again later.",
            headers={"Retry-After": str(settings.login_lockout_window_seconds)},
        )

    ip_failures = count_recent_failed_attempts(db, ip, LOGIN_RATE_WINDOW_SECONDS)
    user_failures = count_recent_failed_attempts(
        db, ip, LOGIN_RATE_WINDOW_SECONDS, username=req.username,
    )
    if ip_failures >= settings.login_rate_limit or user_failures >= settings.login_rate_limit:
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
        raise HTTPException(401, "Invalid username or password")

    assert not db.new and not db.dirty and not db.deleted, (
        "login: session has uncommitted mutations — "
        "the commit() below would persist them unconditionally"
    )
    db.commit()
    _begin_exclusive(db, _SESSION_CAP_LOCK_ID)

    record_login_attempt(db, ip, req.username, success=True)
    ua = _client_user_agent(request)
    expires = datetime.now(timezone.utc) + timedelta(seconds=settings.session_max_age_seconds)
    user_session = create_session(
        db, user.id, expires,
        ip_address=ip, user_agent=ua,
    )
    pruned_ids = prune_overflow_sessions(
        db, user.id, settings.max_concurrent_sessions_per_user,
    )

    session_cache: SessionCache | None = getattr(request.app.state, "session_cache", None)
    if session_cache is not None:
        try:
            for pruned_id in pruned_ids:
                session_cache.delete(pruned_id, user.id)
        except Exception:
            log.warning("Redis session cache delete failed on login prune")
            db.rollback()
            raise HTTPException(503, "Service temporarily degraded — try again shortly")

    _cache_session(request, user_session.id, user, ip, ua, expires, user_session.created_at)
    try:
        db.commit()
    except Exception:
        if session_cache is not None:
            try:
                session_cache.delete(user_session.id, user.id)
            except Exception:
                log.warning("Redis session cache delete failed after login commit failure")
        raise

    _set_session_cookie(response, user_session.id, ctx, request)
    return UserResponse.from_orm(user)


@router.delete("/session")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> StatusResponse:
    session_id = getattr(request.state, "session_id", None)
    if session_id:
        delete_session(db, session_id)
        db.commit()

        session_cache: SessionCache | None = getattr(request.app.state, "session_cache", None)
        if session_cache:
            try:
                session_cache.delete(session_id, current_user.id)
            except Exception:
                log.warning("Redis session cache delete failed on logout")

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
    db: Session = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(get_current_user),
    ctx: AppContext = Depends(get_app_context),
) -> StatusResponse:
    user = get_user(db, current_user.id)
    ip = resolve_client_ip(request)
    settings = get_settings()

    ip_failures = count_recent_failed_attempts(
        db, ip, LOGIN_RATE_WINDOW_SECONDS, username=f"__pwchange__{current_user.username}",
    )
    if ip_failures >= settings.login_rate_limit:
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

    ip = resolve_client_ip(request)
    ua = _client_user_agent(request)
    expires = datetime.now(timezone.utc) + timedelta(
        seconds=settings.session_max_age_seconds,
    )
    new_session = create_session(
        db, current_user.id, expires,
        ip_address=ip, user_agent=ua,
    )
    db.commit()

    _clear_user_cache(request, current_user.id)
    _cache_session(request, new_session.id, user, ip, ua, expires, new_session.created_at)
    _set_session_cookie(response, new_session.id, ctx, request)
    return StatusResponse(status="ok")

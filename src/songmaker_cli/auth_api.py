"""Auth API endpoints — login, logout, setup, password change."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Final

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
from songmaker_cli.app_context import get_db_session
from songmaker_cli.auth import ROLE_ADMIN
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
from songmaker_cli.middleware import AuthenticatedUser, get_current_user
from songmaker_cli.settings import get_settings
from webauth.config import WebAuthConfig, web_auth_config
from webauth.cookies import generate_csrf_token, sign_session_id
from webauth.passwords import hash_password, verify_password_constant_time
from webauth.proxies import request_is_https, resolve_client_ip
from webauth.session_store import SessionCache

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

SETUP_ALREADY_COMPLETED_DETAIL: Final = "Setup already completed"




def _cache_session(
    request: Request, session_id: str, user, ip: str, ua: str, expires, created_at,
) -> None:
    session_cache: SessionCache | None = getattr(request.app.state, "session_cache", None)
    if not session_cache:
        return
    try:
        session_cache.store(
            session_id, user.id, user.username, user.role, user.is_active,
            ip, ua, expires, created_at,
            web_auth_config(request).session_max_age_seconds,
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
    response: Response, session_id: str, config: WebAuthConfig, request: Request,
) -> None:
    secure = request_is_https(request)
    signed = sign_session_id(session_id, config.signing_key)
    max_age = config.session_max_age_seconds
    response.set_cookie(
        config.session_cookie_name,
        signed,
        max_age=max_age,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/",
    )
    csrf_token = generate_csrf_token(session_id, config.signing_key)
    response.set_cookie(  # NOSONAR The client must read this CSRF token for double-submit.
        config.csrf_cookie_name,
        csrf_token,
        max_age=max_age,
        httponly=False,
        samesite="strict",
        secure=secure,
        path="/",
    )


@router.get("/setup-required")
def setup_required(db: Session = Depends(get_db_session)) -> SetupRequiredResponse:
    return SetupRequiredResponse(required=user_count(db) == 0)


@router.post(
    "/setup",
    responses={403: {"description": "Initial setup is not available"}},
)
def setup(
    req: SetupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
    config: WebAuthConfig = Depends(web_auth_config),
) -> UserResponse:
    _begin_exclusive(db)
    if user_count(db) > 0:
        raise HTTPException(403, SETUP_ALREADY_COMPLETED_DETAIL)

    ip = resolve_client_ip(request)
    ua = _client_user_agent(request)
    try:
        user = create_user(db, req.username, hash_password(req.password), role=ROLE_ADMIN)
        db.flush()
        if user_count(db) > 1:
            db.rollback()
            raise HTTPException(403, SETUP_ALREADY_COMPLETED_DETAIL)
        expires = datetime.now(timezone.utc) + timedelta(
            seconds=config.session_max_age_seconds,
        )
        user_session = create_session(
            db, user.id, expires,
            ip_address=ip, user_agent=ua,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(403, SETUP_ALREADY_COMPLETED_DETAIL)

    _cache_session(request, user_session.id, user, ip, ua, expires, user_session.created_at)
    _set_session_cookie(response, user_session.id, config, request)
    log.info("Setup completed: admin user '%s' created", req.username)
    return UserResponse.from_orm(user)


@router.post(
    "/login",
    responses={
        401: {"description": "Credentials are invalid"},
        429: {"description": "Too many login attempts"},
        503: {"description": "Session service is temporarily unavailable"},
    },
)
def login(
    req: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
    config: WebAuthConfig = Depends(web_auth_config),
) -> UserResponse:
    ip = resolve_client_ip(request)

    _check_login_attempt_limits(db, ip, req.username, config)
    user = _authenticate_login(db, ip, req)

    assert not db.new and not db.dirty and not db.deleted, (
        "login: session has uncommitted mutations — "
        "the commit() below would persist them unconditionally"
    )
    db.commit()
    _begin_exclusive(db, _SESSION_CAP_LOCK_ID)

    record_login_attempt(db, ip, req.username, success=True)
    ua = _client_user_agent(request)
    expires = datetime.now(timezone.utc) + timedelta(
        seconds=config.session_max_age_seconds,
    )
    user_session = create_session(
        db, user.id, expires,
        ip_address=ip, user_agent=ua,
    )
    pruned_ids = prune_overflow_sessions(
        db, user.id, get_settings().max_concurrent_sessions_per_user,
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

    _set_session_cookie(response, user_session.id, config, request)
    return UserResponse.from_orm(user)


def _check_login_attempt_limits(
    db: Session, ip: str, username: str, config: WebAuthConfig,
) -> None:
    lockout_failures = count_recent_failed_attempts(
        db, ip, config.login_lockout_window_seconds, username=username,
    )
    if lockout_failures >= config.login_lockout_threshold:
        raise HTTPException(
            429,
            "Account temporarily locked due to repeated failed attempts. Try again later.",
            headers={"Retry-After": str(config.login_lockout_window_seconds)},
        )
    window = config.login_rate_window_seconds
    ip_failures = count_recent_failed_attempts(db, ip, window)
    user_failures = count_recent_failed_attempts(db, ip, window, username=username)
    if ip_failures >= config.login_rate_limit or user_failures >= config.login_rate_limit:
        raise HTTPException(
            429,
            "Too many login attempts. Try again later.",
            headers={"Retry-After": str(window)},
        )


def _authenticate_login(db: Session, ip: str, req: LoginRequest):
    user = get_user_by_username(db, req.username)
    password_valid = verify_password_constant_time(
        req.password, user.password_hash if user else None,
    )
    if user is not None and password_valid and user.is_active:
        return user
    record_login_attempt(db, ip, req.username, success=False)
    db.commit()
    raise HTTPException(401, "Invalid username or password")


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

    config = web_auth_config(request)
    response.delete_cookie(config.session_cookie_name, path="/")
    response.delete_cookie(config.csrf_cookie_name, path="/")
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


@router.put(
    "/password",
    responses={
        401: {"description": "Current password is incorrect"},
        429: {"description": "Too many password change attempts"},
    },
)
def change_password(
    req: ChangePasswordRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(get_current_user),
    config: WebAuthConfig = Depends(web_auth_config),
) -> StatusResponse:
    user = get_user(db, current_user.id)
    ip = resolve_client_ip(request)
    window = config.login_rate_window_seconds

    ip_failures = count_recent_failed_attempts(
        db, ip, window, username=f"__pwchange__{current_user.username}",
    )
    if ip_failures >= config.login_rate_limit:
        raise HTTPException(
            429, "Too many password change attempts. Try again later.",
            headers={"Retry-After": str(window)},
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
        seconds=config.session_max_age_seconds,
    )
    new_session = create_session(
        db, current_user.id, expires,
        ip_address=ip, user_agent=ua,
    )
    db.commit()

    _clear_user_cache(request, current_user.id)
    _cache_session(request, new_session.id, user, ip, ua, expires, new_session.created_at)
    _set_session_cookie(response, new_session.id, config, request)
    return StatusResponse(status="ok")

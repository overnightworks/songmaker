"""Auth API endpoints — login, logout, setup, password change."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Final

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
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
from webauth.passwords import hash_password, verify_password_constant_time
from webauth.proxies import client_user_agent, resolve_client_ip

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
from songmaker_cli.auth_dependencies import get_current_user, get_verified_session_id
from songmaker_cli.auth_stores import DatabaseLoginAttemptStore
from songmaker_cli.constants import ROLE_ADMIN
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
from songmaker_cli.settings import get_settings

if TYPE_CHECKING:
    from songmaker_cli.db.models import User

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

SETUP_ALREADY_COMPLETED_DETAIL: Final = "Setup already completed"


def _cache_session(
    request: Request, session_id: str, user, ip: str, ua: str, expires, created_at,
) -> None:
    session_cache = web_auth_config(request).session_cache
    if not session_cache:
        return
    max_age = web_auth_config(request).session_max_age_seconds
    try:
        session_cache.store(
            session_id, user.id, user.username, user.role, user.is_active,
            ip, ua, expires, created_at, max_age,
        )
    except Exception:
        log.warning("Redis session cache write failed on login")


def _clear_user_cache(request: Request, user_id: str) -> None:
    session_cache = web_auth_config(request).session_cache
    if not session_cache:
        return
    try:
        session_cache.delete_user_sessions(user_id)
    except Exception:
        log.warning("Redis session cache clear failed")


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
    ua = client_user_agent(request)
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
    issue_session_cookies(response, request, user_session.id, config)
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
    pruned_ids = prune_overflow_sessions(
        db, user.id, get_settings().max_concurrent_sessions_per_user,
    )

    session_cache = web_auth_config(request).session_cache
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

    issue_session_cookies(response, request, user_session.id, config)
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
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(get_current_user),
    session_id: str = Depends(get_verified_session_id),
    config: WebAuthConfig = Depends(web_auth_config),
) -> StatusResponse:
    delete_session(db, session_id)
    db.commit()

    session_cache = web_auth_config(request).session_cache
    if session_cache:
        try:
            session_cache.delete(session_id, current_user.id)
        except Exception:
            log.warning("Redis session cache delete failed on logout")

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
    ua = client_user_agent(request)
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
    issue_session_cookies(response, request, new_session.id, config)
    return StatusResponse(status="ok")

"""Admin API endpoints — user management, sessions, login attempts."""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import ensure_not_last_admin
from songmaker_cli.api_models import (
    AuditLogResponse,
    CreateUserRequest,
    LoginAttemptResponse,
    PaginatedResponse,
    SessionResponse,
    StatusResponse,
    UpdateUserRequest,
    UserResponse,
)
from songmaker_cli.api_models.settings import AceStepStatusResponse
from songmaker_cli.app_context import get_db_session
from songmaker_cli.auth import hash_password
from songmaker_cli.constants import ACESTEP_PORT, PAGE_ADMIN_DEFAULT_LIMIT, PAGE_ADMIN_MAX_LIMIT
from songmaker_cli.db.queries import (
    count_active_sessions,
    count_audit_log,
    count_login_attempts,
    create_user,
    delete_session,
    delete_user_sessions,
    get_user,
    get_user_by_username,
    list_active_sessions,
    list_audit_log,
    list_login_attempts,
    list_users,
    record_audit,
    update_user,
)
from songmaker_cli.middleware import AuthenticatedUser, require_admin
from songmaker_cli.redis_client import SessionCache

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _clear_user_session_cache(request: Request, user_id: str) -> None:
    session_cache: SessionCache | None = getattr(request.app.state, "session_cache", None)
    if not session_cache:
        return
    try:
        session_cache.delete_user_sessions(user_id)
    except Exception:
        log.warning("Redis session cache clear failed for user %s", user_id)


@router.get("/users")
def list_users_endpoint(
    db: Session = Depends(get_db_session),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> list[UserResponse]:
    return [UserResponse.from_orm(u) for u in list_users(db)]


@router.post("/users")
def create_user_endpoint(
    req: CreateUserRequest,
    db: Session = Depends(get_db_session),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> UserResponse:
    existing = get_user_by_username(db, req.username)
    if existing:
        raise HTTPException(409, "Username already exists")

    user = create_user(db, req.username, hash_password(req.password), role=req.role)
    record_audit(db, _admin.id, "create", "user", user.id, f"role={req.role}")
    db.commit()
    return UserResponse.from_orm(user)


@router.put("/users/{user_id}")
def update_user_endpoint(
    user_id: str,
    req: UpdateUserRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
) -> UserResponse:
    user = get_user(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    if user_id == admin.id and req.is_active is False:
        raise HTTPException(400, "Cannot deactivate your own account")

    if req.role is not None and req.role != "admin" and user.role == "admin":
        ensure_not_last_admin(db, user_id)

    password_hash = hash_password(req.password) if req.password else None
    invalidate_sessions = req.role is not None or req.is_active is False or req.password
    updated = update_user(
        db, user_id, role=req.role, is_active=req.is_active, password_hash=password_hash,
    )
    changes = []
    if req.role is not None:
        changes.append(f"role={req.role}")
    if req.is_active is not None:
        changes.append(f"active={req.is_active}")
    if req.password:
        changes.append("password_changed")
    if invalidate_sessions:
        delete_user_sessions(db, user_id)
    record_audit(db, admin.id, "update", "user", user_id, ", ".join(changes))
    db.commit()
    if invalidate_sessions:
        _clear_user_session_cache(request, user_id)
    return UserResponse.from_orm(updated)


@router.delete("/users/{user_id}")
def deactivate_user_endpoint(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
) -> StatusResponse:
    user = get_user(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    if user_id == admin.id:
        raise HTTPException(400, "Cannot deactivate your own account")

    if user.role == "admin":
        ensure_not_last_admin(db, user_id)

    update_user(db, user_id, is_active=False)
    delete_user_sessions(db, user_id)
    record_audit(db, admin.id, "deactivate", "user", user_id)
    db.commit()
    _clear_user_session_cache(request, user_id)
    return StatusResponse(status="ok")


@router.get("/audit-log")
def audit_log_endpoint(
    offset: int = Query(0, ge=0),
    limit: int = Query(PAGE_ADMIN_DEFAULT_LIMIT, ge=1, le=PAGE_ADMIN_MAX_LIMIT),
    db: Session = Depends(get_db_session),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> PaginatedResponse[AuditLogResponse]:
    total = count_audit_log(db)
    entries = list_audit_log(db, offset=offset, limit=limit)
    return PaginatedResponse(
        items=[AuditLogResponse.from_orm(e) for e in entries],
        total=total, offset=offset, limit=limit,
    )


@router.get("/login-attempts")
def login_attempts_endpoint(
    offset: int = Query(0, ge=0),
    limit: int = Query(PAGE_ADMIN_DEFAULT_LIMIT, ge=1, le=PAGE_ADMIN_MAX_LIMIT),
    db: Session = Depends(get_db_session),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> PaginatedResponse[LoginAttemptResponse]:
    total = count_login_attempts(db)
    attempts = list_login_attempts(db, offset=offset, limit=limit)
    return PaginatedResponse(
        items=[LoginAttemptResponse.from_orm(a) for a in attempts],
        total=total, offset=offset, limit=limit,
    )


@router.get("/sessions")
def sessions_endpoint(
    offset: int = Query(0, ge=0),
    limit: int = Query(PAGE_ADMIN_DEFAULT_LIMIT, ge=1, le=PAGE_ADMIN_MAX_LIMIT),
    db: Session = Depends(get_db_session),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> PaginatedResponse[SessionResponse]:
    total = count_active_sessions(db)
    sessions = list_active_sessions(db, offset=offset, limit=limit)
    return PaginatedResponse(
        items=[SessionResponse.from_orm(s) for s in sessions],
        total=total, offset=offset, limit=limit,
    )


@router.delete("/sessions/{session_hash}")
def force_logout_endpoint(
    session_hash: str,
    request: Request,
    db: Session = Depends(get_db_session),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> StatusResponse:
    for sess in list_active_sessions(db):
        if hmac.compare_digest(hashlib.sha256(sess.id.encode()).hexdigest(), session_hash):
            delete_session(db, sess.id)
            db.commit()
            session_cache: SessionCache | None = getattr(request.app.state, "session_cache", None)
            if session_cache:
                try:
                    session_cache.delete(sess.id, sess.user_id)
                except Exception:
                    log.warning("Redis session cache delete failed on force-logout")
            return StatusResponse(status="ok")
    raise HTTPException(404, "Session not found")


@router.post("/acestep/reinitialize")
def reinitialize_acestep(
    _admin: AuthenticatedUser = Depends(require_admin),
) -> StatusResponse:
    import json
    from urllib.request import Request, urlopen

    acestep_url = f"http://localhost:{ACESTEP_PORT}/v1/reinitialize"
    try:
        req = Request(
            acestep_url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST",
        )
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        if data.get("code") == 200:
            return StatusResponse(status="ok")
        log.warning("ACE-Step reinitialize returned: %s", data)
        raise HTTPException(502, "ACE-Step returned an error")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "ACE-Step server is unreachable") from exc


@router.get("/acestep/status")
def acestep_status(
    _admin: AuthenticatedUser = Depends(require_admin),
) -> AceStepStatusResponse:
    import json
    from urllib.request import Request, urlopen

    try:
        req = Request(f"http://localhost:{ACESTEP_PORT}/health", method="GET")
        with urlopen(req, timeout=5) as resp:
            health = json.loads(resp.read())

        req2 = Request(f"http://localhost:{ACESTEP_PORT}/v1/stats", method="GET")
        with urlopen(req2, timeout=5) as resp:
            stats = json.loads(resp.read())

        return AceStepStatusResponse(
            online=True,
            model=health.get("data", {}).get("loaded_model", "unknown"),
            lm_model=health.get("data", {}).get("loaded_lm_model", "unknown"),
            jobs=stats.get("data", {}).get("jobs", {}),
        )
    except Exception:
        return AceStepStatusResponse(online=False, model=None, lm_model=None, jobs={})

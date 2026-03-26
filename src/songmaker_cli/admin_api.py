"""Admin API endpoints — user management, sessions, login attempts."""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from songmaker_cli.api_models import (
    AuditLogResponse,
    CreateUserRequest,
    LoginAttemptResponse,
    SessionResponse,
    StatusResponse,
    UpdateUserRequest,
    UserResponse,
)
from songmaker_cli.auth import hash_password
from songmaker_cli.db.engine import get_db_session
from songmaker_cli.db.models import User as UserModel
from songmaker_cli.db.queries import (
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
from songmaker_cli.gpu_queue import ACESTEP_PORT
from songmaker_cli.middleware import AuthenticatedUser, require_admin

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


_get_session = get_db_session


@router.get("/users")
def list_users_endpoint(
    db: Session = Depends(_get_session),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> list[UserResponse]:
    return [UserResponse.from_orm(u) for u in list_users(db)]


@router.post("/users")
def create_user_endpoint(
    req: CreateUserRequest,
    db: Session = Depends(_get_session),
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
    db: Session = Depends(_get_session),
    admin: AuthenticatedUser = Depends(require_admin),
) -> UserResponse:
    user = get_user(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    if user_id == admin.id and req.is_active is False:
        raise HTTPException(400, "Cannot deactivate your own account")

    if req.role is not None and req.role != "admin" and user.role == "admin":
        admin_count = db.query(UserModel).filter_by(role="admin", is_active=True).count()
        if admin_count <= 1:
            raise HTTPException(400, "Cannot demote the last active admin")

    password_hash = hash_password(req.password) if req.password else None
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
    if req.role is not None or req.is_active is False or req.password:
        delete_user_sessions(db, user_id)
    record_audit(db, admin.id, "update", "user", user_id, ", ".join(changes))
    db.commit()
    return UserResponse.from_orm(updated)


@router.delete("/users/{user_id}")
def deactivate_user_endpoint(
    user_id: str,
    db: Session = Depends(_get_session),
    admin: AuthenticatedUser = Depends(require_admin),
) -> StatusResponse:
    user = get_user(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    if user_id == admin.id:
        raise HTTPException(400, "Cannot deactivate your own account")

    if user.role == "admin":
        admin_count = db.query(UserModel).filter_by(role="admin", is_active=True).count()
        if admin_count <= 1:
            raise HTTPException(400, "Cannot deactivate the last active admin")

    update_user(db, user_id, is_active=False)
    delete_user_sessions(db, user_id)
    record_audit(db, admin.id, "deactivate", "user", user_id)
    db.commit()
    return StatusResponse(status="ok")


@router.get("/audit-log")
def audit_log_endpoint(
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(_get_session),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> list[AuditLogResponse]:
    return [AuditLogResponse.from_orm(e) for e in list_audit_log(db, limit=limit)]


@router.get("/login-attempts")
def login_attempts_endpoint(
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(_get_session),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> list[LoginAttemptResponse]:
    return [LoginAttemptResponse.from_orm(a) for a in list_login_attempts(db, limit=limit)]


@router.get("/sessions")
def sessions_endpoint(
    db: Session = Depends(_get_session),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> list[SessionResponse]:
    return [SessionResponse.from_orm(s) for s in list_active_sessions(db)]


@router.delete("/sessions/{session_hash}")
def force_logout_endpoint(
    session_hash: str,
    db: Session = Depends(_get_session),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> StatusResponse:
    for sess in list_active_sessions(db):
        if hashlib.sha256(sess.id.encode()).hexdigest() == session_hash:
            delete_session(db, sess.id)
            db.commit()
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
) -> dict:
    import json
    from urllib.request import Request, urlopen

    try:
        req = Request(f"http://localhost:{ACESTEP_PORT}/health", method="GET")
        with urlopen(req, timeout=5) as resp:
            health = json.loads(resp.read())

        req2 = Request(f"http://localhost:{ACESTEP_PORT}/v1/stats", method="GET")
        with urlopen(req2, timeout=5) as resp:
            stats = json.loads(resp.read())

        return {
            "online": True,
            "model": health.get("data", {}).get("loaded_model", "unknown"),
            "lm_model": health.get("data", {}).get("loaded_lm_model", "unknown"),
            "jobs": stats.get("data", {}).get("jobs", {}),
        }
    except Exception:
        return {"online": False, "model": None, "lm_model": None, "jobs": {}}

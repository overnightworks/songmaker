"""Admin API endpoints — user management, sessions, login attempts."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from songmaker_cli.api_models import (
    CreateUserRequest,
    LoginAttemptResponse,
    SessionResponse,
    StatusResponse,
    UpdateUserRequest,
    UserResponse,
)
from songmaker_cli.auth import hash_password
from songmaker_cli.db.engine import get_db_session
from songmaker_cli.db.queries import (
    create_user,
    delete_session,
    get_user,
    get_user_by_username,
    list_active_sessions,
    list_login_attempts,
    list_users,
    update_user,
)
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
    if req.role not in ("admin", "user"):
        raise HTTPException(422, "Role must be 'admin' or 'user'")

    existing = get_user_by_username(db, req.username)
    if existing:
        raise HTTPException(409, f"Username '{req.username}' already exists")

    user = create_user(db, req.username, hash_password(req.password), role=req.role)
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

    if req.role is not None and req.role not in ("admin", "user"):
        raise HTTPException(422, "Role must be 'admin' or 'user'")

    if user_id == admin.id and req.is_active is False:
        raise HTTPException(400, "Cannot deactivate your own account")

    if user_id == admin.id and req.role is not None and req.role != "admin":
        raise HTTPException(400, "Cannot demote your own admin account")

    password_hash = hash_password(req.password) if req.password else None
    updated = update_user(
        db, user_id, role=req.role, is_active=req.is_active, password_hash=password_hash,
    )
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

    update_user(db, user_id, is_active=False)
    db.commit()
    return StatusResponse(status="ok")


@router.get("/login-attempts")
def login_attempts_endpoint(
    limit: int = 100,
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


@router.delete("/sessions/{session_id}")
def force_logout_endpoint(
    session_id: str,
    db: Session = Depends(_get_session),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> StatusResponse:
    delete_session(db, session_id)
    db.commit()
    return StatusResponse(status="ok")


@router.post("/acestep/reinitialize")
def reinitialize_acestep(
    _admin: AuthenticatedUser = Depends(require_admin),
) -> StatusResponse:
    import json
    from urllib.request import Request, urlopen

    acestep_url = "http://localhost:8001/v1/reinitialize"
    try:
        req = Request(
            acestep_url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST",
        )
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        if data.get("code") == 200:
            return StatusResponse(status="ok")
        raise HTTPException(502, f"ACE-Step error: {data}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"ACE-Step unreachable: {exc}") from exc


@router.get("/acestep/status")
def acestep_status(
    _admin: AuthenticatedUser = Depends(require_admin),
) -> dict:
    import json
    from urllib.request import Request, urlopen

    try:
        req = Request("http://localhost:8001/health", method="GET")
        with urlopen(req, timeout=5) as resp:
            health = json.loads(resp.read())

        req2 = Request("http://localhost:8001/v1/stats", method="GET")
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

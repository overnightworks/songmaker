"""songmaker's binding of the library's auth dependencies to its own request.

Regular dependencies commit authentication in a short, separate transaction
before the endpoint runs. Stream callers own their explicit transaction.
"""

from __future__ import annotations

import structlog
from fastapi import Depends, Request
from sqlalchemy.orm import Session
from webauth.config import WebAuthConfig, web_auth_config
from webauth.dependencies import AuthenticatedUser, current_user_dependency
from webauth.users import UserManagement

from songmaker_cli.app_context import get_app_context, get_db_session
from songmaker_cli.auth_stores import (
    DatabaseAuditSink,
    DatabaseSessionRecordStore,
    DatabaseUserStore,
    DatabaseWriteLock,
)


def user_management(
    request: Request,
    db: Session = Depends(get_db_session),
) -> UserManagement:
    return build_user_management(db, web_auth_config(request))


def build_user_management(db: Session, config: WebAuthConfig) -> UserManagement:
    return UserManagement(
        users=DatabaseUserStore(db),
        sessions=DatabaseSessionRecordStore(
            db, session_max_age_seconds=config.session_max_age_seconds,
        ),
        audit=DatabaseAuditSink(db),
        lock=DatabaseWriteLock(db),
        config=config,
    )


def _session_record_store(
    request: Request,
    db: Session = Depends(get_db_session),
) -> DatabaseSessionRecordStore:
    return DatabaseSessionRecordStore(
        db, session_max_age_seconds=web_auth_config(request).session_max_age_seconds,
    )


def _audit_sink(db: Session = Depends(get_db_session)) -> DatabaseAuditSink:
    return DatabaseAuditSink(db)


def _bind_user_to_log_context(user: AuthenticatedUser) -> None:
    structlog.contextvars.bind_contextvars(user_id=user.id)


_auth_dependencies = current_user_dependency(
    session_store=_session_record_store,
    audit_sink=_audit_sink,
    on_authenticated=_bind_user_to_log_context,
)


def get_current_user(request: Request) -> AuthenticatedUser:
    """Persist renewal and identity audit without committing endpoint writes."""
    with get_app_context(request).db.begin() as db:
        return authenticate_request(request, db)


def require_admin(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    return _auth_dependencies.admin_user(request, user)


def get_verified_session_id(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> str:
    return _auth_dependencies.verified_session_id(request, user)


def authenticate_request(request: Request, db: Session) -> AuthenticatedUser:
    """The account behind ``request``, resolved outside FastAPI's dependency graph.

    The stream endpoints call this instead of declaring `Depends`, because a
    yield dependency stays open until the whole response finishes — which for
    a stream means holding a pooled connection for its entire lifetime.
    """
    return _auth_dependencies.current_user(
        request, _session_record_store(request, db), DatabaseAuditSink(db),
    )

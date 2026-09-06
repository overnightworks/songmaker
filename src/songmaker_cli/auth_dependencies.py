"""songmaker's binding of the library's auth dependencies to its own request.

The stores arrive as dependencies over `get_db_session`, so FastAPI's
dependency cache hands the endpoint, the session store, and the audit sink
one and the same SQLAlchemy session: the session renewal and the audit
record become durable exactly when the endpoint commits, and vanish with the
rest of the request when it does not.
"""

from __future__ import annotations

import structlog
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from songmaker_cli.app_context import get_db_session
from songmaker_cli.auth_stores import DatabaseAuditSink, DatabaseSessionRecordStore
from webauth.dependencies import AuthenticatedUser, current_user_dependency


def _session_record_store(
    db: Session = Depends(get_db_session),
) -> DatabaseSessionRecordStore:
    return DatabaseSessionRecordStore(db)


def _audit_sink(db: Session = Depends(get_db_session)) -> DatabaseAuditSink:
    return DatabaseAuditSink(db)


def _bind_user_to_log_context(user: AuthenticatedUser) -> None:
    structlog.contextvars.bind_contextvars(user_id=user.id)


_auth_dependencies = current_user_dependency(
    session_store=_session_record_store,
    audit_sink=_audit_sink,
    on_authenticated=_bind_user_to_log_context,
)

get_current_user = _auth_dependencies.current_user
require_admin = _auth_dependencies.admin_user


def authenticate_request(request: Request, db: Session) -> AuthenticatedUser:
    """The account behind ``request``, resolved outside FastAPI's dependency graph.

    The stream endpoints call this instead of declaring `Depends`, because a
    yield dependency stays open until the whole response finishes — which for
    a stream means holding a pooled connection for its entire lifetime.
    """
    return get_current_user(request, DatabaseSessionRecordStore(db), DatabaseAuditSink(db))

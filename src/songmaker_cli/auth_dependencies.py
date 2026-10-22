"""songmaker's binding of the library's auth dependencies to its own request.

Regular dependencies commit authentication in a short, separate transaction
before the endpoint runs. Stream callers own their explicit transaction.
"""

from __future__ import annotations

import structlog
from fastapi import Depends, Request
from sqlalchemy.orm import Session
from webauth.dependencies import current_user_dependency
from webauth.ports import AuthenticatedUser

from songmaker_cli.app_context import get_app_context, get_db_session
from songmaker_cli.auth_stores import DatabaseSessionRecordStore


def _session_record_store(db: Session = Depends(get_db_session)) -> DatabaseSessionRecordStore:
    return DatabaseSessionRecordStore(db)


def _bind_user_to_log_context(user: AuthenticatedUser) -> None:
    structlog.contextvars.bind_contextvars(user_id=user.id)


_auth_dependencies = current_user_dependency(
    session_store=_session_record_store,
    on_authenticated=_bind_user_to_log_context,
)


def get_current_user(request: Request) -> AuthenticatedUser:
    """Persist the session renewal without committing endpoint writes."""
    with get_app_context(request).db.begin() as db:
        return authenticate_request(request, db)


def require_admin(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    return _auth_dependencies.admin_user(request, user)


def authenticate_request(request: Request, db: Session) -> AuthenticatedUser:
    """The account behind ``request``, resolved outside FastAPI's dependency graph.

    The stream endpoints call this instead of declaring `Depends`, because a
    yield dependency stays open until the whole response finishes — which for
    a stream means holding a pooled connection for its entire lifetime.
    """
    return _auth_dependencies.current_user(request, DatabaseSessionRecordStore(db))

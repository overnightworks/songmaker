"""Load the acting user for a tool call as the HTTP middleware would see them.

Every tool call re-reads the user from the DB (so a changed role takes effect
immediately) and wraps it in the same ``AuthenticatedUser`` dataclass the HTTP
middleware produces, so the ``check_*_access()`` helpers work unchanged.
"""
from __future__ import annotations

from sqlalchemy.orm import Session
from webauth.ports import AuthenticatedUser

from songmaker_cli.db.queries.auth import get_user


class ToolUserNotFoundError(RuntimeError):
    """Raised when the user a tool call acts for no longer exists."""


def load_user(session: Session, user_id: str) -> AuthenticatedUser:
    user = get_user(session, user_id)
    if user is None:
        raise ToolUserNotFoundError(f"User not found: {user_id}")
    return AuthenticatedUser(id=user.id, username=user.username, role=user.role)

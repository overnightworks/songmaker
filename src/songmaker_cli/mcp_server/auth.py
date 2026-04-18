"""Resolve the MCP subprocess's acting user from environment.

The chat backend spawns the CLI → MCP subprocess chain with
``SONGMAKER_MCP_USER_ID`` set to the authenticated caller's user id.
Every tool call re-reads the user from the DB (so deactivations take
effect immediately) and wraps it in the same ``AuthenticatedUser``
dataclass the HTTP middleware produces — that way the existing
``check_*_access()`` helpers work unchanged.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from songmaker_cli.db.queries.auth import get_user
from songmaker_cli.middleware.auth import AuthenticatedUser
from songmaker_cli.settings import get_settings

USER_ID_ENV = "SONGMAKER_MCP_USER_ID"


class MCPAuthError(RuntimeError):
    """Raised when the MCP subprocess cannot identify or load the caller."""


def require_user_id() -> str:
    user_id = get_settings().songmaker_mcp_user_id
    if not user_id:
        raise MCPAuthError(
            f"{USER_ID_ENV} not set — MCP server must be spawned by the "
            "songmaker chat backend, not directly."
        )
    return user_id


def load_user(session: Session, user_id: str) -> AuthenticatedUser:
    user = get_user(session, user_id)
    if user is None:
        raise MCPAuthError(f"User not found: {user_id}")
    if not user.is_active:
        raise MCPAuthError(f"User is deactivated: {user.username}")
    return AuthenticatedUser(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
    )

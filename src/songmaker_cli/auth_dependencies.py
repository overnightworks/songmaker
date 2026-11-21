"""songmaker's names for the library's auth dependencies.

`WebAuth.install` binds the session transaction, so `current_user` renews and reads the session in
its own short transaction before the endpoint runs. A stream endpoint calls it directly, before it
opens the session its stream reads from, because a yield dependency would hold a pooled
connection for the whole stream.
"""

from __future__ import annotations

from fastapi import Depends, Request
from webauth.dependencies import admin_user, current_user
from webauth.middleware import is_resource_admission
from webauth.ports import AuthenticatedUser

from songmaker_cli.refusals import Refusal

get_current_user = current_user
require_admin = admin_user


def require_sharing_caller(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Refuse a person's own agent a public share; a session, a hal token and an agent pass."""
    if is_resource_admission(request) and user.agent is None:
        raise Refusal(403, "shareRefusal.personsAgent")
    return user

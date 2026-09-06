"""Middleware — authentication dependencies and HTTP middleware stack.

The rate-limit, CSRF, body-size, and security-header middlewares now live in
`webauth.middleware` and are re-exported here while the auth dependencies
below still sit beside them; B4 moves those and drops this re-export.
"""

from __future__ import annotations

from songmaker_cli.middleware.access_log import AccessLogMiddleware
from songmaker_cli.middleware.auth import (
    SESSION_COOKIE,
    AuthenticatedUser,
    get_current_user,
    require_admin,
)
from songmaker_cli.middleware.gzip import SelectiveGZipMiddleware
from songmaker_cli.middleware.resource_stream_deadline import (
    ResourceStreamDeadlineMiddleware,
)
from webauth.middleware import (
    BodySizeLimitMiddleware,
    CsrfOriginMiddleware,
    CsrfTokenMiddleware,
    IpRateLimitMiddleware,
    SecurityHeadersMiddleware,
)

__all__ = [
    "SESSION_COOKIE",
    "AccessLogMiddleware",
    "AuthenticatedUser",
    "BodySizeLimitMiddleware",
    "CsrfOriginMiddleware",
    "CsrfTokenMiddleware",
    "IpRateLimitMiddleware",
    "ResourceStreamDeadlineMiddleware",
    "SecurityHeadersMiddleware",
    "SelectiveGZipMiddleware",
    "get_current_user",
    "require_admin",
]

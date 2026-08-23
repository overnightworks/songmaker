"""Middleware — authentication dependencies and HTTP middleware stack."""

from __future__ import annotations

from songmaker_cli.middleware.access_log import AccessLogMiddleware
from songmaker_cli.middleware.auth import (
    SESSION_COOKIE,
    AuthenticatedUser,
    get_current_user,
    require_admin,
)
from songmaker_cli.middleware.body_size import BodySizeLimitMiddleware
from songmaker_cli.middleware.csrf import (
    CsrfOriginMiddleware,
    CsrfTokenMiddleware,
)
from songmaker_cli.middleware.gzip import SelectiveGZipMiddleware
from songmaker_cli.middleware.rate_limit import IpRateLimitMiddleware
from songmaker_cli.middleware.resource_stream_deadline import (
    ResourceStreamDeadlineMiddleware,
)
from songmaker_cli.middleware.security_headers import SecurityHeadersMiddleware

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

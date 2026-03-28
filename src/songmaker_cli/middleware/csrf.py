"""CSRF protection middleware -- double-submit cookie and origin checking."""

from __future__ import annotations

import re

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from songmaker_cli.app_context import AppContext

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_FORM_CONTENT_TYPES = frozenset({
    "application/x-www-form-urlencoded",
    "multipart/form-data",
    "text/plain",
})

_LOCALHOST_PATTERN = re.compile(r"^(localhost|127\.0\.0\.1)(:\d+)?$")

_CSRF_EXEMPT_PATHS = frozenset({"/api/auth/login", "/api/auth/setup"})


class CsrfTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if (
            request.method in _MUTATING_METHODS
            and request.url.path.startswith("/api/")
            and request.url.path not in _CSRF_EXEMPT_PATHS
        ):
            from songmaker_cli.auth import CSRF_HEADER, verify_csrf_token, verify_session_cookie
            from songmaker_cli.middleware.auth import SESSION_COOKIE

            ctx: AppContext = request.app.state.ctx
            header_token = request.headers.get(CSRF_HEADER)
            if not header_token:
                return JSONResponse(
                    {"detail": "CSRF token missing or invalid"}, status_code=403,
                )
            raw_cookie = request.cookies.get(SESSION_COOKIE)
            secret = ctx.session_secret
            session_id = verify_session_cookie(raw_cookie, secret) if raw_cookie else None
            if not session_id or not verify_csrf_token(header_token, session_id, secret):
                return JSONResponse(
                    {"detail": "CSRF token missing or invalid"}, status_code=403,
                )
        return await call_next(request)


def _is_allowed_host(
    netloc: str,
    exact: frozenset[str],
    patterns: list[re.Pattern[str]],
) -> bool:
    host_without_port = netloc.rsplit(":", 1)[0] if ":" in netloc else netloc
    if exact or patterns:
        if netloc in exact or host_without_port in exact:
            return True
        return any(p.match(netloc) for p in patterns)
    return bool(_LOCALHOST_PATTERN.match(netloc))


class CsrfOriginMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if (
            request.method in _MUTATING_METHODS
            and request.url.path.startswith("/api/")
        ):
            origin = request.headers.get("origin") or request.headers.get("referer")
            if origin:
                from urllib.parse import urlparse
                ctx: AppContext = request.app.state.ctx
                parsed = urlparse(origin)
                origin_host = parsed.netloc
                if origin_host and not _is_allowed_host(
                    origin_host, ctx.allowed_hosts_exact, ctx.allowed_hosts_patterns,
                ):
                    return JSONResponse(
                        {"detail": "Cross-origin request rejected"},
                        status_code=403,
                    )
            else:
                content_type = (request.headers.get("content-type") or "").split(";")[0].strip()
                if content_type in _FORM_CONTENT_TYPES:
                    return JSONResponse(
                        {"detail": "Missing Origin header on form submission"},
                        status_code=403,
                    )
        return await call_next(request)

"""Security headers middleware -- CSP, HSTS, and related headers."""

from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from songmaker_cli.app_context import AppContext


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, script_hashes: list[str] | None = None) -> None:
        super().__init__(app)
        script_src = "'self'"
        for h in script_hashes or []:
            script_src += f" '{h}'"
        self._csp = (
            "default-src 'none'; "
            f"script-src {script_src}; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "connect-src 'self'; "
            "img-src 'self' data: blob:; "
            "media-src 'self' blob:; "
            "font-src 'self' https://fonts.gstatic.com; "
            "manifest-src 'self'; "
            "frame-ancestors 'none'"
        )

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = self._csp
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        is_https = request.url.scheme == "https"
        if not is_https:
            ctx: AppContext = request.app.state.ctx
            direct_ip = request.client.host if request.client else ""
            if ctx.trusted_proxies and direct_ip in ctx.trusted_proxies:
                is_https = request.headers.get("x-forwarded-proto", "") == "https"
        if is_https:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

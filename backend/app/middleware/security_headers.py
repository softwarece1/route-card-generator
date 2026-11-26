"""Security headers middleware for VAPT hardening."""
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        # script-src 'self' only — theme bootstrap is an external /theme-boot.js file.
        # style-src keeps 'unsafe-inline' because PrimeReact injects inline styles.
        self.csp = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self' data:; "
            "base-uri 'self'; "
            "object-src 'none'; "
            "form-action 'self'; "
            "frame-ancestors 'none';"
        )

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = self.csp
        return response

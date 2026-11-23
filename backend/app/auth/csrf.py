"""Origin / Referer allowlist for cookie-authenticated mutating requests."""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth.cookies import access_cookie_name
from app.config.settings import cors_allow_origins

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def _origin_allowed(origin: str, allowlist: list[str]) -> bool:
    o = (origin or "").strip().rstrip("/")
    if not o:
        return False
    return o in {a.rstrip("/") for a in allowlist}


def _request_origin(request: Request) -> str | None:
    origin = (request.headers.get("origin") or "").strip()
    if origin:
        return origin.rstrip("/")
    referer = (request.headers.get("referer") or "").strip()
    if not referer:
        return None
    try:
        p = urlparse(referer)
        if not p.scheme or not p.netloc:
            return None
        return f"{p.scheme}://{p.netloc}".rstrip("/")
    except Exception:
        return None


class CookieCsrfMiddleware(BaseHTTPMiddleware):
    """
    When the access cookie is present on a mutating API request, require
    Origin/Referer (if sent) to match the CORS allowlist. Missing both headers
    is allowed for non-browser clients / TestClient; browsers send Origin on XHR.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method.upper() in _SAFE_METHODS:
            return await call_next(request)

        cookie_name = access_cookie_name()
        if not request.cookies.get(cookie_name):
            return await call_next(request)

        path = request.url.path or ""
        if not path.startswith("/api/"):
            return await call_next(request)

        origin = _request_origin(request)
        if origin is None:
            return await call_next(request)

        allowlist = cors_allow_origins()
        if _origin_allowed(origin, allowlist):
            return await call_next(request)

        return JSONResponse(
            status_code=403,
            content={"detail": "CSRF check failed: Origin not allowed"},
        )

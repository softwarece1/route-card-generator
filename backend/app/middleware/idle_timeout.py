"""Idle session timeout middleware — cookie or Bearer JWT activity.

The database ``last_seen_at`` column is the source of truth so a process
restart still expires an idle session. Login and other anonymous auth routes
are skipped so a stale cookie cannot block a new sign-in.
"""

from datetime import datetime

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.settings import settings

_SKIP_PREFIXES = (
    "/api/v1/auth/login",
    "/api/v1/auth/signup",
    "/api/v1/auth/captcha",
    "/api/v1/auth/public-key",
    "/api/v1/auth/config",
    "/api/v1/auth/sbus",
    "/api/v1/auth/emp-status",
)


def _extract_token(request: Request) -> str | None:
    from app.auth.cookies import access_cookie_name

    cookie = request.cookies.get(access_cookie_name())
    if cookie:
        return cookie
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(None, 1)[1].strip() or None
    return None


def _skip(path: str) -> bool:
    if not path.startswith("/api/"):
        return True
    return any(path.startswith(prefix) for prefix in _SKIP_PREFIXES)


class IdleSessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path or ""
        token = None if _skip(path) else _extract_token(request)
        if token:
            try:
                from app.auth.tokens import decode_token

                payload = decode_token(token)
            except Exception:
                return await call_next(request)
            jti = payload.get("jti")
            if jti:
                from app.auth.sessions import revoke_jti, session_last_seen, touch_session

                last = session_last_seen(jti)
                timeout = int(getattr(settings, "IDLE_TIMEOUT_MINUTES", 15) or 15) * 60
                if last is not None and (datetime.utcnow() - last).total_seconds() > timeout:
                    revoke_jti(jti)
                    return JSONResponse(
                        {"detail": "Session expired due to inactivity"},
                        status_code=401,
                    )
                try:
                    touch_session(jti)
                except Exception:
                    pass
        return await call_next(request)

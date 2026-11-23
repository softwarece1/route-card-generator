"""Idle session timeout middleware — cookie or Bearer JWT activity."""

from datetime import datetime, timezone

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.settings import settings

# In-memory last-seen cache keyed by jti (DB last_seen_at updated periodically)
_idle_store: dict[str, datetime] = {}


def _extract_token(request: Request) -> str | None:
    from app.auth.cookies import access_cookie_name

    cookie = request.cookies.get(access_cookie_name())
    if cookie:
        return cookie
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(None, 1)[1].strip() or None
    return None


class IdleSessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = _extract_token(request)
        if token:
            try:
                from app.auth import decode_token
                from app.auth.sessions import revoke_jti, touch_session

                payload = decode_token(token)
                jti = payload.get("jti")
                if jti:
                    now = datetime.now(timezone.utc)
                    last = _idle_store.get(jti)
                    timeout = getattr(settings, "IDLE_TIMEOUT_MINUTES", 15) * 60
                    if last and (now - last).total_seconds() > timeout:
                        revoke_jti(jti)
                        _idle_store.pop(jti, None)
                        return JSONResponse(
                            {"detail": "Session expired due to inactivity"},
                            status_code=401,
                        )
                    _idle_store[jti] = now
                    # Persist last_seen occasionally (every request is fine for LAN scale)
                    try:
                        touch_session(jti)
                    except Exception:
                        pass
            except Exception:
                pass
        return await call_next(request)

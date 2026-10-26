"""Idle session timeout middleware tracking JWT activity."""
from datetime import datetime, timezone
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.config.settings import settings

# In‑memory store for idle session tracking: jti -> last activity timestamp (UTC)
_idle_store: dict[str, datetime] = {}

class IdleSessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Extract token JTI if present
        auth: str | None = request.headers.get("authorization")
        if auth and auth.lower().startswith("bearer "):
            token = auth.split()[1]
            from app.auth import decode_token
            try:
                payload = decode_token(token)
                jti: str = payload.get("jti")
                if jti:
                    now = datetime.now(timezone.utc)
                    last = _idle_store.get(jti)
                    timeout = getattr(settings, "IDLE_TIMEOUT_MINUTES", 15) * 60
                    if last and (now - last).total_seconds() > timeout:
                        # Expire session
                        from app.auth import _revoked_tokens
                        _revoked_tokens.add(jti)
                        return JSONResponse({"detail": "Session expired due to inactivity"}, status_code=401)
                    # Update last activity
                    _idle_store[jti] = now
            except Exception:
                pass  # Token errors handled elsewhere
        response = await call_next(request)
        return response

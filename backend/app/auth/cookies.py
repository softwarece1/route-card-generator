"""httpOnly access cookie helpers (no refresh cookie)."""

from __future__ import annotations

from fastapi import Request, Response

from app.config.settings import cookie_secure, settings


def access_cookie_name() -> str:
    return (getattr(settings, "AUTH_COOKIE_NAME", None) or "rc_access").strip() or "rc_access"


def access_cookie_max_age() -> int:
    return max(60, int(settings.ACCESS_TOKEN_EXPIRE_MINUTES) * 60)


def set_access_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=access_cookie_name(),
        value=token,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        path="/",
        max_age=access_cookie_max_age(),
    )


def clear_access_cookie(response: Response) -> None:
    response.delete_cookie(
        key=access_cookie_name(),
        path="/",
        samesite="lax",
        secure=cookie_secure(),
    )


def read_access_token(request: Request) -> str | None:
    """Cookie first, then Authorization Bearer (scripts / tests)."""
    name = access_cookie_name()
    raw = request.cookies.get(name)
    if raw:
        return raw
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return token or None
    return None

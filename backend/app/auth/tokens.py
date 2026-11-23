"""Access JWT create / decode (no refresh tokens)."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from jose import JWTError, jwt

from app.config.settings import settings


def create_access_token(*, emp_id: str, role: str, user_id: int) -> tuple[str, str, datetime]:
    """
    Build a signed access JWT.

    Returns ``(token, jti, expires_at_utc)``. Caller registers the session in DB.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    jti = secrets.token_urlsafe(16)
    payload = {
        "sub": emp_id,
        "role": role,
        "uid": user_id,
        "exp": expire,
        "jti": jti,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, jti, expire


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from e

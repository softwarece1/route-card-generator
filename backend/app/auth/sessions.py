"""DB-backed auth sessions (access jti) + short-lived takeover resume tokens."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from fastapi import HTTPException, status
from pony.orm import commit, db_session, desc, select

from app.route_card.models import RcAuthSession, RcUser

# Short-lived tokens after concurrent-login 409 — confirm takeover without re-CAPTCHA
# resumeToken -> {user_id, emp_id, role, exp}
_pending_session_takeovers: dict[str, dict] = {}
_TAKEOVER_TTL_SEC = 120


@db_session
def active_jti_for_user(user_id: int) -> str | None:
    now = datetime.utcnow()
    rows = select(
        s
        for s in RcAuthSession
        if s.user.id == user_id
        and s.revoked_at is None
        and s.is_active
        and s.expires_at > now
    ).order_by(desc(RcAuthSession.created_at))[:1]
    return rows[0].access_jti if rows else None


@db_session
def has_active_session(user_id: int) -> bool:
    return bool(active_jti_for_user(user_id))


@db_session
def create_session(
    *,
    user_id: int,
    access_jti: str,
    expires_at: datetime,
    user_agent: str = "",
    ip: str = "",
    revoke_others: bool = True,
) -> RcAuthSession:
    user = RcUser.get(id=user_id)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    now = datetime.utcnow()
    exp = expires_at.replace(tzinfo=None) if expires_at.tzinfo else expires_at

    if revoke_others:
        for s in select(
            x
            for x in RcAuthSession
            if x.user.id == user_id and (x.revoked_at is None or x.is_active)
        ):
            s.revoked_at = now
            s.is_active = False

    row = RcAuthSession(
        user=user,
        access_jti=access_jti,
        user_agent=(user_agent or "")[:512],
        ip=(ip or "")[:64],
        expires_at=exp,
        revoked_at=None,
        is_active=True,
        created_at=now,
        last_seen_at=now,
    )
    commit()
    return row


@db_session
def revoke_jti(jti: str | None) -> None:
    if not jti:
        return
    now = datetime.utcnow()
    for s in select(x for x in RcAuthSession if x.access_jti == jti and x.revoked_at is None):
        s.revoked_at = now
        s.is_active = False
    commit()


@db_session
def revoke_user_sessions(user_id: int) -> None:
    now = datetime.utcnow()
    for s in select(
        x
        for x in RcAuthSession
        if x.user.id == user_id and (x.revoked_at is None or x.is_active)
    ):
        s.revoked_at = now
        s.is_active = False
    commit()


@db_session
def is_jti_active(jti: str | None, user_id: int | None = None) -> bool:
    if not jti:
        return False
    now = datetime.utcnow()
    row = RcAuthSession.get(access_jti=jti)
    if not row or row.revoked_at is not None or not row.is_active:
        return False
    if row.expires_at <= now:
        return False
    if user_id is not None and row.user.id != int(user_id):
        return False
    return True


@db_session
def touch_session(jti: str) -> None:
    row = RcAuthSession.get(access_jti=jti)
    if row and row.revoked_at is None and row.is_active:
        row.last_seen_at = datetime.utcnow()
        commit()


@db_session
def session_last_seen(jti: str) -> datetime | None:
    row = RcAuthSession.get(access_jti=jti)
    if not row:
        return None
    return row.last_seen_at


def _purge_expired_takeovers() -> None:
    now = datetime.now(timezone.utc).timestamp()
    dead = [k for k, v in _pending_session_takeovers.items() if float(v.get("exp") or 0) < now]
    for k in dead:
        _pending_session_takeovers.pop(k, None)


def issue_takeover_resume(*, user_id: int, emp_id: str, role: str) -> str:
    _purge_expired_takeovers()
    token = secrets.token_urlsafe(24)
    _pending_session_takeovers[token] = {
        "user_id": int(user_id),
        "emp_id": emp_id,
        "role": role,
        "exp": datetime.now(timezone.utc).timestamp() + _TAKEOVER_TTL_SEC,
    }
    return token


def consume_takeover_resume(resume_token: str) -> dict:
    _purge_expired_takeovers()
    pending = _pending_session_takeovers.pop((resume_token or "").strip(), None)
    if not pending:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session takeover expired. Please sign in again.",
        )
    return pending


# Back-compat aliases used by older tests
def _issue_takeover_resume(*, user_id: int, emp_id: str, role: str) -> str:
    return issue_takeover_resume(user_id=user_id, emp_id=emp_id, role=role)


def _consume_takeover_resume(resume_token: str) -> dict:
    return consume_takeover_resume(resume_token)

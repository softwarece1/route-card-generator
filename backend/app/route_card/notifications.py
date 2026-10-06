"""In-app notifications + optional webhook (Phase 5 / 2A)."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import HTTPException
from pony.orm import commit, db_session, desc, select

from app.config.settings import settings
from app.route_card.models import RcNotification, RcUser

logger = logging.getLogger(__name__)


def notification_dict(n: RcNotification) -> dict:
    return {
        "id": n.id,
        "title": n.title,
        "body": n.body or "",
        "link": n.link or "",
        "readAt": n.read_at.isoformat() + "Z" if n.read_at else None,
        "createdAt": n.created_at.isoformat() + "Z" if n.created_at else None,
    }


def _fire_webhook(payload: dict) -> None:
    url = (getattr(settings, "NOTIFY_WEBHOOK_URL", None) or "").strip()
    if not url:
        return
    try:
        import httpx

        with httpx.Client(timeout=5.0, trust_env=False) as client:
            client.post(url, json=payload)
    except Exception as exc:
        logger.warning("notify webhook failed: %s", exc)


@db_session
def create_notification(
    user_id: int | None,
    title: str,
    body: str = "",
    link: str = "",
    emp_id: str | None = None,
) -> dict | None:
    user = None
    if user_id:
        user = RcUser.get(id=user_id)
    elif emp_id:
        user = RcUser.get(emp_id=emp_id)
    if not user:
        return None
    n = RcNotification(user=user, title=title, body=body or "", link=link or "")
    commit()
    out = notification_dict(n)
    _fire_webhook(
        {
            **out,
            "userEmpId": user.emp_id,
            "userId": user.id,
        }
    )
    return out


@db_session
def list_notifications(user: dict, unread_only: bool = False, limit: int = 50) -> dict:
    uid = user.get("id")
    if not uid:
        raise HTTPException(401, "Not authenticated")
    q = select(n for n in RcNotification if n.user.id == uid)
    if unread_only:
        q = select(n for n in RcNotification if n.user.id == uid and n.read_at is None)
    rows = q.order_by(desc(RcNotification.created_at))[: max(1, min(limit, 200))]
    unread = select(
        n for n in RcNotification if n.user.id == uid and n.read_at is None
    ).count()
    return {"items": [notification_dict(n) for n in rows], "unreadCount": unread}


@db_session
def mark_notification_read(notification_id: int, user: dict) -> dict:
    n = RcNotification.get(id=notification_id)
    if not n or n.user.id != user.get("id"):
        raise HTTPException(404, "Notification not found")
    if not n.read_at:
        n.read_at = datetime.utcnow()
        commit()
    return notification_dict(n)


@db_session
def mark_all_read(user: dict) -> dict:
    uid = user.get("id")
    now = datetime.utcnow()
    for n in select(x for x in RcNotification if x.user.id == uid and x.read_at is None):
        n.read_at = now
    commit()
    return {"ok": True}

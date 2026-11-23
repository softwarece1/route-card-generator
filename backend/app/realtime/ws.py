"""Cookie-authenticated WebSocket for live notifications."""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pony.orm import db_session

from app.auth.cookies import access_cookie_name
from app.auth.sessions import is_jti_active
from app.auth.tokens import decode_token
from app.config.settings import settings
from app.realtime.hub import hub
from app.route_card.models import RcUser
from app.route_card.notifications import list_notifications

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])


def _user_from_cookie(websocket: WebSocket) -> dict | None:
    if not settings.AUTH_ENABLED:
        return {
            "id": 0,
            "empId": "dev",
            "role": "admin",
        }
    token = websocket.cookies.get(access_cookie_name())
    if not token:
        auth = websocket.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            token = auth.split(None, 1)[1].strip()
    if not token:
        return None
    try:
        data = decode_token(token)
    except Exception:
        return None
    jti = data.get("jti")
    uid = data.get("uid")
    with db_session:
        user = RcUser.get(id=int(uid)) if uid else None
        if not user and data.get("sub"):
            user = RcUser.get(emp_id=str(data.get("sub")))
        if not user or not user.is_active:
            return None
        if not jti or not is_jti_active(jti, user.id):
            return None
        return {
            "id": user.id,
            "empId": user.emp_id,
            "role": user.role,
        }


@router.websocket("/api/v1/ws/notifications")
async def notifications_ws(websocket: WebSocket):
    user = _user_from_cookie(websocket)
    if not user or not user.get("id"):
        await websocket.close(code=1008)
        return

    uid = int(user["id"])
    await hub.connect(uid, websocket)
    try:
        snap = list_notifications(user, unread_only=False, limit=50)
        await websocket.send_json(
            {
                "type": "hello",
                "items": snap.get("items") or [],
                "unreadCount": snap.get("unreadCount") or 0,
            }
        )
        while True:
            # Keepalive / ignore client pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("notifications ws ended: %s", exc)
    finally:
        await hub.disconnect(uid, websocket)

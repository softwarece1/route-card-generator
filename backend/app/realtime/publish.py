"""Helpers to push notification events onto the realtime hub."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.realtime.hub import hub

logger = logging.getLogger(__name__)


def publish_notification(user_id: int, item: dict[str, Any], unread_count: int | None = None) -> None:
    """Fire-and-forget from sync code (create_notification)."""
    payload: dict[str, Any] = {
        "type": "notification",
        "item": item,
    }
    if unread_count is not None:
        payload["unreadCount"] = unread_count

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No event loop (rare sync context) — skip push; REST still has the row
        logger.debug("no event loop for notification push user=%s", user_id)
        return

    loop.create_task(_safe_publish(int(user_id), payload))


async def _safe_publish(user_id: int, payload: dict[str, Any]) -> None:
    try:
        await hub.publish(user_id, payload)
    except Exception as exc:
        logger.warning("realtime publish failed: %s", exc)

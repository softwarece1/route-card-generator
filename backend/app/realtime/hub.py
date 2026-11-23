"""In-process WebSocket fan-out hub keyed by user id."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class RealtimeHub:
    def __init__(self) -> None:
        self._rooms: dict[int, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._rooms.setdefault(int(user_id), set()).add(ws)

    async def disconnect(self, user_id: int, ws: WebSocket) -> None:
        async with self._lock:
            room = self._rooms.get(int(user_id))
            if not room:
                return
            room.discard(ws)
            if not room:
                self._rooms.pop(int(user_id), None)

    async def publish(self, user_id: int, message: dict[str, Any]) -> None:
        async with self._lock:
            sockets = list(self._rooms.get(int(user_id), set()))
        dead: list[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(user_id, ws)


hub = RealtimeHub()

"""In-process WebSocket hub.

One hub instance per process (the app is single-worker by design). Each client
holds one connection per campaign and subscribes to scene channels over it.
Broadcasts fan out via per-connection queues so one slow client can't stall
the game; a client whose queue overflows is dropped and resyncs on reconnect.
"""

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("hallucinatingdm.hub")

QUEUE_SIZE = 256


@dataclass(eq=False)  # identity hash: connections live in sets
class Connection:
    ws: WebSocket
    user_id: str
    campaign_id: str
    is_dm: bool
    scene_ids: set[str] = field(default_factory=set)
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=QUEUE_SIZE))
    writer_task: asyncio.Task | None = None


class Hub:
    def __init__(self) -> None:
        self._rooms: dict[str, set[Connection]] = {}

    async def connect(self, conn: Connection) -> None:
        await conn.ws.accept()
        self._rooms.setdefault(conn.campaign_id, set()).add(conn)
        conn.writer_task = asyncio.create_task(self._writer(conn))

    def disconnect(self, conn: Connection) -> None:
        room = self._rooms.get(conn.campaign_id)
        if room:
            room.discard(conn)
            if not room:
                self._rooms.pop(conn.campaign_id, None)
        if conn.writer_task:
            conn.writer_task.cancel()

    async def _writer(self, conn: Connection) -> None:
        try:
            while True:
                event = await conn.queue.get()
                await conn.ws.send_json(event)
        except asyncio.CancelledError:
            pass
        except Exception:
            # Socket died mid-send; the reader loop will clean up.
            with contextlib.suppress(Exception):
                await conn.ws.close()

    def broadcast(
        self,
        campaign_id: str,
        event: dict[str, Any],
        scene_id: str | None = None,
        dm_only: bool = False,
        only_user_id: str | None = None,
    ) -> None:
        """Fan an event out to a campaign room.

        scene_id: only connections subscribed to that scene receive it
        dm_only: only DM connections receive it
        only_user_id: only that user's connections receive it (private prompts)
        """
        for conn in self._rooms.get(campaign_id, set()).copy():
            if dm_only and not conn.is_dm:
                continue
            if only_user_id and conn.user_id != only_user_id:
                continue
            if scene_id and scene_id not in conn.scene_ids:
                continue
            try:
                conn.queue.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("dropping slow ws connection (user=%s)", conn.user_id)
                self.disconnect(conn)

    def campaign_user_ids(self, campaign_id: str) -> set[str]:
        return {c.user_id for c in self._rooms.get(campaign_id, set())}


hub = Hub()

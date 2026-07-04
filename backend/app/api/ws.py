import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import get_membership
from app.db import get_sessionmaker
from app.models import Scene, User
from app.realtime.hub import Connection, hub
from app.services.auth_service import COOKIE_NAME, decode_access_token

log = logging.getLogger("landl.ws")

router = APIRouter()


@router.websocket("/ws/campaigns/{campaign_id}")
async def campaign_ws(ws: WebSocket, campaign_id: str) -> None:
    token = ws.cookies.get(COOKIE_NAME)
    user_id = decode_access_token(token) if token else None
    if not user_id:
        await ws.close(code=4401)
        return

    async with get_sessionmaker()() as db:
        user = await db.get(User, user_id)
        member = await get_membership(db, campaign_id, user_id) if user else None
        if not member:
            await ws.close(code=4403)
            return
        is_dm = member.role == "dm"

    conn = Connection(ws=ws, user_id=user_id, campaign_id=campaign_id, is_dm=is_dm)
    await hub.connect(conn)
    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")
            if msg_type == "scene.subscribe":
                scene_id = str(data.get("scene_id", ""))
                async with get_sessionmaker()() as db:
                    scene = await db.get(Scene, scene_id)
                if scene and scene.campaign_id == campaign_id:
                    conn.scene_ids.add(scene_id)
                    await ws.send_json({"type": "scene.subscribed", "scene_id": scene_id})
            elif msg_type == "scene.unsubscribe":
                conn.scene_ids.discard(str(data.get("scene_id", "")))
            elif msg_type == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("ws error (user=%s)", user_id)
    finally:
        hub.disconnect(conn)

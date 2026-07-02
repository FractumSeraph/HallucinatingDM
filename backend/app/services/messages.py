"""Message creation: per-scene sequence numbers + persistence + broadcast.

Single code path used by the REST API, the dice roller, and the AI DM, so every
author type flows through identical ordering and fan-out.
"""

import asyncio
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DiceRoll, Message, Scene
from app.realtime import events
from app.realtime.hub import hub
from app.services import dice as dice_service

# Serializes seq allocation per scene (single-process app).
_scene_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def message_out(msg: Message) -> dict[str, Any]:
    return {
        "id": msg.id,
        "scene_id": msg.scene_id,
        "seq": msg.seq,
        "author_type": msg.author_type,
        "author_user_id": msg.author_user_id,
        "character_id": msg.character_id,
        "kind": msg.kind,
        "content": msg.content,
        "payload_json": msg.payload_json,
        "visibility": msg.visibility,
        "struck": msg.struck,
        "created_at": msg.created_at.isoformat(),
    }


async def create_message(
    db: AsyncSession,
    scene: Scene,
    *,
    author_type: str,
    content: str,
    kind: str = "chat",
    author_user_id: str | None = None,
    character_id: str | None = None,
    payload: dict[str, Any] | None = None,
    visibility: str = "all",
    broadcast: bool = True,
) -> Message:
    async with _scene_locks[scene.id]:
        next_seq = (
            await db.execute(
                select(func.coalesce(func.max(Message.seq), 0)).where(
                    Message.scene_id == scene.id
                )
            )
        ).scalar_one() + 1
        msg = Message(
            scene_id=scene.id,
            seq=next_seq,
            author_type=author_type,
            author_user_id=author_user_id,
            character_id=character_id,
            kind=kind,
            content=content,
            payload_json=payload or {},
            visibility=visibility,
        )
        db.add(msg)
        await db.commit()

    if broadcast:
        hub.broadcast(
            scene.campaign_id,
            events.make_event(
                events.MESSAGE_CREATED, scene.campaign_id, message_out(msg), scene.id
            ),
            scene_id=scene.id,
            dm_only=visibility in ("dm", "dm_ai"),
        )
    return msg


async def create_roll_message(
    db: AsyncSession,
    scene: Scene,
    *,
    expression: str,
    purpose: str = "raw",
    roller_name: str = "",
    author_type: str = "player",
    author_user_id: str | None = None,
    character_id: str | None = None,
    detail: dict[str, Any] | None = None,
    result: dice_service.DiceResult | None = None,
) -> tuple[Message, DiceRoll]:
    """Roll server-side, persist the audited roll, and post it as a message."""
    rolled = result or dice_service.roll(expression)
    detail = detail or {}

    payload = {
        "roll": {
            **rolled.as_dict(),
            "purpose": purpose,
            "roller_name": roller_name,
            **detail,
        }
    }
    label = f"**{roller_name or 'Someone'}** rolls `{rolled.expression}` → **{rolled.total}**"
    msg = await create_message(
        db,
        scene,
        author_type=author_type,
        author_user_id=author_user_id,
        character_id=character_id,
        kind="roll",
        content=label,
        payload=payload,
    )

    roll_row = DiceRoll(
        scene_id=scene.id,
        message_id=msg.id,
        roller_user_id=author_user_id,
        character_id=character_id,
        roller_name=roller_name,
        expression=rolled.expression,
        rolls_json=rolled.rolls,
        modifier=rolled.modifier,
        total=rolled.total,
        purpose=purpose,
        detail_json=detail,
    )
    db.add(roll_row)
    await db.commit()
    return msg, roll_row

"""Typed WebSocket event envelopes.

Single source of truth for event names; frontend/src/types/events.ts mirrors this.
Envelope: {type, campaign_id, scene_id?, payload, ts}
"""

from datetime import UTC, datetime
from typing import Any

MESSAGE_CREATED = "message.created"
MESSAGE_STRUCK = "message.struck"
STREAM_START = "message.stream.start"
STREAM_DELTA = "message.stream.delta"
STREAM_END = "message.stream.end"
ROLL_CREATED = "roll.created"
TOOL_ACTIVITY = "tool.activity"
CHARACTER_UPDATED = "character.updated"
INVENTORY_UPDATED = "inventory.updated"
COMBAT_UPDATED = "combat.updated"
SCENE_CREATED = "scene.created"
SCENE_UPDATED = "scene.updated"
QUEST_UPDATED = "quest.updated"
WORLD_ENTITY_CHANGED = "world.entity_changed"
MEMBER_JOINED = "campaign.member_joined"
DM_PROPOSAL = "dm.proposal"
DM_WHISPER = "dm.whisper"
DOCUMENT_PROGRESS = "document.ingest_progress"
AI_STATUS = "ai.status"


def make_event(
    event_type: str,
    campaign_id: str,
    payload: dict[str, Any],
    scene_id: str | None = None,
) -> dict[str, Any]:
    return {
        "type": event_type,
        "campaign_id": campaign_id,
        "scene_id": scene_id,
        "payload": payload,
        "ts": datetime.now(UTC).isoformat(),
    }

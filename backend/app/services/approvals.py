"""Copilot/assist-mode approvals: held tool calls and draft turns."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Campaign, Message, PendingApproval, Scene
from app.realtime import events
from app.realtime.hub import hub


def _notify(campaign_id: str, approval: PendingApproval) -> None:
    hub.broadcast(
        campaign_id,
        events.make_event(
            events.DM_PROPOSAL,
            campaign_id,
            {
                "id": approval.id,
                "kind": approval.kind,
                "scene_id": approval.scene_id,
                "payload": approval.payload_json,
            },
            approval.scene_id,
        ),
        dm_only=True,
    )


async def hold_tool_call(
    db: AsyncSession,
    campaign: Campaign,
    scene: Scene,
    tool: str,
    arguments: dict[str, Any],
) -> PendingApproval:
    approval = PendingApproval(
        campaign_id=campaign.id,
        scene_id=scene.id,
        kind="tool_call",
        payload_json={"tool": tool, "arguments": arguments},
    )
    db.add(approval)
    await db.commit()
    _notify(campaign.id, approval)
    return approval


async def hold_draft_turn(
    db: AsyncSession,
    campaign: Campaign,
    scene: Scene,
    message: Message,
    leak: str | None = None,
) -> PendingApproval:
    approval = PendingApproval(
        campaign_id=campaign.id,
        scene_id=scene.id,
        kind="draft_turn",
        payload_json={
            "message_id": message.id,
            "content": message.content,
            "leak_warning": leak,
        },
    )
    db.add(approval)
    await db.commit()
    _notify(campaign.id, approval)
    return approval

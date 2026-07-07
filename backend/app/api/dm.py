"""DM controls: approvals, whispers, retcon, and turn nudges."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, require_campaign_dm, require_campaign_member
from app.api.errors import bad_request, not_found
from app.models import (
    NPC,
    AiTurn,
    Campaign,
    Character,
    Combatant,
    CombatEncounter,
    InventoryEntry,
    Item,
    Message,
    PendingApproval,
    Scene,
    ToolCallLog,
)
from app.realtime import events
from app.realtime.hub import hub
from app.services.messages import create_message, message_out

router = APIRouter(tags=["dm"])


class WhisperBody(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class RejectBody(BaseModel):
    note: str = ""


class EditApproveBody(BaseModel):
    content: str | None = None  # edited narration for draft turns
    arguments: dict[str, Any] | None = None  # edited args for tool calls


@router.get("/campaigns/{campaign_id}/approvals")
async def list_approvals(
    campaign_id: str, db: DbSession, user: CurrentUser
) -> list[dict[str, Any]]:
    await require_campaign_dm(campaign_id, db, user)
    rows = (
        await db.execute(
            select(PendingApproval)
            .where(
                PendingApproval.campaign_id == campaign_id,
                PendingApproval.status == "pending",
            )
            .order_by(PendingApproval.created_at)
        )
    ).scalars()
    return [
        {
            "id": a.id,
            "scene_id": a.scene_id,
            "kind": a.kind,
            "payload_json": a.payload_json,
            "status": a.status,
            "created_at": a.created_at.isoformat(),
        }
        for a in rows
    ]


@router.post("/approvals/{approval_id}/approve")
async def approve(
    approval_id: str, body: EditApproveBody, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    approval = await db.get(PendingApproval, approval_id)
    if not approval or approval.status != "pending":
        raise not_found("Pending approval")
    await require_campaign_dm(approval.campaign_id, db, user)
    scene = await db.get(Scene, approval.scene_id)
    campaign = await db.get(Campaign, approval.campaign_id)
    assert scene and campaign

    result: dict[str, Any] = {"ok": True}
    if approval.kind == "draft_turn":
        message = await db.get(Message, approval.payload_json.get("message_id"))
        if message:
            if body.content is not None:
                message.content = body.content
            message.visibility = "all"
            await db.commit()
            hub.broadcast(
                campaign.id,
                events.make_event(
                    events.MESSAGE_CREATED, campaign.id, message_out(message), scene.id
                ),
                scene_id=scene.id,
            )
            result["message"] = message_out(message)
    else:  # tool_call
        import app.ai.dm_agent  # noqa: F401  — ensure tools registered
        from app.ai.tools.registry import ToolContext, registry

        arguments = body.arguments or approval.payload_json.get("arguments", {})
        ctx = ToolContext(db=db, campaign=campaign, scene=scene, actor="dm")
        tool_result = await registry.dispatch(
            ctx, approval.payload_json.get("tool", ""), arguments
        )
        db.add(
            ToolCallLog(
                scene_id=scene.id,
                call_id=f"approval-{approval.id}",
                tool=approval.payload_json.get("tool", ""),
                args_json=arguments,
                result_json=tool_result.for_llm(),
                inverse_patch_json=list(ctx.inverse_patches),
                approved_by=user.id,
            )
        )
        if tool_result.public_note:
            await create_message(
                db, scene, author_type="tool", kind="tool_result",
                content=tool_result.public_note,
                payload={"tool": approval.payload_json.get("tool"), "ok": tool_result.ok},
            )
        result["tool_result"] = tool_result.for_llm()

    approval.status = "approved"
    approval.resolved_by = user.id
    await db.commit()
    return result


@router.post("/approvals/{approval_id}/reject")
async def reject(
    approval_id: str, body: RejectBody, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    approval = await db.get(PendingApproval, approval_id)
    if not approval or approval.status != "pending":
        raise not_found("Pending approval")
    await require_campaign_dm(approval.campaign_id, db, user)
    scene = await db.get(Scene, approval.scene_id)
    assert scene

    approval.status = "rejected"
    approval.resolved_by = user.id
    approval.note = body.note
    await db.commit()

    if approval.kind == "draft_turn":
        message = await db.get(Message, approval.payload_json.get("message_id"))
        if message:
            message.struck = True
            await db.commit()

    if body.note:
        # The note goes back to the AI as a private instruction; a fresh draft
        # is generated on the next turn.
        await create_message(
            db, scene, author_type="dm", author_user_id=user.id, kind="whisper",
            content=f"(rejected your last {approval.kind.replace('_', ' ')}): {body.note}",
            visibility="dm_ai", broadcast=False,
        )
        from app.ai.dm_agent import trigger_turn

        if scene.dm_mode in ("ai", "copilot", "assist"):
            trigger_turn(scene.id)
    return {"ok": True}


@router.post("/scenes/{scene_id}/whisper")
async def whisper(
    scene_id: str, body: WhisperBody, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    scene = await db.get(Scene, scene_id)
    if not scene:
        raise not_found("Scene")
    await require_campaign_dm(scene.campaign_id, db, user)
    message = await create_message(
        db, scene, author_type="dm", author_user_id=user.id, kind="whisper",
        content=body.content, visibility="dm_ai",
    )
    from app.ai.dm_agent import trigger_turn

    if scene.dm_mode in ("ai", "copilot", "assist"):
        trigger_turn(scene.id)
    return message_out(message)


@router.post("/scenes/{scene_id}/nudge")
async def nudge(scene_id: str, db: DbSession, user: CurrentUser) -> dict[str, bool]:
    """Ask the AI DM to take a turn now (any member; e.g. 'continue')."""
    scene = await db.get(Scene, scene_id)
    if not scene:
        raise not_found("Scene")
    await require_campaign_member(scene.campaign_id, db, user)
    if scene.dm_mode == "human":
        raise bad_request("This scene is run by the human DM")
    from app.ai.dm_agent import trigger_turn

    trigger_turn(scene.id)
    return {"ok": True}


async def _apply_inverse_patch(db, patch: dict[str, Any]) -> None:
    kind, row_id, values = patch.get("kind"), patch.get("id"), patch.get("patch", {})
    if kind == "campaign" and row_id:
        row = await db.get(Campaign, row_id)
        if row:
            for field_name, value in values.items():
                if hasattr(row, field_name):
                    setattr(row, field_name, value)
    elif kind == "character" and row_id:
        row = await db.get(Character, row_id)
        if row:
            for field_name, value in values.items():
                if hasattr(row, field_name):
                    setattr(row, field_name, value)
    elif kind == "npc" and row_id:
        row = await db.get(NPC, row_id)
        if row:
            if values.get("_created"):
                await db.delete(row)
            else:
                for field_name, value in values.items():
                    if hasattr(row, field_name):
                        setattr(row, field_name, value)
    elif kind == "encounter" and row_id:
        # Un-start a fight the retconned turn created: drop its combatants
        # then the encounter itself.
        row = await db.get(CombatEncounter, row_id)
        if row and values.get("_created"):
            # Core deletes execute immediately in order — child rows first.
            # (ORM delete ordering isn't guaranteed without relationships.)
            from sqlalchemy import delete as sa_delete

            await db.execute(sa_delete(Combatant).where(Combatant.encounter_id == row.id))
            await db.execute(sa_delete(CombatEncounter).where(CombatEncounter.id == row.id))
    elif kind == "combatant" and row_id:
        row = await db.get(Combatant, row_id)
        if row:
            for field_name, value in values.items():
                if hasattr(row, field_name):
                    setattr(row, field_name, value)
    elif kind == "inventory" and row_id:
        # restore prior quantity of an item for a character
        item_name, quantity = values.get("item"), values.get("quantity", 0)
        character = await db.get(Character, row_id)
        if character and item_name:
            item = (
                await db.execute(
                    select(Item).where(
                        Item.campaign_id == character.campaign_id,
                        func.lower(Item.name) == str(item_name).lower(),
                    )
                )
            ).scalars().first()
            if item:
                entry = (
                    await db.execute(
                        select(InventoryEntry).where(
                            InventoryEntry.owner_type == "character",
                            InventoryEntry.owner_id == character.id,
                            InventoryEntry.item_id == item.id,
                        )
                    )
                ).scalars().first()
                if quantity == 0:
                    if entry:
                        await db.delete(entry)
                elif entry:
                    entry.quantity = quantity
                else:
                    db.add(
                        InventoryEntry(
                            item_id=item.id,
                            owner_type="character",
                            owner_id=character.id,
                            quantity=quantity,
                        )
                    )


@router.post("/scenes/{scene_id}/retcon-last-turn")
async def retcon_last_turn(
    scene_id: str, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    """Strike the last AI turn's messages and reverse its state changes."""
    scene = await db.get(Scene, scene_id)
    if not scene:
        raise not_found("Scene")
    await require_campaign_dm(scene.campaign_id, db, user)

    turn = (
        await db.execute(
            select(AiTurn)
            .where(AiTurn.scene_id == scene_id, AiTurn.status == "done")
            .order_by(AiTurn.created_at.desc())
        )
    ).scalars().first()
    if not turn:
        raise bad_request("No completed AI turn to retcon")

    tool_calls = list(
        (
            await db.execute(
                select(ToolCallLog)
                .where(ToolCallLog.ai_turn_id == turn.id, ToolCallLog.reverted.is_(False))
                .order_by(ToolCallLog.created_at.desc())
            )
        ).scalars()
    )
    for log_row in tool_calls:
        for patch in reversed(log_row.inverse_patch_json or []):
            await _apply_inverse_patch(db, patch)
        log_row.reverted = True

    # Strike this turn's AI messages (created after the turn began)
    struck_ids = []
    messages = list(
        (
            await db.execute(
                select(Message).where(
                    Message.scene_id == scene_id,
                    Message.author_type.in_(["ai", "tool"]),
                    Message.created_at >= turn.created_at,
                    Message.struck.is_(False),
                )
            )
        ).scalars()
    )
    for message in messages:
        message.struck = True
        struck_ids.append(message.id)

    turn.status = "reverted"
    await db.commit()

    # Reverted patches may have changed (or deleted) combat — refresh clients.
    from app.services.combat import broadcast_combat

    await broadcast_combat(db, scene)

    for message_id in struck_ids:
        hub.broadcast(
            scene.campaign_id,
            events.make_event(
                events.MESSAGE_STRUCK, scene.campaign_id, {"message_id": message_id}, scene_id
            ),
            scene_id=scene_id,
        )
    return {"ok": True, "reverted_tool_calls": len(tool_calls), "struck_messages": len(struck_ids)}

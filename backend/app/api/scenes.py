import asyncio
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import (
    CurrentUser,
    DbSession,
    require_campaign_dm,
    require_campaign_member,
)
from app.api.errors import bad_request, forbidden, not_found
from app.models import Character, Message, Scene
from app.realtime import events
from app.realtime.hub import hub
from app.services import dice as dice_service
from app.services.messages import create_message, create_roll_message, message_out

router = APIRouter(tags=["scenes"])


class SceneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="main", pattern="^(main|side|solo)$")
    dm_mode: str = Field(default="ai", pattern="^(human|assist|copilot|ai)$")


class ScenePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: str | None = Field(default=None, pattern="^(active|idle|archived)$")
    dm_mode: str | None = Field(default=None, pattern="^(human|assist|copilot|ai)$")
    dm_notes: str | None = None
    time_note: str | None = None


class SceneOut(BaseModel):
    id: str
    campaign_id: str
    name: str
    kind: str
    status: str
    dm_mode: str
    location_id: str | None
    party_json: list[Any]
    summary: str
    time_note: str

    model_config = {"from_attributes": True}


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    kind: str = Field(default="chat", pattern="^(chat|ooc)$")
    character_id: str | None = None


class RollRequest(BaseModel):
    expression: str = Field(min_length=1, max_length=60)
    purpose: str = Field(default="raw", max_length=20)
    character_id: str | None = None


async def _get_scene_for_member(scene_id: str, db, user) -> Scene:
    scene = await db.get(Scene, scene_id)
    if not scene:
        raise not_found("Scene")
    await require_campaign_member(scene.campaign_id, db, user)
    return scene


@router.get("/campaigns/{campaign_id}/scenes", response_model=list[SceneOut])
async def list_scenes(campaign_id: str, db: DbSession, user: CurrentUser) -> list[Scene]:
    await require_campaign_member(campaign_id, db, user)
    result = await db.execute(
        select(Scene)
        .where(Scene.campaign_id == campaign_id)
        .order_by(Scene.created_at)
    )
    return list(result.scalars())


@router.post("/campaigns/{campaign_id}/scenes", response_model=SceneOut)
async def create_scene(
    campaign_id: str, body: SceneCreate, db: DbSession, user: CurrentUser
) -> Scene:
    member = await require_campaign_member(campaign_id, db, user)
    # Players may spin up their own solo side adventures; only the DM creates
    # main/side table scenes.
    if member.role != "dm" and body.kind != "solo":
        raise forbidden("Players can only create solo scenes")
    if member.role != "dm" and body.dm_mode != "ai":
        raise forbidden("Solo scenes are run by the AI DM")

    scene = Scene(
        campaign_id=campaign_id,
        name=body.name,
        kind=body.kind,
        dm_mode=body.dm_mode,
    )
    db.add(scene)
    await db.commit()

    hub.broadcast(
        campaign_id,
        events.make_event(
            events.SCENE_CREATED,
            campaign_id,
            SceneOut.model_validate(scene).model_dump(),
        ),
    )
    return scene


@router.patch("/scenes/{scene_id}", response_model=SceneOut)
async def update_scene(
    scene_id: str, body: ScenePatch, db: DbSession, user: CurrentUser
) -> Scene:
    scene = await db.get(Scene, scene_id)
    if not scene:
        raise not_found("Scene")
    await require_campaign_dm(scene.campaign_id, db, user)

    was_active = scene.status == "active"
    for field_name in ("name", "status", "dm_mode", "dm_notes", "time_note"):
        value = getattr(body, field_name)
        if value is not None:
            setattr(scene, field_name, value)
    await db.commit()

    # A DM ending a scene by hand still gets a recap (the AI path does this
    # through the scene_control tool).
    if was_active and scene.status in ("idle", "archived"):
        from app.ai import memory

        asyncio.get_running_loop().create_task(
            memory.rollup_scene_by_id(scene.id, force=True)
        )

    hub.broadcast(
        scene.campaign_id,
        events.make_event(
            events.SCENE_UPDATED,
            scene.campaign_id,
            SceneOut.model_validate(scene).model_dump(),
            scene.id,
        ),
    )
    return scene


@router.get("/scenes/{scene_id}/messages")
async def list_messages(
    scene_id: str,
    db: DbSession,
    user: CurrentUser,
    after_seq: int = 0,
    limit: int = 200,
) -> list[dict[str, Any]]:
    scene = await _get_scene_for_member(scene_id, db, user)
    member = await require_campaign_member(scene.campaign_id, db, user)

    query = (
        select(Message)
        .where(Message.scene_id == scene_id, Message.seq > after_seq)
        .order_by(Message.seq)
        .limit(min(limit, 500))
    )
    if member.role != "dm":
        query = query.where(Message.visibility == "all")
    result = await db.execute(query)
    return [message_out(m) for m in result.scalars()]


@router.post("/scenes/{scene_id}/messages")
async def post_message(
    scene_id: str, body: MessageCreate, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    scene = await _get_scene_for_member(scene_id, db, user)
    member = await require_campaign_member(scene.campaign_id, db, user)

    if body.character_id:
        character = await db.get(Character, body.character_id)
        if not character or character.campaign_id != scene.campaign_id:
            raise bad_request("Unknown character")
        if character.user_id != user.id and member.role != "dm":
            raise forbidden("That's not your character")

    author_type = "dm" if member.role == "dm" else "player"
    msg = await create_message(
        db,
        scene,
        author_type=author_type,
        author_user_id=user.id,
        character_id=body.character_id,
        kind=body.kind,
        content=body.content,
    )

    from app.ai.trigger import maybe_trigger_ai_turn

    await maybe_trigger_ai_turn(scene, msg)

    # Human-run scenes never take AI turns, so the rolling summarizer is kicked
    # from here once the unsummarized backlog is long enough (the AI/assist/
    # copilot paths already summarize after each AI turn).
    if scene.dm_mode == "human":
        from app.ai import memory

        if msg.seq - scene.summary_upto_seq >= memory.SUMMARIZE_EVERY:
            asyncio.get_running_loop().create_task(memory.rollup_scene_by_id(scene.id))
    return message_out(msg)


class RollResponse(BaseModel):
    message_id: str  # the roll_request message being answered


@router.post("/scenes/{scene_id}/respond-roll")
async def respond_roll(
    scene_id: str, body: RollResponse, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    """A player answers an AI 'request_player_roll' prompt: the server rolls
    with their real sheet modifiers and the AI continues."""
    scene = await _get_scene_for_member(scene_id, db, user)
    prompt_msg = await db.get(Message, body.message_id)
    if not prompt_msg or prompt_msg.scene_id != scene_id:
        raise not_found("Roll request")
    request = prompt_msg.payload_json.get("roll_request")
    if not request:
        raise bad_request("That message isn't a roll request")
    if prompt_msg.payload_json.get("answered"):
        raise bad_request("That roll was already made")

    character = await db.get(Character, request.get("character_id", ""))
    if not character:
        raise not_found("Character")
    member = await require_campaign_member(scene.campaign_id, db, user)
    if character.user_id != user.id and member.role != "dm":
        raise bad_request("That roll prompt is for another player")

    from app.ai.tools.core_tools import _sheet_modifier
    from app.services.dice import DiceResult, roll_d20

    kind = request.get("kind", "check")
    skill = request.get("ability_or_skill", "")
    dc = request.get("dc")
    face, faces = roll_d20()
    mod, mod_note = _sheet_modifier(character, kind, skill)
    total = face + mod
    detail: dict[str, Any] = {"kind": kind, "skill": skill, "modifier_note": mod_note}
    if dc is not None:
        detail["dc"] = dc
        detail["outcome"] = "success" if total >= dc else "failure"

    result = DiceResult(
        expression="1d20", rolls=faces, kept=[face], modifier=mod, total=total
    )
    msg, _roll = await create_roll_message(
        db, scene, expression="1d20", purpose=kind, roller_name=character.name,
        author_type="player", author_user_id=user.id, character_id=character.id,
        detail=detail, result=result,
    )
    prompt_msg.payload_json = {**prompt_msg.payload_json, "answered": True}
    await db.commit()

    from app.ai.trigger import maybe_trigger_ai_turn

    await maybe_trigger_ai_turn(scene, msg)
    return message_out(msg)


@router.post("/scenes/{scene_id}/roll")
async def roll_dice(
    scene_id: str, body: RollRequest, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    scene = await _get_scene_for_member(scene_id, db, user)
    member = await require_campaign_member(scene.campaign_id, db, user)

    roller_name = user.display_name
    if body.character_id:
        character = await db.get(Character, body.character_id)
        if character and character.campaign_id == scene.campaign_id:
            roller_name = character.name

    try:
        msg, _ = await create_roll_message(
            db,
            scene,
            expression=body.expression,
            purpose=body.purpose,
            roller_name=roller_name,
            author_type="dm" if member.role == "dm" else "player",
            author_user_id=user.id,
            character_id=body.character_id,
        )
    except dice_service.DiceError as e:
        raise bad_request(str(e)) from e
    return message_out(msg)

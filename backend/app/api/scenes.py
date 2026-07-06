import asyncio
from typing import Any

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import (
    CurrentUser,
    DbSession,
    require_campaign_dm,
    require_campaign_member,
)
from app.api.errors import bad_request, forbidden, not_found
from app.models import Campaign, Character, Location, Message, Scene
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
    # "" clears the scene's location; a real id sets it; None leaves it unchanged.
    location_id: str | None = None


class ScenePrepOut(BaseModel):
    """DM-only editable prep for a scene — dm_notes is secret, so it is not part
    of the members-visible SceneOut."""

    dm_notes: str
    time_note: str
    location_id: str | None


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


@router.get("/scenes/{scene_id}/prep", response_model=ScenePrepOut)
async def get_scene_prep(
    scene_id: str, db: DbSession, user: CurrentUser
) -> ScenePrepOut:
    """The DM's secret prep for a scene (notes/time/location) so it can be
    edited. DM-only — dm_notes must never reach players."""
    scene = await db.get(Scene, scene_id)
    if not scene:
        raise not_found("Scene")
    await require_campaign_dm(scene.campaign_id, db, user)
    return ScenePrepOut(
        dm_notes=scene.dm_notes, time_note=scene.time_note, location_id=scene.location_id
    )


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
    if body.location_id is not None:
        if body.location_id == "":
            scene.location_id = None
        else:
            loc = await db.get(Location, body.location_id)
            if not loc or loc.campaign_id != scene.campaign_id:
                raise bad_request("Unknown location for this campaign")
            scene.location_id = body.location_id
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
    tail: bool = False,
) -> list[dict[str, Any]]:
    """Messages for a scene, oldest→newest. `after_seq` fetches everything newer
    than a seq (used for reconnect resync). `tail=true` returns the most recent
    `limit` messages instead of the oldest — the right default for opening a
    long scene, so the view isn't stuck at the beginning."""
    scene = await _get_scene_for_member(scene_id, db, user)
    member = await require_campaign_member(scene.campaign_id, db, user)

    capped = min(limit, 500)
    base = select(Message).where(Message.scene_id == scene_id, Message.seq > after_seq)
    if member.role != "dm":
        base = base.where(Message.visibility == "all")

    if tail:
        # newest `capped` rows, then flip back to chronological order
        rows = list(
            (await db.execute(base.order_by(Message.seq.desc()).limit(capped))).scalars()
        )[::-1]
    else:
        rows = list((await db.execute(base.order_by(Message.seq).limit(capped))).scalars())
    return [message_out(m) for m in rows]


def _transcript_line(msg: Message, char_names: dict[str, str]) -> str | None:
    """One readable Markdown line per message for the exported log."""
    ts = msg.created_at.strftime("%H:%M")
    speaker = char_names.get(msg.character_id or "", None)

    if msg.kind == "roll":
        roll = (msg.payload_json or {}).get("roll", {})
        who = roll.get("roller_name") or speaker or "?"
        line = f"🎲 {who} rolled {roll.get('expression')} ({roll.get('purpose')}): {roll.get('total')}"
        if roll.get("dc") is not None:
            line += f" vs DC {roll['dc']} — {roll.get('outcome')}"
        return f"`{ts}` {line}"

    content = (msg.content or "").strip()
    if not content:
        return None

    # Tool-result chips and system beats are mechanics, not a speaker's line.
    if msg.kind in ("tool_result", "system") or msg.author_type in ("tool", "system"):
        return f"`{ts}` _{content}_"

    if msg.kind == "whisper":
        who = "**DM → AI (whisper)**"
    elif msg.author_type == "ai":
        who = "**DM**"
    elif speaker:
        # spoken in-character as a PC — show the character, whoever controls them
        who = f"**{speaker}**"
    elif msg.author_type == "dm":
        who = "**DM**"
    else:
        who = "**Player**"

    tag = ""
    if msg.kind == "ooc":
        tag = " (OOC)"
    if msg.visibility != "all":
        tag += " [DM-only]"
    if msg.struck:
        tag += " [retconned]"

    return f"`{ts}` {who}{tag}: {content}"


@router.get("/scenes/{scene_id}/transcript", response_class=PlainTextResponse)
async def scene_transcript(
    scene_id: str, db: DbSession, user: CurrentUser
) -> PlainTextResponse:
    """Download the full scene log as Markdown. DMs get everything (including
    whispers and DM-only messages); players get only what they can see. Not
    capped — the complete history, oldest to newest."""
    scene = await _get_scene_for_member(scene_id, db, user)
    member = await require_campaign_member(scene.campaign_id, db, user)
    campaign = await db.get(Campaign, scene.campaign_id)

    query = select(Message).where(Message.scene_id == scene_id).order_by(Message.seq)
    if member.role != "dm":
        query = query.where(Message.visibility == "all", Message.struck.is_(False))
    messages = list((await db.execute(query)).scalars())

    char_names = {
        c.id: c.name
        for c in (
            await db.execute(
                select(Character).where(Character.campaign_id == scene.campaign_id)
            )
        ).scalars()
    }

    header = [
        f"# {campaign.name if campaign else 'Campaign'} — {scene.name}",
        f"_Scene log · {len(messages)} messages_",
        "",
    ]
    lines = [ln for m in messages if (ln := _transcript_line(m, char_names))]
    body = "\n\n".join(lines) if lines else "_(no messages yet)_"
    filename = "".join(c if c.isalnum() else "-" for c in scene.name).strip("-") or "scene"
    return PlainTextResponse(
        "\n".join(header) + body + "\n",
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}-log.md"'},
    )


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

    await maybe_trigger_ai_turn(scene, msg, db)

    # Human-run scenes never take AI turns, so the rolling summarizer is kicked
    # from here once the unsummarized backlog is long enough (the AI/assist/
    # copilot paths already summarize after each AI turn).
    if scene.dm_mode == "human":
        from app.ai import memory

        if msg.seq - scene.summary_upto_seq >= memory.SUMMARIZE_EVERY:
            asyncio.get_running_loop().create_task(memory.rollup_scene_by_id(scene.id))
    return message_out(msg)


@router.post("/scenes/{scene_id}/skip-turn")
async def skip_turn(scene_id: str, db: DbSession, user: CurrentUser) -> dict[str, bool]:
    """A player declares they hold this round — counts as their declaration so
    the round can resolve without waiting on them."""
    scene = await _get_scene_for_member(scene_id, db, user)
    character = (
        await db.execute(
            select(Character).where(
                Character.campaign_id == scene.campaign_id,
                Character.user_id == user.id,
                Character.status == "active",
            )
        )
    ).scalars().first()
    if not character:
        raise bad_request("No active character to hold with")

    from app.ai.trigger import note_skip

    await create_message(
        db, scene, author_type="system", kind="system", content=f"{character.name} holds."
    )
    await note_skip(db, scene, character.id)
    return {"ok": True}


@router.post("/scenes/{scene_id}/resolve-turn")
async def resolve_turn(scene_id: str, db: DbSession, user: CurrentUser) -> dict[str, bool]:
    """DM forces the AI to resolve the round now, skipping anyone who hasn't
    declared (for an AFK player)."""
    scene = await db.get(Scene, scene_id)
    if not scene:
        raise not_found("Scene")
    await require_campaign_dm(scene.campaign_id, db, user)
    if scene.dm_mode == "human":
        raise bad_request("This scene is run by the human DM — there's no AI turn to resolve")

    from app.ai.trigger import resolve_now

    resolve_now(scene_id)
    return {"ok": True}


@router.delete("/scenes/{scene_id}")
async def delete_scene(scene_id: str, db: DbSession, user: CurrentUser) -> dict[str, bool]:
    """Permanently delete a scene and its chat log, rolls, combat history, and
    AI traces. Campaign-level memory (world events, the campaign summary)
    survives. DM only; no undo."""
    scene = await db.get(Scene, scene_id)
    if not scene:
        raise not_found("Scene")
    await require_campaign_dm(scene.campaign_id, db, user)
    from app.services.purge import purge_scene

    await purge_scene(db, scene)
    return {"ok": True}


@router.post("/scenes/{scene_id}/suggest-actions")
async def suggest_actions_endpoint(
    scene_id: str, db: DbSession, user: CurrentUser
) -> dict[str, list[str]]:
    """'What can I do?' — three short in-character options for stuck players.
    Always answers; falls back to generic suggestions if the model is down."""
    scene = await _get_scene_for_member(scene_id, db, user)

    from app.ai.suggestions import suggest_actions

    return {"suggestions": await suggest_actions(db, scene, user.id)}


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
        if not character or character.campaign_id != scene.campaign_id:
            raise bad_request("Unknown character")
        if character.user_id != user.id and member.role != "dm":
            raise forbidden("That's not your character")
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

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession, require_campaign_dm, require_campaign_member
from app.api.errors import bad_request, not_found
from app.models import Scene
from app.services import combat as combat_service

router = APIRouter(tags=["combat"])


class EncounterCreate(BaseModel):
    participants: list[str] = Field(min_length=1, description="names/ids/SRD monsters ('goblin x3')")


async def _dm_scene(scene_id: str, db, user) -> Scene:
    scene = await db.get(Scene, scene_id)
    if not scene:
        raise not_found("Scene")
    await require_campaign_dm(scene.campaign_id, db, user)
    return scene


@router.get("/scenes/{scene_id}/combat")
async def get_combat(scene_id: str, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    scene = await db.get(Scene, scene_id)
    if not scene:
        raise not_found("Scene")
    await require_campaign_member(scene.campaign_id, db, user)
    return await combat_service.combat_snapshot(db, scene_id)


@router.post("/scenes/{scene_id}/combat")
async def start_combat(
    scene_id: str, body: EncounterCreate, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    scene = await _dm_scene(scene_id, db, user)
    try:
        return await combat_service.start_encounter(db, scene, body.participants)
    except combat_service.CombatError as e:
        raise bad_request(str(e)) from e


@router.post("/scenes/{scene_id}/combat/next-turn")
async def next_turn(scene_id: str, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    scene = await _dm_scene(scene_id, db, user)
    try:
        return await combat_service.advance_turn(db, scene)
    except combat_service.CombatError as e:
        raise bad_request(str(e)) from e


class CombatantHp(BaseModel):
    delta: int = Field(ge=-999, le=999, description="negative = damage, positive = heal")


@router.patch("/combatants/{combatant_id}")
async def nudge_combatant_hp(
    combatant_id: str, body: CombatantHp, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    """DM applies quick damage/healing straight from the initiative tracker.
    Character rows route to the character sheet so HP stays consistent."""
    from app.models import Character, Combatant, CombatEncounter

    combatant = await db.get(Combatant, combatant_id)
    if not combatant:
        raise not_found("Combatant")
    encounter = await db.get(CombatEncounter, combatant.encounter_id)
    scene = await db.get(Scene, encounter.scene_id)
    await require_campaign_dm(scene.campaign_id, db, user)

    if combatant.ref_type == "character" and combatant.ref_id:
        character = await db.get(Character, combatant.ref_id)
        if character:
            character.hp_current = max(
                0, min(character.hp_current + body.delta, character.hp_max)
            )
            from app.services.bookkeeping import broadcast_character

            broadcast_character(scene.campaign_id, character)
    else:
        current = combatant.hp_current or 0
        new_hp = current + body.delta
        if combatant.hp_max is not None:
            new_hp = min(new_hp, combatant.hp_max)
        combatant.hp_current = max(0, new_hp)
        if combatant.hp_current == 0 and body.delta < 0:
            combatant.defeated = True
        elif combatant.hp_current > 0:
            combatant.defeated = False
        # Mirror onto the persistent NPC row when this combatant wraps one.
        if combatant.ref_type == "npc" and combatant.ref_id:
            from app.models import NPC

            npc = await db.get(NPC, combatant.ref_id)
            if npc:
                npc.hp_current = combatant.hp_current
                if combatant.defeated:
                    npc.status = "dead"
                elif npc.status == "dead":
                    npc.status = "active"
    await db.commit()
    return await combat_service.broadcast_combat(db, scene)


@router.post("/scenes/{scene_id}/combat/end")
async def end_combat(scene_id: str, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    scene = await _dm_scene(scene_id, db, user)
    try:
        # The human DM's call is final — no standing-foes guard here.
        return await combat_service.end_encounter(db, scene, force=True)
    except combat_service.CombatError as e:
        raise bad_request(str(e)) from e

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


@router.post("/scenes/{scene_id}/combat/end")
async def end_combat(scene_id: str, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    scene = await _dm_scene(scene_id, db, user)
    try:
        # The human DM's call is final — no standing-foes guard here.
        return await combat_service.end_encounter(db, scene, force=True)
    except combat_service.CombatError as e:
        raise bad_request(str(e)) from e

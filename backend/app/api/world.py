from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_campaign_dm, require_campaign_member
from app.api.errors import not_found
from app.models import NPC, Faction, Location, Monster, Quest, WorldEvent
from app.realtime import events
from app.realtime.hub import hub

router = APIRouter(tags=["world"])


def npc_out(n: NPC, dm: bool) -> dict[str, Any]:
    out = {
        "id": n.id,
        "name": n.name,
        "role": n.role,
        "disposition": n.disposition,
        "description": n.description,
        "location_id": n.location_id,
        "faction_id": n.faction_id,
        "status": n.status,
        "created_by": n.created_by,
        "stat_block_json": n.stat_block_json if dm else None,
    }
    if dm:
        out["secrets"] = n.secrets
        out["hp_current"] = n.hp_current
    return out


def location_out(loc: Location, dm: bool) -> dict[str, Any]:
    out = {
        "id": loc.id,
        "parent_id": loc.parent_id,
        "kind": loc.kind,
        "name": loc.name,
        "description": loc.description,
        "tags_json": loc.tags_json,
        "created_by": loc.created_by,
    }
    if dm:
        out["dm_notes"] = loc.dm_notes
    return out


def faction_out(f: Faction, dm: bool) -> dict[str, Any]:
    out = {
        "id": f.id,
        "name": f.name,
        "description": f.description,
        "goals": f.goals,
        "relationships_json": f.relationships_json,
    }
    if dm:
        out["dm_notes"] = f.dm_notes
    return out


def quest_out(q: Quest, dm: bool) -> dict[str, Any]:
    out = {
        "id": q.id,
        "title": q.title,
        "status": q.status,
        "summary": q.summary,
        "objectives_json": q.objectives_json,
        "rewards_json": q.rewards_json,
    }
    if dm:
        out["dm_notes"] = q.dm_notes
    return out


def monster_out(m: Monster) -> dict[str, Any]:
    return {
        "id": m.id,
        "name": m.name,
        "cr": m.cr,
        "description": m.description,
        "source": m.source,
        "stat_block_json": m.stat_block_json,
    }


def broadcast_world_change(campaign_id: str, entity_kind: str, entity_id: str) -> None:
    hub.broadcast(
        campaign_id,
        events.make_event(
            events.WORLD_ENTITY_CHANGED,
            campaign_id,
            {"kind": entity_kind, "id": entity_id},
        ),
    )


@router.get("/campaigns/{campaign_id}/world")
async def get_world(campaign_id: str, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    member = await require_campaign_member(campaign_id, db, user)
    dm = member.role == "dm"

    locations = (
        (await db.execute(select(Location).where(Location.campaign_id == campaign_id).order_by(Location.name)))
        .scalars().all()
    )
    npcs = (
        (await db.execute(select(NPC).where(NPC.campaign_id == campaign_id).order_by(NPC.name)))
        .scalars().all()
    )
    factions = (
        (await db.execute(select(Faction).where(Faction.campaign_id == campaign_id).order_by(Faction.name)))
        .scalars().all()
    )
    quests = (
        (await db.execute(select(Quest).where(Quest.campaign_id == campaign_id).order_by(Quest.created_at)))
        .scalars().all()
    )
    monsters = (
        (await db.execute(select(Monster).where(Monster.campaign_id == campaign_id).order_by(Monster.name)))
        .scalars().all()
    )
    # NPC drafts (AI-inferred stubs) are DM-only until accepted
    visible_npcs = [n for n in npcs if dm or n.status != "draft"]
    return {
        "locations": [location_out(loc, dm) for loc in locations],
        "npcs": [npc_out(n, dm) for n in visible_npcs],
        "factions": [faction_out(f, dm) for f in factions],
        "quests": [quest_out(q, dm) for q in quests],
        "monsters": [monster_out(m) for m in monsters] if dm else [],
    }


@router.get("/campaigns/{campaign_id}/world-events")
async def list_world_events(
    campaign_id: str, db: DbSession, user: CurrentUser, limit: int = 50
) -> list[dict[str, Any]]:
    await require_campaign_dm(campaign_id, db, user)
    rows = (
        await db.execute(
            select(WorldEvent)
            .where(WorldEvent.campaign_id == campaign_id)
            .order_by(WorldEvent.created_at.desc())
            .limit(min(limit, 200))
        )
    ).scalars()
    return [
        {"id": e.id, "description": e.description, "scene_id": e.scene_id, "created_at": e.created_at.isoformat()}
        for e in rows
    ]


# --- Generic upsert/patch endpoints (DM only) ---------------------------------

_MODELS = {"npc": NPC, "location": Location, "faction": Faction, "quest": Quest, "monster": Monster}
_OUT = {
    "npc": lambda row, dm: npc_out(row, dm),
    "location": lambda row, dm: location_out(row, dm),
    "faction": lambda row, dm: faction_out(row, dm),
    "quest": lambda row, dm: quest_out(row, dm),
    "monster": lambda row, dm: monster_out(row),
}
_FIELDS = {
    "npc": {"name", "role", "disposition", "description", "secrets", "location_id",
            "faction_id", "status", "stat_block_json", "hp_current"},
    "location": {"name", "kind", "parent_id", "description", "dm_notes", "tags_json"},
    "faction": {"name", "description", "goals", "dm_notes", "relationships_json"},
    "quest": {"title", "status", "summary", "dm_notes", "objectives_json", "rewards_json"},
    "monster": {"name", "cr", "description", "stat_block_json"},
}


class EntityBody(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)


@router.post("/campaigns/{campaign_id}/world/{kind}")
async def create_entity(
    campaign_id: str, kind: str, body: EntityBody, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    await require_campaign_dm(campaign_id, db, user)
    model = _MODELS.get(kind)
    if not model:
        raise not_found(f"Entity kind '{kind}'")
    allowed = {k: v for k, v in body.fields.items() if k in _FIELDS[kind]}
    if not allowed.get("name") and not allowed.get("title"):
        from app.api.errors import bad_request

        raise bad_request("A name is required")
    row = model(campaign_id=campaign_id, **allowed)
    db.add(row)
    await db.commit()
    broadcast_world_change(campaign_id, kind, row.id)
    return _OUT[kind](row, True)


@router.patch("/world/{kind}/{entity_id}")
async def patch_entity(
    kind: str, entity_id: str, body: EntityBody, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    model = _MODELS.get(kind)
    if not model:
        raise not_found(f"Entity kind '{kind}'")
    row = await db.get(model, entity_id)
    if not row:
        raise not_found(kind)
    await require_campaign_dm(row.campaign_id, db, user)
    for key, value in body.fields.items():
        if key in _FIELDS[kind]:
            setattr(row, key, value)
    await db.commit()
    broadcast_world_change(row.campaign_id, kind, row.id)
    return _OUT[kind](row, True)


@router.delete("/world/{kind}/{entity_id}")
async def delete_entity(
    kind: str, entity_id: str, db: DbSession, user: CurrentUser
) -> dict[str, bool]:
    model = _MODELS.get(kind)
    if not model:
        raise not_found(f"Entity kind '{kind}'")
    row = await db.get(model, entity_id)
    if not row:
        raise not_found(kind)
    await require_campaign_dm(row.campaign_id, db, user)
    campaign_id = row.campaign_id
    await db.delete(row)
    await db.commit()
    broadcast_world_change(campaign_id, kind, entity_id)
    return {"ok": True}

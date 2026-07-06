"""Hard deletion of campaigns, scenes, and characters.

SQLite enforces the schema's foreign keys and nothing declares ON DELETE
CASCADE, so deletes must remove children before parents — these helpers own
that ordering. The FTS indexes (messages/chunks/world-events) keep themselves
in sync via AFTER DELETE triggers.
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    NPC,
    AiTurn,
    Campaign,
    CampaignMember,
    Character,
    Chunk,
    Combatant,
    CombatEncounter,
    DiceRoll,
    Document,
    Faction,
    InventoryEntry,
    Item,
    Location,
    Message,
    Monster,
    PendingApproval,
    Quest,
    Scene,
    Summary,
    ToolCallLog,
    WorldEvent,
)


async def _purge_scene_children(db: AsyncSession, scene_ids: list[str]) -> None:
    if not scene_ids:
        return
    encounter_ids = list(
        (
            await db.execute(
                select(CombatEncounter.id).where(CombatEncounter.scene_id.in_(scene_ids))
            )
        ).scalars()
    )
    if encounter_ids:
        await db.execute(delete(Combatant).where(Combatant.encounter_id.in_(encounter_ids)))
        await db.execute(delete(CombatEncounter).where(CombatEncounter.id.in_(encounter_ids)))
    await db.execute(delete(DiceRoll).where(DiceRoll.scene_id.in_(scene_ids)))
    await db.execute(delete(ToolCallLog).where(ToolCallLog.scene_id.in_(scene_ids)))
    await db.execute(delete(AiTurn).where(AiTurn.scene_id.in_(scene_ids)))
    await db.execute(delete(PendingApproval).where(PendingApproval.scene_id.in_(scene_ids)))
    await db.execute(delete(Message).where(Message.scene_id.in_(scene_ids)))


async def purge_scene(db: AsyncSession, scene: Scene) -> None:
    """Delete a scene and everything that happened in it. The campaign's
    world (NPCs, quests, world events, recaps rolled up into the campaign
    summary) survives — only the scene's own record is removed."""
    await _purge_scene_children(db, [scene.id])
    await db.execute(
        delete(Summary).where(Summary.scope == "scene", Summary.ref_id == scene.id)
    )
    await db.delete(scene)
    await db.commit()


async def purge_character(db: AsyncSession, character: Character) -> None:
    """Delete a character: their pack empties, initiative entries and scene
    rosters forget them, and old messages keep their text but drop the link."""
    await db.execute(
        delete(InventoryEntry).where(
            InventoryEntry.owner_type == "character",
            InventoryEntry.owner_id == character.id,
        )
    )
    # Old log lines keep their content; they just stop pointing at the row.
    for model in (Message, DiceRoll):
        rows = (
            await db.execute(select(model).where(model.character_id == character.id))
        ).scalars()
        for row in rows:
            row.character_id = None
    await db.execute(
        delete(Combatant).where(
            Combatant.ref_type == "character", Combatant.ref_id == character.id
        )
    )
    scenes = (
        await db.execute(select(Scene).where(Scene.campaign_id == character.campaign_id))
    ).scalars()
    for scene in scenes:
        if character.id in (scene.party_json or []):
            scene.party_json = [c for c in scene.party_json if c != character.id]
    await db.delete(character)
    await db.commit()


async def purge_campaign(db: AsyncSession, campaign: Campaign) -> None:
    """Delete a campaign and every row that belongs to it."""
    cid = campaign.id
    scene_ids = list(
        (await db.execute(select(Scene.id).where(Scene.campaign_id == cid))).scalars()
    )
    await _purge_scene_children(db, scene_ids)

    character_ids = list(
        (await db.execute(select(Character.id).where(Character.campaign_id == cid))).scalars()
    )
    item_ids = list(
        (await db.execute(select(Item.id).where(Item.campaign_id == cid))).scalars()
    )
    if character_ids:
        await db.execute(
            delete(InventoryEntry).where(
                InventoryEntry.owner_type == "character",
                InventoryEntry.owner_id.in_(character_ids),
            )
        )
    if item_ids:
        # Entries owned by NPCs/locations that reference campaign items.
        await db.execute(delete(InventoryEntry).where(InventoryEntry.item_id.in_(item_ids)))

    document_ids = list(
        (await db.execute(select(Document.id).where(Document.campaign_id == cid))).scalars()
    )
    if document_ids:
        await db.execute(delete(Chunk).where(Chunk.document_id.in_(document_ids)))
        await db.execute(delete(Document).where(Document.id.in_(document_ids)))

    for model in (
        PendingApproval,
        Summary,
        WorldEvent,
        Quest,
        NPC,  # before Location/Faction (FKs point at both)
        Monster,
        Character,
        Item,
        CampaignMember,
    ):
        await db.execute(delete(model).where(model.campaign_id == cid))

    # Scenes reference locations; locations self-reference (parent_id) but a
    # single whole-set DELETE satisfies SQLite's per-statement FK check.
    await db.execute(delete(Scene).where(Scene.campaign_id == cid))
    await db.execute(delete(Location).where(Location.campaign_id == cid))
    await db.execute(delete(Faction).where(Faction.campaign_id == cid))

    await db.delete(campaign)
    await db.commit()

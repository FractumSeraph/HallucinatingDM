from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_campaign_member
from app.api.errors import bad_request, forbidden, not_found
from app.models import Character, InventoryEntry, Item
from app.realtime import events
from app.realtime.hub import hub
from app.services.character_builder import (
    BuildError,
    CharacterBuild,
    build_character,
    character_out,
)

router = APIRouter(tags=["characters"])


class CharacterPatch(BaseModel):
    """Sheet edits by the owner or DM. Derived values recompute elsewhere; this
    is for narrative fields and DM corrections."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    alignment: str | None = None
    notes: str | None = None
    status: str | None = Field(default=None, pattern="^(draft|active|retired|dead)$")
    hp_current: int | None = None
    hp_temp: int | None = None
    ac: int | None = None
    conditions: list[str] | None = None
    currency: dict[str, int] | None = None
    sheet: dict[str, Any] | None = None


class InventoryAdd(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    quantity: int = Field(default=1, ge=1, le=10_000)
    description: str = ""
    item_type: str = ""


class InventoryPatch(BaseModel):
    quantity: int | None = Field(default=None, ge=0, le=10_000)
    equipped: bool | None = None


async def _get_character(character_id: str, db, user) -> tuple[Character, str]:
    character = await db.get(Character, character_id)
    if not character:
        raise not_found("Character")
    member = await require_campaign_member(character.campaign_id, db, user)
    return character, member.role


def _require_owner_or_dm(character: Character, user_id: str, role: str) -> None:
    if character.user_id != user_id and role != "dm":
        raise forbidden("Only the character's player or the DM can do that")


def broadcast_character(character: Character) -> None:
    hub.broadcast(
        character.campaign_id,
        events.make_event(
            events.CHARACTER_UPDATED, character.campaign_id, character_out(character)
        ),
    )


@router.get("/campaigns/{campaign_id}/characters")
async def list_characters(
    campaign_id: str, db: DbSession, user: CurrentUser
) -> list[dict[str, Any]]:
    await require_campaign_member(campaign_id, db, user)
    result = await db.execute(
        select(Character)
        .where(Character.campaign_id == campaign_id)
        .order_by(Character.created_at)
    )
    return [character_out(c) for c in result.scalars()]


@router.post("/campaigns/{campaign_id}/characters")
async def create_character(
    campaign_id: str, build: CharacterBuild, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    await require_campaign_member(campaign_id, db, user)
    try:
        character = await build_character(db, campaign_id, user.id, build)
    except BuildError as e:
        raise bad_request(str(e)) from e
    db.add(character)
    await db.commit()
    broadcast_character(character)
    return character_out(character)


@router.get("/characters/{character_id}")
async def get_character(
    character_id: str, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    character, _role = await _get_character(character_id, db, user)
    return character_out(character)


@router.patch("/characters/{character_id}")
async def patch_character(
    character_id: str, body: CharacterPatch, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    character, role = await _get_character(character_id, db, user)
    _require_owner_or_dm(character, user.id, role)

    if body.name is not None:
        character.name = body.name
    if body.alignment is not None:
        character.alignment = body.alignment
    if body.notes is not None:
        character.notes = body.notes
    if body.status is not None:
        character.status = body.status
    if body.hp_current is not None:
        character.hp_current = max(0, min(body.hp_current, character.hp_max))
    if body.hp_temp is not None:
        character.hp_temp = max(0, body.hp_temp)
    if body.ac is not None:
        character.ac = max(1, min(body.ac, 30))
    if body.conditions is not None:
        character.conditions_json = body.conditions
    if body.currency is not None:
        character.currency_json = {k: max(0, v) for k, v in body.currency.items()}
    if body.sheet is not None:
        character.sheet_json = {**character.sheet_json, **body.sheet}

    await db.commit()
    broadcast_character(character)
    return character_out(character)


# --- Inventory --------------------------------------------------------------


def _inventory_out(entry: InventoryEntry, item: Item) -> dict[str, Any]:
    return {
        "entry_id": entry.id,
        "item_id": item.id,
        "name": item.name,
        "item_type": item.item_type,
        "rarity": item.rarity,
        "description": item.description,
        "quantity": entry.quantity,
        "equipped": entry.equipped,
    }


async def get_or_create_item(
    db, campaign_id: str, name: str, description: str = "", item_type: str = "", source: str = "custom"
) -> Item:
    result = await db.execute(
        select(Item).where(
            Item.campaign_id == campaign_id, Item.name.ilike(name.strip())
        )
    )
    item = result.scalars().first()
    if item:
        return item
    item = Item(
        campaign_id=campaign_id,
        name=name.strip(),
        description=description,
        item_type=item_type,
        source=source,
    )
    db.add(item)
    await db.flush()
    return item


@router.get("/characters/{character_id}/inventory")
async def list_inventory(
    character_id: str, db: DbSession, user: CurrentUser
) -> list[dict[str, Any]]:
    character, _ = await _get_character(character_id, db, user)
    result = await db.execute(
        select(InventoryEntry, Item)
        .join(Item, Item.id == InventoryEntry.item_id)
        .where(
            InventoryEntry.owner_type == "character",
            InventoryEntry.owner_id == character.id,
        )
        .order_by(InventoryEntry.created_at)
    )
    return [_inventory_out(e, i) for e, i in result.all()]


@router.post("/characters/{character_id}/inventory")
async def add_inventory(
    character_id: str, body: InventoryAdd, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    character, role = await _get_character(character_id, db, user)
    _require_owner_or_dm(character, user.id, role)

    item = await get_or_create_item(
        db, character.campaign_id, body.name, body.description, body.item_type
    )
    result = await db.execute(
        select(InventoryEntry).where(
            InventoryEntry.owner_type == "character",
            InventoryEntry.owner_id == character.id,
            InventoryEntry.item_id == item.id,
        )
    )
    entry = result.scalars().first()
    if entry:
        entry.quantity += body.quantity
    else:
        entry = InventoryEntry(
            item_id=item.id,
            owner_type="character",
            owner_id=character.id,
            quantity=body.quantity,
        )
        db.add(entry)
    await db.commit()

    hub.broadcast(
        character.campaign_id,
        events.make_event(
            events.INVENTORY_UPDATED,
            character.campaign_id,
            {"character_id": character.id},
        ),
    )
    return _inventory_out(entry, item)


@router.patch("/inventory/{entry_id}")
async def patch_inventory(
    entry_id: str, body: InventoryPatch, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    entry = await db.get(InventoryEntry, entry_id)
    if not entry or entry.owner_type != "character":
        raise not_found("Inventory entry")
    character, role = await _get_character(entry.owner_id, db, user)
    _require_owner_or_dm(character, user.id, role)

    if body.quantity is not None:
        entry.quantity = body.quantity
    if body.equipped is not None:
        entry.equipped = body.equipped

    item = await db.get(Item, entry.item_id)
    deleted = entry.quantity == 0
    if deleted:
        await db.delete(entry)
    await db.commit()

    hub.broadcast(
        character.campaign_id,
        events.make_event(
            events.INVENTORY_UPDATED,
            character.campaign_id,
            {"character_id": character.id},
        ),
    )
    assert item
    if deleted:
        return {"deleted": True, "entry_id": entry_id}
    return _inventory_out(entry, item)

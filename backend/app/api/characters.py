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

    # Give the character its class starting kit as real inventory.
    from app.services.starting_kit import grant_starting_kit

    await grant_starting_kit(db, campaign_id, character)
    await db.commit()

    broadcast_character(character)
    return character_out(character)


@router.get("/campaigns/{campaign_id}/class-spells/{klass}")
async def class_spells(
    campaign_id: str, klass: str, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    """Spell options + level-1 known counts for a class, to drive the wizard's
    spell-selection step."""
    await require_campaign_member(campaign_id, db, user)
    from app.services.character_builder import class_spell_options
    from app.services.starting_kit import CASTER_SLOTS_L1, kit_for

    slug = klass.lower().replace(" ", "-")
    counts = CASTER_SLOTS_L1.get(slug)
    options = (
        await class_spell_options(db, klass)
        if counts
        else {"cantrips": [], "level1": [], "descriptions": {}}
    )
    return {
        "is_caster": counts is not None,
        "cantrips_known": counts[0] if counts else 0,
        "spells_known": counts[1] if counts else 0,
        "cantrips": options["cantrips"],
        "level1": options["level1"],
        # Short blurbs so pickers aren't bare names ("Fire Bolt: hurl a mote…").
        "spell_descriptions": options["descriptions"],
        # So the wizard can show the player the gear they'll start with.
        "starting_kit": kit_for(klass),
    }


@router.post("/campaigns/{campaign_id}/roll-abilities")
async def roll_abilities(
    campaign_id: str, db: DbSession, user: CurrentUser
) -> dict[str, dict[str, int]]:
    """Server-roll 4d6-drop-lowest for each ability, so the wizard can show the
    result before the player commits to a class (and the roll is auditable)."""
    await require_campaign_member(campaign_id, db, user)
    from app.services.character_builder import _roll_scores

    return {"scores": _roll_scores()}


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


class SlotRequest(BaseModel):
    level: str = Field(min_length=1, max_length=2)
    op: str = Field(default="spend", pattern="^(spend|restore)$")


@router.post("/characters/{character_id}/spell-slot")
async def spend_spell_slot(
    character_id: str, body: SlotRequest, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    """Track a cast by hand (human-DM tables): spend or restore one slot of a
    level. Owner or DM."""
    character, role = await _get_character(character_id, db, user)
    _require_owner_or_dm(character, user.id, role)

    slots = {k: dict(v) for k, v in character.spell_slots_json.items()}
    slot = slots.get(body.level)
    if not slot:
        raise bad_request(f"No level-{body.level} slots on this sheet")
    if body.op == "spend":
        if slot["used"] >= slot["max"]:
            raise bad_request(f"No level-{body.level} slots remaining")
        slot["used"] += 1
    else:
        slot["used"] = max(0, slot["used"] - 1)
    slots[body.level] = slot
    character.spell_slots_json = slots
    await db.commit()
    broadcast_character(character)
    return character_out(character)


@router.delete("/characters/{character_id}")
async def delete_character(
    character_id: str, db: DbSession, user: CurrentUser
) -> dict[str, bool]:
    """Permanently delete a character (owner or DM). Their inventory and
    initiative entries go too; old chat lines keep their text but drop the
    link. Prefer retiring (status="retired") to keep the sheet around."""
    character, role = await _get_character(character_id, db, user)
    _require_owner_or_dm(character, user.id, role)
    from app.services.purge import purge_character

    await purge_character(db, character)
    return {"ok": True}


class ChargenSuggestBody(BaseModel):
    concept: str = Field(min_length=3, max_length=500)


@router.post("/campaigns/{campaign_id}/chargen-suggest")
async def chargen_suggest(
    campaign_id: str, body: ChargenSuggestBody, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    """AI-assisted wizard: turn a concept into a validated build payload."""
    await require_campaign_member(campaign_id, db, user)
    from app.ai.chargen import suggest_build

    build, error = await suggest_build(db, campaign_id, user.id, body.concept)
    if build is None:
        raise bad_request(f"The AI couldn't produce a legal build: {error}")
    return build


class LevelUpRequest(BaseModel):
    """Choices for the pending level: new spells and (at ASI levels) ability
    bumps. All optional — an empty body levels up with no choices spent."""

    cantrips: list[str] = []
    spells: list[str] = []
    asi: dict[str, int] = {}


@router.get("/characters/{character_id}/level-up-options")
async def level_up_options_endpoint(
    character_id: str, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    """What the pending level-up grants: HP, slots, features, ASI, spell picks."""
    from app.services import rules_5e
    from app.services.leveling import level_up_options

    character, role = await _get_character(character_id, db, user)
    _require_owner_or_dm(character, user.id, role)
    if rules_5e.level_for_xp(character.xp) <= character.level:
        needed = rules_5e.xp_for_next_level(character.level)
        raise bad_request(
            f"Not enough XP (need {needed}, have {character.xp})" if needed else "Already level 20"
        )
    return await level_up_options(db, character)


@router.post("/characters/{character_id}/level-up")
async def level_up(
    character_id: str,
    db: DbSession,
    user: CurrentUser,
    body: LevelUpRequest | None = None,
) -> dict[str, Any]:
    from app.services import leveling, rules_5e

    character, role = await _get_character(character_id, db, user)
    _require_owner_or_dm(character, user.id, role)
    picks = body or LevelUpRequest()

    earned = rules_5e.level_for_xp(character.xp)
    if earned <= character.level:
        needed = rules_5e.xp_for_next_level(character.level)
        raise bad_request(
            f"Not enough XP (need {needed}, have {character.xp})" if needed else "Already level 20"
        )

    options = await leveling.level_up_options(db, character)

    # --- Validate choices against what this level actually offers ------------
    try:
        if picks.asi and not options["asi"]:
            raise leveling.LevelUpError(f"Level {options['new_level']} grants no ASI")
        leveling.validate_asi(picks.asi, character.ability_scores_json)
        if len(picks.cantrips) > options["cantrip_picks"]:
            raise leveling.LevelUpError(
                f"Only {options['cantrip_picks']} new cantrip(s) at this level"
            )
        if len(picks.spells) > options["spell_picks"]:
            raise leveling.LevelUpError(
                f"Only {options['spell_picks']} new spell(s) at this level"
            )
        valid_cantrips = {n.lower() for n in options["available"].get("0", [])}
        valid_spells = {
            n.lower()
            for lvl, names in options["available"].items()
            if lvl != "0"
            for n in names
        }
        for name in picks.cantrips:
            if name.lower() not in valid_cantrips:
                raise leveling.LevelUpError(f"'{name}' is not an available cantrip")
        for name in picks.spells:
            if name.lower() not in valid_spells:
                raise leveling.LevelUpError(f"'{name}' is not an available spell")
    except leveling.LevelUpError as e:
        raise bad_request(str(e)) from e

    # --- Apply ----------------------------------------------------------------
    old_con_mod = rules_5e.ability_modifier(character.ability_scores_json.get("con", 10))
    if picks.asi:
        scores = dict(character.ability_scores_json)
        for ability, bump in picks.asi.items():
            scores[ability] = scores.get(ability, 10) + bump
        character.ability_scores_json = scores
    new_con_mod = rules_5e.ability_modifier(character.ability_scores_json.get("con", 10))

    # Retroactive CON: a higher modifier applies to every level already taken.
    retro = (new_con_mod - old_con_mod) * character.level
    character.level += 1
    hit_die = int(character.sheet_json.get("hit_die", 8))
    gained = max(1, hit_die // 2 + 1 + new_con_mod) + retro
    character.hp_max += gained
    character.hp_current += gained

    # refresh slot maxima for the new level, keeping used counts
    class_slug = character.klass.lower().replace(" ", "-")
    new_slots = rules_5e.spell_slots_for(class_slug, character.level)
    for lvl, slot in new_slots.items():
        old = character.spell_slots_json.get(lvl, {})
        slot["used"] = min(old.get("used", 0), slot["max"])
    character.spell_slots_json = new_slots

    resources = {k: dict(v) for k, v in character.resources_json.items()}
    hd = resources.get("hit_dice", {"max": 0, "used": 0, "die": hit_die})
    hd["max"] = character.level
    resources["hit_dice"] = hd
    character.resources_json = resources

    # New class features + learned spells live on the sheet.
    sheet = dict(character.sheet_json)
    if options["features"]:
        sheet["features"] = list(sheet.get("features") or []) + options["features"]
    if picks.cantrips or picks.spells:
        spells = {
            "cantrips": list((sheet.get("spells") or {}).get("cantrips") or []),
            "known": list((sheet.get("spells") or {}).get("known") or []),
        }
        spells["cantrips"] += picks.cantrips
        spells["known"] += picks.spells
        sheet["spells"] = spells
    character.sheet_json = sheet

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


from app.services.items import get_or_create_item  # noqa: E402  (shared with AI tools)


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


class GiveRequest(BaseModel):
    to_character_id: str
    quantity: int = Field(default=1, ge=1, le=10_000)


@router.post("/inventory/{entry_id}/give")
async def give_item(
    entry_id: str, body: GiveRequest, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    """Hand items to a party member: moves quantity from one character's pack
    to another's. Owner (or DM) of the giving character only."""
    entry = await db.get(InventoryEntry, entry_id)
    if not entry or entry.owner_type != "character":
        raise not_found("Inventory entry")
    giver, role = await _get_character(entry.owner_id, db, user)
    _require_owner_or_dm(giver, user.id, role)

    receiver = await db.get(Character, body.to_character_id)
    if (
        not receiver
        or receiver.campaign_id != giver.campaign_id
        or receiver.status != "active"
    ):
        raise bad_request("Unknown or inactive recipient in this campaign")
    if receiver.id == giver.id:
        raise bad_request("They already have it")
    if body.quantity > entry.quantity:
        raise bad_request(f"Only {entry.quantity} available to give")

    item = await db.get(Item, entry.item_id)
    entry.quantity -= body.quantity
    if entry.quantity == 0:
        await db.delete(entry)
    target = (
        await db.execute(
            select(InventoryEntry).where(
                InventoryEntry.owner_type == "character",
                InventoryEntry.owner_id == receiver.id,
                InventoryEntry.item_id == entry.item_id,
            )
        )
    ).scalars().first()
    if target:
        target.quantity += body.quantity
    else:
        db.add(
            InventoryEntry(
                item_id=entry.item_id,
                owner_type="character",
                owner_id=receiver.id,
                quantity=body.quantity,
            )
        )
    await db.commit()

    assert item
    for char_id in (giver.id, receiver.id):
        hub.broadcast(
            giver.campaign_id,
            events.make_event(
                events.INVENTORY_UPDATED, giver.campaign_id, {"character_id": char_id}
            ),
        )
    return {
        "given": body.quantity,
        "item": item.name,
        "from": giver.name,
        "to": receiver.name,
    }


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

"""Level-1 starting equipment + spell counts, so a freshly-built character is
actually playable (gear in the pack, a real AC, and known spells the AI can
see) instead of arriving empty-handed.

Curated per-class kits — the SRD class data ships no starting-equipment lists,
so these are sensible fixed loadouts rather than the full choose-your-own SRD
tables. The DM/players can adjust afterward with modify_inventory.
"""

from app.services.items import change_inventory

# item name -> (category, base_ac). light adds full dex, medium caps dex at +2,
# heavy ignores dex. Used to set AC from whatever armor the kit grants.
ARMOR = {
    "leather armor": ("light", 11),
    "studded leather armor": ("light", 12),
    "hide armor": ("medium", 12),
    "scale mail": ("medium", 14),
    "chain mail": ("heavy", 16),
}

# class slug -> list of (item, quantity). Include armor/shield so AC is right.
STARTING_KITS: dict[str, list[tuple[str, int]]] = {
    "barbarian": [("greataxe", 1), ("handaxe", 2), ("javelin", 4), ("explorer's pack", 1)],
    "bard": [("leather armor", 1), ("rapier", 1), ("dagger", 1), ("entertainer's pack", 1), ("lute", 1)],
    "cleric": [("scale mail", 1), ("shield", 1), ("mace", 1), ("holy symbol", 1), ("priest's pack", 1)],
    "druid": [("leather armor", 1), ("wooden shield", 1), ("scimitar", 1), ("druidic focus", 1), ("explorer's pack", 1)],
    "fighter": [("chain mail", 1), ("shield", 1), ("longsword", 1), ("light crossbow", 1), ("crossbow bolt", 20), ("dungeoneer's pack", 1)],
    "monk": [("shortsword", 1), ("dart", 10), ("dungeoneer's pack", 1)],
    "paladin": [("chain mail", 1), ("shield", 1), ("longsword", 1), ("javelin", 5), ("holy symbol", 1), ("priest's pack", 1)],
    "ranger": [("scale mail", 1), ("shortsword", 2), ("longbow", 1), ("arrow", 20), ("explorer's pack", 1)],
    "rogue": [("leather armor", 1), ("rapier", 1), ("shortbow", 1), ("arrow", 20), ("dagger", 2), ("thieves' tools", 1), ("burglar's pack", 1)],
    "sorcerer": [("dagger", 2), ("light crossbow", 1), ("crossbow bolt", 20), ("component pouch", 1), ("dungeoneer's pack", 1)],
    "warlock": [("leather armor", 1), ("light crossbow", 1), ("crossbow bolt", 20), ("dagger", 2), ("component pouch", 1), ("scholar's pack", 1)],
    "wizard": [("quarterstaff", 1), ("dagger", 1), ("component pouch", 1), ("spellbook", 1), ("scholar's pack", 1)],
}

HAS_SHIELD = {"cleric", "druid", "fighter", "paladin"}

# class slug -> (cantrips known, level-1 spells known/prepared) at level 1.
# paladin & ranger get no spells until level 2, so they're absent.
CASTER_SLOTS_L1: dict[str, tuple[int, int]] = {
    "bard": (2, 4),
    "cleric": (3, 4),
    "druid": (2, 4),
    "sorcerer": (4, 2),
    "warlock": (2, 2),
    "wizard": (3, 6),
}


def kit_for(class_name: str) -> list[dict[str, int | str]]:
    """The starting kit for a class, as [{item, quantity}] for the wizard to
    preview. Accepts either a slug ('fighter') or a display name ('Fighter')."""
    slug = class_name.lower().replace(" ", "-")
    return [{"item": item, "quantity": qty} for item, qty in STARTING_KITS.get(slug, [])]


def compute_ac(class_slug: str, dex_mod: int) -> int:
    """AC from the kit's armor (+ shield), or unarmored 10+DEX."""
    kit = STARTING_KITS.get(class_slug, [])
    ac = 10 + dex_mod
    for item, _qty in kit:
        armor = ARMOR.get(item.lower())
        if armor:
            category, base = armor
            if category == "light":
                ac = base + dex_mod
            elif category == "medium":
                ac = base + min(dex_mod, 2)
            else:  # heavy
                ac = base
            break
    if class_slug in HAS_SHIELD:
        ac += 2
    return ac


async def grant_starting_kit(db, campaign_id: str, character) -> list[str]:
    """Create inventory rows for the character's class kit. Returns item names."""
    granted: list[str] = []
    for item, qty in STARTING_KITS.get(character.klass.lower().replace(" ", "-"), []):
        result = await change_inventory(
            db, campaign_id, "character", character.id, item, qty, "starting equipment"
        )
        if "error" not in result:
            granted.append(item)
    return granted

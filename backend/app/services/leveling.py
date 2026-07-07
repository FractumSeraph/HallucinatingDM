"""Level-up rules: what a character gains at each level (SRD 5.1).

Spell capacities use the SRD progression tables for known-spell casters
(bard/sorcerer/warlock/ranger), the spellbook convention for wizards
(2 new spells per level), and the prepared-caster formula (ability mod +
level, half for paladins) for cleric/druid/paladin — simplified to a
"known" list the player extends on level-up rather than daily preparation.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Character
from app.services import rules_5e

# class slug -> {level: cantrips known}. Breakpoints per the SRD class tables.
_CANTRIP_BREAKPOINTS: dict[str, list[tuple[int, int]]] = {
    "bard": [(1, 2), (4, 3), (10, 4)],
    "cleric": [(1, 3), (4, 4), (10, 5)],
    "druid": [(1, 2), (4, 3), (10, 4)],
    "sorcerer": [(1, 4), (4, 5), (10, 6)],
    "warlock": [(1, 2), (4, 3), (10, 4)],
    "wizard": [(1, 3), (4, 4), (10, 5)],
}

# Known-spell casters: class slug -> spells known at levels 1..20 (SRD).
_SPELLS_KNOWN: dict[str, list[int]] = {
    "bard": [4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 15, 16, 18, 19, 19, 20, 22, 22, 22],
    "sorcerer": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 12, 13, 13, 14, 14, 15, 15, 15, 15],
    "warlock": [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 11, 11, 12, 12, 13, 13, 14, 14, 15, 15],
    "ranger": [0, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11],
}

# Ability Score Improvement levels (SRD; fighter and rogue get extras).
_ASI_LEVELS: dict[str, set[int]] = {
    "fighter": {4, 6, 8, 12, 14, 16, 19},
    "rogue": {4, 8, 10, 12, 16, 19},
}
_ASI_DEFAULT = {4, 8, 12, 16, 19}


def cantrips_known(class_slug: str, level: int) -> int:
    breakpoints = _CANTRIP_BREAKPOINTS.get(class_slug)
    if not breakpoints:
        return 0
    known = 0
    for at_level, count in breakpoints:
        if level >= at_level:
            known = count
    return known


def spells_known_cap(class_slug: str, level: int, ability_scores: dict[str, int]) -> int:
    """How many leveled spells the character may know at this level."""
    level = max(1, min(level, 20))
    if class_slug in _SPELLS_KNOWN:
        return _SPELLS_KNOWN[class_slug][level - 1]
    if class_slug == "wizard":
        return 6 + 2 * (level - 1)  # spellbook: 6 at level 1, +2 per level
    if class_slug in ("cleric", "druid"):
        mod = rules_5e.ability_modifier(ability_scores.get("wis", 10))
        return max(1, mod + level)
    if class_slug == "paladin":
        if level < 2:
            return 0
        mod = rules_5e.ability_modifier(ability_scores.get("cha", 10))
        return max(1, mod + level // 2)
    return 0


def max_spell_level(class_slug: str, level: int) -> int:
    slots = rules_5e.spell_slots_for(class_slug, level)
    return max((int(lvl) for lvl in slots), default=0)


def is_asi_level(class_slug: str, level: int) -> bool:
    return level in _ASI_LEVELS.get(class_slug, _ASI_DEFAULT)


async def srd_class_features(db: AsyncSession, klass_name: str, at_level: int) -> list[dict[str, Any]]:
    from app.services.character_builder import get_srd

    entry = await get_srd(db, "class", klass_name.lower().replace(" ", "-"))
    if not entry:
        return []
    return [
        {"name": f.get("name", ""), "description": f.get("description", "")}
        for f in entry.data_json.get("features", [])
        if int(f.get("level", 99)) == at_level
    ]


async def level_up_options(db: AsyncSession, character: Character) -> dict[str, Any]:
    """Everything the pending level-up offers, for the frontend dialog."""
    slug = character.klass.lower().replace(" ", "-")
    new_level = character.level + 1
    scores = character.ability_scores_json

    hit_die = int(character.sheet_json.get("hit_die", 8))
    con_mod = rules_5e.ability_modifier(scores.get("con", 10))

    known = character.sheet_json.get("spells") or {}
    have_cantrips = len(known.get("cantrips") or [])
    have_spells = len(known.get("known") or [])

    cantrip_picks = max(0, cantrips_known(slug, new_level) - have_cantrips)
    spell_picks = max(0, spells_known_cap(slug, new_level, scores) - have_spells)
    castable = max_spell_level(slug, new_level)

    available: dict[str, list[str]] = {}
    descriptions: dict[str, str] = {}
    if cantrip_picks or spell_picks:
        from app.services.character_builder import class_spell_lists

        lists = await class_spell_lists(db, character.klass, castable)
        descriptions = lists["descriptions"]
        already = set((known.get("cantrips") or []) + (known.get("known") or []))
        for lvl, names in lists["by_level"].items():
            remaining = [n for n in names if n not in already]
            if remaining:
                available[str(lvl)] = remaining

    return {
        "new_level": new_level,
        "hp_gain": max(1, hit_die // 2 + 1 + con_mod),
        "new_slots": rules_5e.spell_slots_for(slug, new_level),
        "features": await srd_class_features(db, character.klass, new_level),
        "asi": is_asi_level(slug, new_level),
        "cantrip_picks": cantrip_picks,
        "spell_picks": spell_picks,
        "max_spell_level": castable,
        "available": available,  # {"0": [cantrip names], "1": [...], ...}
        "spell_descriptions": descriptions,
    }


class LevelUpError(ValueError):
    pass


def validate_asi(asi: dict[str, int], scores: dict[str, int]) -> None:
    if not asi:
        return
    total = sum(asi.values())
    if total > 2 or any(v < 1 or v > 2 for v in asi.values()) or len(asi) > 2:
        raise LevelUpError("ASI is +2 to one ability or +1 to two")
    for ability, bump in asi.items():
        if ability not in rules_5e.ABILITIES:
            raise LevelUpError(f"Unknown ability '{ability}'")
        if scores.get(ability, 10) + bump > 20:
            raise LevelUpError(f"{ability.upper()} can't exceed 20")

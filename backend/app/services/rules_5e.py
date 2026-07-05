"""Pure 5E math: ability modifiers, proficiency, XP, spell slots, skills.

Everything here is deterministic arithmetic over sheet data — the code side of
the "code enforces numbers, LLM adjudicates fiction" boundary.
"""

ABILITIES = ["str", "dex", "con", "int", "wis", "cha"]

SKILLS: dict[str, str] = {
    "acrobatics": "dex",
    "animal handling": "wis",
    "arcana": "int",
    "athletics": "str",
    "deception": "cha",
    "history": "int",
    "insight": "wis",
    "intimidation": "cha",
    "investigation": "int",
    "medicine": "wis",
    "nature": "int",
    "perception": "wis",
    "performance": "cha",
    "persuasion": "cha",
    "religion": "int",
    "sleight of hand": "dex",
    "stealth": "dex",
    "survival": "wis",
}

# XP required to reach each level (index = level, PHB p.15)
XP_THRESHOLDS = [
    0, 0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000, 64000,
    85000, 100000, 120000, 140000, 165000, 195000, 225000, 265000, 305000, 355000,
]

FULL_CASTERS = {"bard", "cleric", "druid", "sorcerer", "wizard"}
HALF_CASTERS = {"paladin", "ranger"}

# Full-caster spell slots by class level: {slot_level: count}
FULL_CASTER_SLOTS: dict[int, dict[int, int]] = {
    1: {1: 2},
    2: {1: 3},
    3: {1: 4, 2: 2},
    4: {1: 4, 2: 3},
    5: {1: 4, 2: 3, 3: 2},
    6: {1: 4, 2: 3, 3: 3},
    7: {1: 4, 2: 3, 3: 3, 4: 1},
    8: {1: 4, 2: 3, 3: 3, 4: 2},
    9: {1: 4, 2: 3, 3: 3, 4: 3, 5: 1},
    10: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2},
    11: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1},
    12: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1},
    13: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1},
    14: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1},
    15: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1},
    16: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1},
    17: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1, 9: 1},
    18: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 1, 7: 1, 8: 1, 9: 1},
    19: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 1, 8: 1, 9: 1},
    20: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 2, 8: 1, 9: 1},
}

# Warlock pact magic: (slots, slot_level) by class level
WARLOCK_SLOTS: dict[int, tuple[int, int]] = {
    1: (1, 1), 2: (2, 1), 3: (2, 2), 4: (2, 2), 5: (2, 3), 6: (2, 3),
    7: (2, 4), 8: (2, 4), 9: (2, 5), 10: (2, 5), 11: (3, 5), 12: (3, 5),
    13: (3, 5), 14: (3, 5), 15: (3, 5), 16: (3, 5), 17: (4, 5), 18: (4, 5),
    19: (4, 5), 20: (4, 5),
}

# Encounter building: XP thresholds per character level (DMG p.82)
ENCOUNTER_THRESHOLDS: dict[int, dict[str, int]] = {
    1: {"easy": 25, "medium": 50, "hard": 75, "deadly": 100},
    2: {"easy": 50, "medium": 100, "hard": 150, "deadly": 200},
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
    4: {"easy": 125, "medium": 250, "hard": 375, "deadly": 500},
    5: {"easy": 250, "medium": 500, "hard": 750, "deadly": 1100},
    6: {"easy": 300, "medium": 600, "hard": 900, "deadly": 1400},
    7: {"easy": 350, "medium": 750, "hard": 1100, "deadly": 1700},
    8: {"easy": 450, "medium": 900, "hard": 1400, "deadly": 2100},
    9: {"easy": 550, "medium": 1100, "hard": 1600, "deadly": 2400},
    10: {"easy": 600, "medium": 1200, "hard": 1900, "deadly": 2800},
    11: {"easy": 800, "medium": 1600, "hard": 2400, "deadly": 3600},
    12: {"easy": 1000, "medium": 2000, "hard": 3000, "deadly": 4500},
    13: {"easy": 1100, "medium": 2200, "hard": 3400, "deadly": 5100},
    14: {"easy": 1250, "medium": 2500, "hard": 3800, "deadly": 5700},
    15: {"easy": 1400, "medium": 2800, "hard": 4300, "deadly": 6400},
    16: {"easy": 1600, "medium": 3200, "hard": 4800, "deadly": 7200},
    17: {"easy": 2000, "medium": 3900, "hard": 5900, "deadly": 8800},
    18: {"easy": 2100, "medium": 4200, "hard": 6300, "deadly": 9500},
    19: {"easy": 2400, "medium": 4900, "hard": 7300, "deadly": 10900},
    20: {"easy": 2800, "medium": 5700, "hard": 8500, "deadly": 12700},
}

CONDITIONS = [
    "blinded", "charmed", "deafened", "frightened", "grappled", "incapacitated",
    "invisible", "paralyzed", "petrified", "poisoned", "prone", "restrained",
    "stunned", "unconscious", "exhaustion",
]

STANDARD_ARRAY = [15, 14, 13, 12, 10, 8]
POINT_BUY_BUDGET = 27
POINT_BUY_COST = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}


def ability_modifier(score: int) -> int:
    return (score - 10) // 2


def proficiency_bonus(level: int) -> int:
    return 2 + (max(1, min(level, 20)) - 1) // 4


def level_for_xp(xp: int) -> int:
    level = 1
    for lvl in range(1, 21):
        if xp >= XP_THRESHOLDS[lvl]:
            level = lvl
    return level


def xp_for_next_level(level: int) -> int | None:
    if level >= 20:
        return None
    return XP_THRESHOLDS[level + 1]


def spell_slots_for(class_slug: str, level: int) -> dict[str, dict[str, int]]:
    """Return {"<slot level>": {"max": n, "used": 0}} for a class/level."""
    level = max(1, min(level, 20))
    slug = class_slug.lower()
    slots: dict[int, int] = {}
    if slug in FULL_CASTERS:
        slots = FULL_CASTER_SLOTS[level]
    elif slug in HALF_CASTERS:
        # Half casters use the full table at ceil(level/2), no slots at level 1
        if level >= 2:
            slots = FULL_CASTER_SLOTS[(level + 1) // 2]
    elif slug == "warlock":
        count, slot_level = WARLOCK_SLOTS[level]
        slots = {slot_level: count}
    return {str(lvl): {"max": n, "used": 0} for lvl, n in sorted(slots.items())}


def validate_point_buy(scores: dict[str, int]) -> str | None:
    """Return an error string, or None if the spread is a legal 27-point buy."""
    if set(scores.keys()) != set(ABILITIES):
        return "Scores must cover exactly str/dex/con/int/wis/cha"
    total = 0
    for ability, score in scores.items():
        if score not in POINT_BUY_COST:
            return f"{ability} must be between 8 and 15 for point buy"
        total += POINT_BUY_COST[score]
    if total > POINT_BUY_BUDGET:
        return f"Point buy total {total} exceeds budget of {POINT_BUY_BUDGET}"
    return None


def validate_standard_array(scores: dict[str, int]) -> str | None:
    if set(scores.keys()) != set(ABILITIES):
        return "Scores must cover exactly str/dex/con/int/wis/cha"
    if sorted(scores.values(), reverse=True) != sorted(STANDARD_ARRAY, reverse=True):
        return f"Standard array must use exactly {STANDARD_ARRAY}"
    return None


def validate_rolled(scores: dict[str, int]) -> str | None:
    """Sanity-check scores that came from the server roll endpoint: every
    ability present and each within the 3–18 range a 4d6-drop-lowest can yield."""
    if set(scores.keys()) != set(ABILITIES):
        return "Scores must cover exactly str/dex/con/int/wis/cha"
    for ability, score in scores.items():
        if not 3 <= score <= 18:
            return f"{ability} of {score} is outside the rollable 3–18 range"
    return None


def max_hp_for(hit_die: int, level: int, con_mod: int) -> int:
    """Level 1 = max die; later levels use the fixed average (PHB default)."""
    per_level = hit_die // 2 + 1
    hp = hit_die + con_mod + (level - 1) * (per_level + con_mod)
    return max(1, hp)


def encounter_multiplier(count: int) -> float:
    """DMG encounter multiplier by number of monsters."""
    if count <= 1:
        return 1.0
    if count == 2:
        return 1.5
    if count <= 6:
        return 2.0
    if count <= 10:
        return 2.5
    if count <= 14:
        return 3.0
    return 4.0


CR_TO_XP: dict[str, int] = {
    "0": 10, "1/8": 25, "1/4": 50, "1/2": 100, "1": 200, "2": 450, "3": 700,
    "4": 1100, "5": 1800, "6": 2300, "7": 2900, "8": 3900, "9": 5000, "10": 5900,
    "11": 7200, "12": 8400, "13": 10000, "14": 11500, "15": 13000, "16": 15000,
    "17": 18000, "18": 20000, "19": 22000, "20": 25000, "21": 33000, "22": 41000,
    "23": 50000, "24": 62000, "25": 75000, "26": 90000, "27": 105000, "28": 120000,
    "29": 135000, "30": 155000,
}

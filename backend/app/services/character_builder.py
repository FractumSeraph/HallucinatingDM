"""Builds a legal 5E level-1 character from a wizard payload + SRD data.

The client (or the AI chargen assistant) picks options; this module validates
choices against the SRD and computes every derived value — the LLM/user never
writes HP, AC, or save DCs directly.
"""

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Character, SrdEntry
from app.services import rules_5e
from app.services.dice import roll


class BuildError(ValueError):
    pass


class CharacterBuild(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    race: str
    subrace: str = ""  # e.g. "High Elf" — must match a subrace of the chosen race
    klass: str
    background: str = "acolyte"
    alignment: str = ""
    method: str = Field(default="standard", pattern="^(standard|pointbuy|roll)$")
    # Base scores before racial bonuses. Ignored for method="roll" (server rolls).
    base_scores: dict[str, int] = {}
    skill_choices: list[str] = []
    cantrips: list[str] = []  # caster: chosen cantrips (level-0 spells)
    spells: list[str] = []  # caster: chosen level-1 spells
    personality: str = ""
    backstory: str = ""


async def get_srd(db: AsyncSession, kind: str, slug: str) -> SrdEntry | None:
    result = await db.execute(
        select(SrdEntry).where(SrdEntry.kind == kind, SrdEntry.slug == slug.lower())
    )
    return result.scalar_one_or_none()


async def class_spell_options(db: AsyncSession, class_name: str) -> dict[str, Any]:
    """Level-0 and level-1 spell names available to a class, from the SRD,
    plus a short description per spell so pickers aren't a list of bare names."""
    rows = list((await db.execute(select(SrdEntry).where(SrdEntry.kind == "spell"))).scalars())
    cn = class_name.lower()
    cantrips, level1 = [], []
    descriptions: dict[str, str] = {}
    for r in rows:
        d = r.data_json
        classes = [str(c).lower() for c in (d.get("classes") or [])]
        if cn not in classes:
            continue
        name = d.get("name", r.name)
        if d.get("level") == 0:
            cantrips.append(name)
        elif d.get("level") == 1:
            level1.append(name)
        else:
            continue
        desc = " ".join(str(d.get("description", "")).split())
        if desc:
            descriptions[name] = desc[:160] + ("…" if len(desc) > 160 else "")
    return {"cantrips": sorted(cantrips), "level1": sorted(level1), "descriptions": descriptions}


async def _validate_spells(
    db: AsyncSession, klass: SrdEntry, cantrips: list[str], spells: list[str]
) -> dict[str, list[str]]:
    """Validate a caster's chosen spells against the class list and level-1
    known counts. Returns the stored {"cantrips","known"} or raises BuildError."""
    from app.services.starting_kit import CASTER_SLOTS_L1

    slug = klass.slug
    if slug not in CASTER_SLOTS_L1:
        if cantrips or spells:
            raise BuildError(f"{klass.name} does not choose spells at level 1")
        return {"cantrips": [], "known": []}

    max_cantrips, max_spells = CASTER_SLOTS_L1[slug]
    if len(cantrips) > max_cantrips:
        raise BuildError(f"{klass.name} knows at most {max_cantrips} cantrips at level 1")
    if len(spells) > max_spells:
        raise BuildError(f"{klass.name} knows at most {max_spells} level-1 spells at level 1")

    options = await class_spell_options(db, klass.name)
    valid_cantrips = {c.lower() for c in options["cantrips"]}
    valid_level1 = {s.lower() for s in options["level1"]}
    for c in cantrips:
        if c.lower() not in valid_cantrips:
            raise BuildError(f"'{c}' is not a {klass.name} cantrip")
    for s in spells:
        if s.lower() not in valid_level1:
            raise BuildError(f"'{s}' is not a level-1 {klass.name} spell")
    return {"cantrips": list(cantrips), "known": list(spells)}


def _roll_scores() -> dict[str, int]:
    """4d6 drop lowest, in ability order (server-rolled, auditable)."""
    return {ability: roll("4d6kh3").total for ability in rules_5e.ABILITIES}


async def build_character(
    db: AsyncSession, campaign_id: str, user_id: str, build: CharacterBuild
) -> Character:
    race = await get_srd(db, "race", build.race)
    if not race:
        raise BuildError(f"Unknown race '{build.race}'")
    klass = await get_srd(db, "class", build.klass)
    if not klass:
        raise BuildError(f"Unknown class '{build.klass}'")
    background = await get_srd(db, "background", build.background)

    # --- Ability scores -------------------------------------------------------
    if build.method == "roll":
        # The wizard rolls up front (via /roll-abilities) so the player can pick
        # a class that fits their scores; those rolled values arrive here. If
        # none were supplied (older client / API caller), roll now.
        if build.base_scores:
            base_scores = {k: int(v) for k, v in build.base_scores.items()}
            error = rules_5e.validate_rolled(base_scores)
            if error:
                raise BuildError(error)
        else:
            base_scores = _roll_scores()
    else:
        base_scores = {k: int(v) for k, v in build.base_scores.items()}
        error = (
            rules_5e.validate_point_buy(base_scores)
            if build.method == "pointbuy"
            else rules_5e.validate_standard_array(base_scores)
        )
        if error:
            raise BuildError(error)

    subrace_data: dict = {}
    if build.subrace:
        matches = [
            s
            for s in (race.data_json.get("subraces") or [])
            if str(s.get("name", "")).lower() == build.subrace.lower()
        ]
        if not matches:
            raise BuildError(f"'{build.subrace}' is not a subrace of {race.name}")
        subrace_data = matches[0]

    scores = dict(base_scores)
    for bonus in race.data_json.get("ability_bonuses", []) + subrace_data.get(
        "ability_bonuses", []
    ):
        ability = str(bonus.get("ability", "")).lower()
        if ability in scores:
            scores[ability] += int(bonus.get("bonus", 0))

    # --- Proficiencies ---------------------------------------------------------
    class_profs = klass.data_json.get("proficiencies", {})
    skill_rule = class_profs.get("skills", {}) or {}
    allowed = {s.lower() for s in skill_rule.get("from", [])}
    choose_n = int(skill_rule.get("choose", 0))
    chosen = [s.lower() for s in build.skill_choices]
    if len(chosen) != choose_n:
        raise BuildError(f"Pick exactly {choose_n} class skills from: {sorted(allowed)}")
    for skill in chosen:
        if skill not in allowed:
            raise BuildError(f"'{skill}' is not a {klass.name} skill option")
        if skill not in rules_5e.SKILLS:
            raise BuildError(f"Unknown skill '{skill}'")

    bg_skills = [
        s.lower() for s in (background.data_json.get("skill_proficiencies", []) if background else [])
    ]
    skills = sorted(set(chosen) | set(bg_skills))
    saves = [s.lower() for s in klass.data_json.get("saving_throws", [])]

    # --- Derived numbers --------------------------------------------------------
    con_mod = rules_5e.ability_modifier(scores["con"])
    dex_mod = rules_5e.ability_modifier(scores["dex"])
    hit_die = int(klass.data_json.get("hit_die", 8))
    hp_max = rules_5e.max_hp_for(hit_die, 1, con_mod)

    features = [
        f for f in klass.data_json.get("features", []) if int(f.get("level", 99)) <= 1
    ]

    spells = await _validate_spells(db, klass, build.cantrips, build.spells)

    from app.services.starting_kit import compute_ac

    ac = compute_ac(klass.slug, dex_mod)

    character = Character(
        campaign_id=campaign_id,
        user_id=user_id,
        name=build.name,
        race=f"{subrace_data['name']}" if subrace_data else race.name,
        klass=klass.name,
        background=background.name if background else build.background,
        alignment=build.alignment,
        level=1,
        xp=0,
        hp_current=hp_max,
        hp_max=hp_max,
        ac=ac,  # from the class's starting armor (+shield), else unarmored 10+DEX
        ability_scores_json=scores,
        proficiencies_json={
            "skills": skills,
            "saves": saves,
            "armor": class_profs.get("armor", []),
            "weapons": class_profs.get("weapons", []),
            "tools": class_profs.get("tools", []),
        },
        spell_slots_json=rules_5e.spell_slots_for(klass.slug, 1),
        resources_json={"hit_dice": {"max": 1, "used": 0, "die": hit_die}},
        conditions_json=[],
        death_saves_json={"successes": 0, "failures": 0},
        currency_json={"cp": 0, "sp": 0, "ep": 0, "gp": 15, "pp": 0},
        sheet_json={
            "speed": race.data_json.get("speed", 30),
            "size": race.data_json.get("size", "Medium"),
            "traits": race.data_json.get("traits", []) + subrace_data.get("traits", []),
            "base_race": race.name,
            "features": features,
            "languages": race.data_json.get("languages", []),
            "spellcasting_ability": klass.data_json.get("spellcasting_ability"),
            "spells": spells,  # {"cantrips": [...], "known": [...]}
            "hit_die": hit_die,
            "ability_method": build.method,
            "base_scores": base_scores,
            "personality": build.personality,
            "backstory": build.backstory,
            "background_feature": (background.data_json.get("feature") if background else None),
        },
        status="active",
    )
    return character


def character_out(c: Character) -> dict[str, Any]:
    return {
        "id": c.id,
        "campaign_id": c.campaign_id,
        "user_id": c.user_id,
        "name": c.name,
        "race": c.race,
        "klass": c.klass,
        "background": c.background,
        "alignment": c.alignment,
        "level": c.level,
        "xp": c.xp,
        "hp_current": c.hp_current,
        "hp_max": c.hp_max,
        "hp_temp": c.hp_temp,
        "ac": c.ac,
        "ability_scores_json": c.ability_scores_json,
        "proficiencies_json": c.proficiencies_json,
        "spell_slots_json": c.spell_slots_json,
        "resources_json": c.resources_json,
        "conditions_json": c.conditions_json,
        "death_saves_json": c.death_saves_json,
        "currency_json": c.currency_json,
        "sheet_json": c.sheet_json,
        "notes": c.notes,
        "status": c.status,
    }

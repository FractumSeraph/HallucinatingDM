"""Resolve LLM-provided entity references (id or name) to real rows.

The hallucination firewall: models mangle ids and invent names, so every tool
argument that targets an entity goes through here. Misses return the nearest
names so the model can self-correct on its next call.
"""

from dataclasses import dataclass
from typing import Any, Literal

from rapidfuzz import fuzz, process, utils
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NPC, Character, Combatant

EntityKind = Literal["character", "npc", "combatant"]


@dataclass
class Resolved:
    kind: EntityKind
    row: Any
    name: str


@dataclass
class ResolveMiss:
    query: str
    suggestions: list[str]

    def error(self) -> str:
        hint = f" Did you mean: {', '.join(self.suggestions)}?" if self.suggestions else ""
        return f"No character or NPC matching '{self.query}'.{hint}"


async def resolve_target(
    db: AsyncSession,
    campaign_id: str,
    ref: str,
    scene_id: str | None = None,
) -> Resolved | ResolveMiss:
    """ref may be an entity id or a (possibly imprecise) name."""
    ref = (ref or "").strip()

    characters = list(
        (
            await db.execute(
                select(Character).where(
                    Character.campaign_id == campaign_id,
                    Character.status.in_(["active", "draft"]),
                )
            )
        ).scalars()
    )
    npcs = list(
        (
            await db.execute(select(NPC).where(NPC.campaign_id == campaign_id))
        ).scalars()
    )
    combatants: list[Combatant] = []
    if scene_id:
        from app.models import CombatEncounter

        encounter = (
            await db.execute(
                select(CombatEncounter).where(
                    CombatEncounter.scene_id == scene_id,
                    CombatEncounter.status == "active",
                )
            )
        ).scalars().first()
        if encounter:
            combatants = list(
                (
                    await db.execute(
                        select(Combatant).where(Combatant.encounter_id == encounter.id)
                    )
                ).scalars()
            )

    pool: list[Resolved] = (
        [Resolved("character", c, c.name) for c in characters]
        + [Resolved("npc", n, n.name) for n in npcs]
        + [Resolved("combatant", c, c.name) for c in combatants]
    )

    # 1) exact id
    for item in pool:
        if item.row.id == ref:
            return item
    # 2) exact name (combatants like "Goblin 2" win over generic matches)
    lowered = ref.lower()
    for item in pool:
        if item.name.lower() == lowered:
            return item
    # 2b) NPC aliases
    for item in pool:
        if item.kind == "npc":
            aliases = [str(a).lower() for a in (item.row.aliases_json or [])]
            if lowered in aliases:
                return item
    # 3) fuzzy unique-winner
    if pool:
        names = {i: item.name for i, item in enumerate(pool)}
        matches = process.extract(
            ref, names, scorer=fuzz.WRatio, processor=utils.default_process,
            score_cutoff=87, limit=2,
        )
        if len(matches) == 1 or (
            len(matches) > 1 and matches[0][1] - matches[1][1] >= 5
        ):
            return pool[matches[0][2]]

    suggestions = [
        m[0]
        for m in process.extract(
            ref, [item.name for item in pool], scorer=fuzz.WRatio,
            processor=utils.default_process, limit=3,
        )
        if m[1] >= 50
    ]
    return ResolveMiss(query=ref, suggestions=suggestions)

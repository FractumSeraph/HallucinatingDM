"""Initiative and turn-order tracking — server-enforced, shared by REST and AI."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.entity_resolver import ResolveMiss, resolve_target
from app.models import NPC, Character, Combatant, CombatEncounter, Scene, SrdEntry
from app.realtime import events
from app.realtime.hub import hub
from app.services import rules_5e
from app.services.dice import roll_d20


class CombatError(ValueError):
    pass


async def get_active_encounter(db: AsyncSession, scene_id: str) -> CombatEncounter | None:
    return (
        (
            await db.execute(
                select(CombatEncounter).where(
                    CombatEncounter.scene_id == scene_id,
                    CombatEncounter.status == "active",
                )
            )
        )
        .scalars()
        .first()
    )


async def combat_snapshot(db: AsyncSession, scene_id: str) -> dict[str, Any]:
    encounter = await get_active_encounter(db, scene_id)
    if not encounter:
        return {"encounter": None, "combatants": []}
    combatants = list(
        (
            await db.execute(
                select(Combatant)
                .where(Combatant.encounter_id == encounter.id)
                .order_by(Combatant.sort_order)
            )
        ).scalars()
    )
    out = []
    for c in combatants:
        hp_current, hp_max, ac = c.hp_current, c.hp_max, c.ac
        conditions = c.conditions_json
        if c.ref_type == "character" and c.ref_id:
            character = await db.get(Character, c.ref_id)
            if character:
                hp_current, hp_max, ac = character.hp_current, character.hp_max, character.ac
                conditions = character.conditions_json
        out.append(
            {
                "id": c.id,
                "ref_type": c.ref_type,
                "ref_id": c.ref_id,
                "name": c.name,
                "initiative": c.initiative,
                "hp_current": hp_current,
                "hp_max": hp_max,
                "ac": ac if c.ref_type == "character" else None,  # monster AC stays hidden
                "conditions_json": conditions,
                "defeated": c.defeated,
            }
        )
    return {
        "encounter": {
            "id": encounter.id,
            "status": encounter.status,
            "round": encounter.round,
            "active_combatant_id": encounter.active_combatant_id,
        },
        "combatants": out,
    }


async def broadcast_combat(db: AsyncSession, scene: Scene) -> dict[str, Any]:
    snapshot = await combat_snapshot(db, scene.id)
    hub.broadcast(
        scene.campaign_id,
        events.make_event(events.COMBAT_UPDATED, scene.campaign_id, snapshot, scene.id),
        scene_id=scene.id,
    )
    return snapshot


def _dex_mod_from_statblock(stat_block: dict | None) -> int:
    if not stat_block:
        return 0
    return rules_5e.ability_modifier(int(stat_block.get("dex", 10)))


async def start_encounter(
    db: AsyncSession, scene: Scene, participants: list[str]
) -> dict[str, Any]:
    """participants: character/NPC names or ids, or SRD monster slugs/names,
    optionally 'goblin x3' for multiples."""
    if await get_active_encounter(db, scene.id):
        raise CombatError("An encounter is already active in this scene")

    encounter = CombatEncounter(scene_id=scene.id, status="active", round=1)
    db.add(encounter)
    await db.flush()

    rows: list[Combatant] = []
    for raw in participants:
        ref = raw.strip()
        count = 1
        if " x" in ref.lower():
            base, _, count_txt = ref.lower().rpartition(" x")
            if count_txt.isdigit():
                ref = raw[: len(base)].strip()
                count = min(int(count_txt), 20)

        target = await resolve_target(db, scene.campaign_id, ref, scene.id)
        if not isinstance(target, ResolveMiss):
            if isinstance(target.row, Character):
                init, _faces = roll_d20()
                init += rules_5e.ability_modifier(
                    target.row.ability_scores_json.get("dex", 10)
                )
                rows.append(
                    Combatant(
                        encounter_id=encounter.id,
                        ref_type="character",
                        ref_id=target.row.id,
                        name=target.name,
                        initiative=init,
                    )
                )
                continue
            if isinstance(target.row, NPC):
                stats = target.row.stat_block_json
                init, _ = roll_d20()
                init += _dex_mod_from_statblock(stats)
                hp = int(stats.get("hp", 10)) if stats else 10
                rows.append(
                    Combatant(
                        encounter_id=encounter.id,
                        ref_type="npc",
                        ref_id=target.row.id,
                        name=target.name,
                        initiative=init,
                        hp_current=target.row.hp_current if target.row.hp_current is not None else hp,
                        hp_max=hp,
                        ac=int(stats.get("ac", 10)) if stats else 10,
                        stat_block_json=stats,
                    )
                )
                continue

        # otherwise: an SRD monster by name/slug — one Combatant per copy
        srd = (
            await db.execute(
                select(SrdEntry).where(
                    SrdEntry.kind == "monster",
                    (SrdEntry.slug == ref.lower().replace(" ", "-"))
                    | (SrdEntry.name.ilike(ref)),
                )
            )
        ).scalars().first()
        if not srd:
            raise CombatError(
                f"Can't find combatant '{ref}' (no character, NPC, or SRD monster matches)"
            )
        stats = srd.data_json
        for i in range(count):
            init, _ = roll_d20()
            init += _dex_mod_from_statblock(stats)
            rows.append(
                Combatant(
                    encounter_id=encounter.id,
                    ref_type="monster",
                    ref_id=None,
                    name=f"{srd.name} {i + 1}" if count > 1 else srd.name,
                    initiative=init,
                    hp_current=int(stats.get("hp", 10)),
                    hp_max=int(stats.get("hp", 10)),
                    ac=int(stats.get("ac", 10)),
                    stat_block_json=stats,
                )
            )

    if not rows:
        raise CombatError("No combatants")

    rows.sort(key=lambda c: (-c.initiative, c.name))
    for order, c in enumerate(rows):
        c.sort_order = order
        db.add(c)
    await db.flush()  # assign ids before referencing the first combatant
    encounter.active_combatant_id = rows[0].id
    await db.commit()
    return await broadcast_combat(db, scene)


async def advance_turn(db: AsyncSession, scene: Scene) -> dict[str, Any]:
    encounter = await get_active_encounter(db, scene.id)
    if not encounter:
        raise CombatError("No active encounter")
    combatants = list(
        (
            await db.execute(
                select(Combatant)
                .where(Combatant.encounter_id == encounter.id)
                .order_by(Combatant.sort_order)
            )
        ).scalars()
    )
    alive = [c for c in combatants if not c.defeated]
    if not alive:
        raise CombatError("Everyone is down — end the encounter instead")

    current_idx = next(
        (i for i, c in enumerate(combatants) if c.id == encounter.active_combatant_id), -1
    )
    for step in range(1, len(combatants) + 1):
        nxt = combatants[(current_idx + step) % len(combatants)]
        if not nxt.defeated:
            if (current_idx + step) >= len(combatants):
                encounter.round += 1
            encounter.active_combatant_id = nxt.id
            break
    await db.commit()
    return await broadcast_combat(db, scene)


async def end_encounter(db: AsyncSession, scene: Scene) -> dict[str, Any]:
    encounter = await get_active_encounter(db, scene.id)
    if not encounter:
        raise CombatError("No active encounter")
    encounter.status = "ended"
    await db.commit()
    return await broadcast_combat(db, scene)

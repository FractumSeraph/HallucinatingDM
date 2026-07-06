"""Initiative and turn-order tracking — server-enforced, shared by REST and AI.

The server is the referee: it auto-rolls death saves for downed characters
when their turn comes up, refuses to end combat while foes are still standing
(the human DM can force it), and can reject encounters wildly over the party's
XP budget. These are hard guarantees — unlike prompt rules, the model can't
forget them.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.entity_resolver import ResolveMiss, resolve_target
from app.models import NPC, Character, Combatant, CombatEncounter, Scene, SrdEntry
from app.realtime import events
from app.realtime.hub import hub
from app.services import rules_5e
from app.services.dice import roll_d20
from app.services.messages import create_message


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


def _foe_budget_error(
    party_levels: list[int], foe_xps: list[int]
) -> str | None:
    """DMG math: is this encounter at/over the party's deadly threshold?"""
    if not party_levels or not foe_xps:
        return None
    deadly = sum(
        rules_5e.ENCOUNTER_THRESHOLDS[min(level, 20)]["deadly"] for level in party_levels
    )
    adjusted = int(sum(foe_xps) * rules_5e.encounter_multiplier(len(foe_xps)))
    if adjusted >= deadly:
        return (
            f"Encounter rejected: adjusted foe XP {adjusted} is at/over the party's "
            f"DEADLY threshold ({deadly}). Choose fewer or weaker foes (see "
            f"suggest_encounter), or pass allow_deadly=true ONLY if the story "
            f"truly demands a potentially lethal fight."
        )
    return None


async def start_encounter(
    db: AsyncSession,
    scene: Scene,
    participants: list[str],
    enforce_budget: bool = False,
) -> dict[str, Any]:
    """participants: character/NPC names or ids, or SRD monster slugs/names,
    optionally 'goblin x3' for multiples. With enforce_budget=True (the AI
    path), encounters at/over the party's deadly XP budget are rejected."""
    if await get_active_encounter(db, scene.id):
        raise CombatError("An encounter is already active in this scene")

    # Resolve every participant BEFORE persisting anything, so a rejected
    # encounter leaves no orphan rows behind in the shared session.
    rows: list[Combatant] = []
    party_levels: list[int] = []
    foe_xps: list[int] = []
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
                party_levels.append(target.row.level)
                rows.append(
                    Combatant(
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
                if stats and target.row.disposition not in ("friendly", "ally", "helpful"):
                    foe_xps.append(rules_5e.CR_TO_XP.get(str(stats.get("cr", "0")), 10))
                rows.append(
                    Combatant(
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
            foe_xps.append(rules_5e.CR_TO_XP.get(str(stats.get("cr", "0")), 10))
            rows.append(
                Combatant(
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

    if enforce_budget:
        error = _foe_budget_error(party_levels, foe_xps)
        if error:
            raise CombatError(error)

    encounter = CombatEncounter(scene_id=scene.id, status="active", round=1)
    db.add(encounter)
    await db.flush()

    rows.sort(key=lambda c: (-c.initiative, c.name))
    for order, c in enumerate(rows):
        c.encounter_id = encounter.id
        c.sort_order = order
        db.add(c)
    await db.flush()  # assign ids before referencing the first combatant
    encounter.active_combatant_id = rows[0].id
    await db.commit()
    return await broadcast_combat(db, scene)


async def _auto_death_save(
    db: AsyncSession, scene: Scene, character: Character, combatant: Combatant
) -> None:
    """A downed character's turn IS their death save — the server rolls it.
    5E: 10+ succeeds, natural 20 restores 1 HP, natural 1 counts twice,
    3 successes stabilize, 3 failures kill."""
    saves = dict(character.death_saves_json or {"successes": 0, "failures": 0})
    if saves.get("stable") or character.status == "dead":
        return

    d20, _ = roll_d20()
    if d20 == 20:
        character.hp_current = 1
        character.death_saves_json = {"successes": 0, "failures": 0}
        conditions = set(character.conditions_json)
        conditions.discard("unconscious")
        character.conditions_json = sorted(conditions)
        note = (
            f"💀 {character.name}'s death save: natural 20! They surge back to "
            f"consciousness with 1 HP."
        )
    elif d20 >= 10:
        saves["successes"] = saves.get("successes", 0) + 1
        if saves["successes"] >= 3:
            saves["stable"] = True
            note = (
                f"💀 {character.name}'s death save: {d20} — success "
                f"({saves['successes']}/3). They are STABLE (unconscious at 0 HP)."
            )
        else:
            note = (
                f"💀 {character.name}'s death save: {d20} — success "
                f"({saves['successes']} success{'es' if saves['successes'] > 1 else ''}, "
                f"{saves.get('failures', 0)} failures)."
            )
        character.death_saves_json = saves
    else:
        saves["failures"] = saves.get("failures", 0) + (2 if d20 == 1 else 1)
        if saves["failures"] >= 3:
            character.status = "dead"
            combatant.defeated = True
            note = (
                f"💀 {character.name}'s death save: {d20} — "
                f"{'natural 1, two failures' if d20 == 1 else 'failure'} "
                f"({saves['failures']}/3). {character.name} has DIED."
            )
        else:
            note = (
                f"💀 {character.name}'s death save: {d20} — "
                f"{'natural 1, two failures' if d20 == 1 else 'failure'} "
                f"({saves.get('successes', 0)} successes, {saves['failures']} failures)."
            )
        character.death_saves_json = saves

    await create_message(
        db, scene, author_type="system", kind="system", content=note
    )
    from app.services.bookkeeping import broadcast_character

    broadcast_character(scene.campaign_id, character)


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
        if nxt.defeated:
            continue
        # A downed character's turn is just their death save — the server
        # rolls it and moves on, never waiting on an unconscious player.
        if nxt.ref_type == "character" and nxt.ref_id:
            character = await db.get(Character, nxt.ref_id)
            if character and character.hp_current == 0:
                await _auto_death_save(db, scene, character, nxt)
                continue
        if (current_idx + step) >= len(combatants):
            encounter.round += 1
        encounter.active_combatant_id = nxt.id
        break
    else:
        raise CombatError(
            "No combatant can take a turn (everyone standing is down or dying) — "
            "end the encounter"
        )
    await db.commit()
    return await broadcast_combat(db, scene)


async def _standing_foes(db: AsyncSession, combatants: list[Combatant]) -> list[str]:
    """Non-character combatants still in the fight, excluding NPCs whose
    disposition marks them as on the party's side."""
    standing = []
    for c in combatants:
        if c.ref_type == "character" or c.defeated or (c.hp_current or 0) <= 0:
            continue
        if c.ref_type == "npc" and c.ref_id:
            npc = await db.get(NPC, c.ref_id)
            if npc and npc.disposition in ("friendly", "ally", "helpful"):
                continue
        standing.append(c.name)
    return standing


async def remove_combatant(db: AsyncSession, scene: Scene, name: str) -> dict[str, Any]:
    """Take a combatant out of the fight without killing them — they fled,
    surrendered, or stood down. Lets end_combat succeed honestly."""
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
    match = next(
        (c for c in combatants if c.name.lower() == name.lower().strip()), None
    )
    if not match:
        raise CombatError(
            f"No combatant named '{name}' — current: "
            + ", ".join(c.name for c in combatants)
        )
    match.defeated = True
    await create_message(
        db, scene, author_type="system", kind="system",
        content=f"🏳️ {match.name} is out of the fight.",
    )
    if encounter.active_combatant_id == match.id:
        await db.commit()
        return await advance_turn(db, scene)
    await db.commit()
    return await broadcast_combat(db, scene)


async def end_encounter(
    db: AsyncSession, scene: Scene, force: bool = False
) -> dict[str, Any]:
    """End combat. Refuses while foes are still standing unless force=True
    (the human DM's override) — enemies must be defeated, flee, or surrender
    (remove_combatant) first."""
    encounter = await get_active_encounter(db, scene.id)
    if not encounter:
        raise CombatError("No active encounter")
    if not force:
        combatants = list(
            (
                await db.execute(
                    select(Combatant).where(Combatant.encounter_id == encounter.id)
                )
            ).scalars()
        )
        standing = await _standing_foes(db, combatants)
        if standing:
            raise CombatError(
                f"Can't end combat: {', '.join(standing)} "
                f"{'are' if len(standing) > 1 else 'is'} still up and fighting. "
                f"Defeat them, or mark them fled/surrendered with "
                f"advance_combat op='remove' target='<name>'."
            )
    encounter.status = "ended"
    await db.commit()
    return await broadcast_combat(db, scene)

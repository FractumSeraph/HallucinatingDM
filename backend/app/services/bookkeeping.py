"""Game-state mutations shared by REST endpoints and AI tools.

Every mutation records inverse patches (for DM retcon) into the ToolContext
when one is provided, clamps values, applies 5E consequences (unconscious,
death saves), and broadcasts live events.
"""

from typing import Any

from app.ai.entity_resolver import Resolved
from app.ai.tools.registry import ToolContext
from app.models import NPC, Character, Combatant
from app.realtime import events
from app.realtime.hub import hub
from app.services.character_builder import character_out
from app.services.rules_5e import level_for_xp


def _record_inverse(ctx: ToolContext | None, kind: str, row_id: str, patch: dict[str, Any]) -> None:
    if ctx is not None:
        ctx.inverse_patches.append({"kind": kind, "id": row_id, "patch": patch})


def broadcast_character(campaign_id: str, character: Character) -> None:
    hub.broadcast(
        campaign_id,
        events.make_event(events.CHARACTER_UPDATED, campaign_id, character_out(character)),
    )


async def _sync_npc_combatant(ctx: ToolContext, npc: NPC) -> None:
    """Propagate an NPC's HP/defeat to its combatant row in the scene's active
    encounter, if it's in one."""
    from sqlalchemy import select

    from app.models import CombatEncounter

    encounter = (
        (
            await ctx.db.execute(
                select(CombatEncounter).where(
                    CombatEncounter.scene_id == ctx.scene.id,
                    CombatEncounter.status == "active",
                )
            )
        )
        .scalars()
        .first()
    )
    if not encounter:
        return
    combatants = (
        await ctx.db.execute(
            select(Combatant).where(
                Combatant.encounter_id == encounter.id,
                Combatant.ref_type == "npc",
                Combatant.ref_id == npc.id,
            )
        )
    ).scalars()
    for combatant in combatants:
        combatant.hp_current = npc.hp_current
        if (npc.hp_current or 0) <= 0 or npc.status == "dead":
            combatant.defeated = True


async def apply_hp_change(
    ctx: ToolContext, target: Resolved, delta: int, reason: str = ""
) -> dict[str, Any]:
    """Positive delta heals, negative damages. Returns a result summary."""
    row = target.row
    result: dict[str, Any] = {"target": target.name, "delta": delta}

    if target.kind == "character":
        character: Character = row
        _record_inverse(
            ctx,
            "character",
            character.id,
            {
                "hp_current": character.hp_current,
                "hp_temp": character.hp_temp,
                "conditions_json": list(character.conditions_json),
                "death_saves_json": dict(character.death_saves_json),
            },
        )
        remaining = delta
        if remaining < 0 and character.hp_temp > 0:
            absorbed = min(character.hp_temp, -remaining)
            character.hp_temp -= absorbed
            remaining += absorbed
            result["absorbed_by_temp_hp"] = absorbed

        was_up = character.hp_current > 0
        new_hp = max(0, min(character.hp_current + remaining, character.hp_max))
        # Instant death: leftover damage >= max HP while at 0
        overflow = -(character.hp_current + remaining) if remaining < 0 else 0
        character.hp_current = new_hp
        conditions = set(character.conditions_json)
        if new_hp == 0 and was_up:
            if overflow >= character.hp_max:
                character.status = "dead"
                result["instant_death"] = True
            else:
                conditions.add("unconscious")
                character.death_saves_json = {"successes": 0, "failures": 0}
                result["now_unconscious"] = True
        elif new_hp > 0:
            if "unconscious" in conditions:
                result["regained_consciousness"] = True
            conditions.discard("unconscious")
            character.death_saves_json = {"successes": 0, "failures": 0}
        character.conditions_json = sorted(conditions)
        result["hp"] = f"{character.hp_current}/{character.hp_max}"
        broadcast_character(ctx.campaign.id, character)

    elif target.kind == "npc":
        npc: NPC = row
        stat_hp = (npc.stat_block_json or {}).get("hp")
        max_hp = int(stat_hp) if stat_hp else None
        current = npc.hp_current if npc.hp_current is not None else (max_hp or 0)
        _record_inverse(
            ctx, "npc", npc.id, {"hp_current": npc.hp_current, "status": npc.status}
        )
        new_hp = current + delta
        if max_hp is not None:
            new_hp = min(new_hp, max_hp)
        npc.hp_current = max(0, new_hp)
        if npc.hp_current == 0 and delta < 0:
            npc.status = "dead"
            result["defeated"] = True
        result["hp"] = f"{npc.hp_current}/{max_hp or '?'}"
        # Keep this NPC's initiative-tracker entry in step, or the encounter
        # would still count them as standing (and show stale HP) after they
        # drop — the name resolver prefers the NPC row over its combatant.
        await _sync_npc_combatant(ctx, npc)

    else:  # combatant (monster instance)
        combatant: Combatant = row
        _record_inverse(
            ctx,
            "combatant",
            combatant.id,
            {"hp_current": combatant.hp_current, "defeated": combatant.defeated},
        )
        current = combatant.hp_current or 0
        new_hp = current + delta
        if combatant.hp_max is not None:
            new_hp = min(new_hp, combatant.hp_max)
        combatant.hp_current = max(0, new_hp)
        if combatant.hp_current == 0 and delta < 0:
            combatant.defeated = True
            result["defeated"] = True
        result["hp"] = f"{combatant.hp_current}/{combatant.hp_max or '?'}"
        # Mirror onto the persistent NPC row when this combatant wraps one.
        if combatant.ref_type == "npc" and combatant.ref_id:
            npc = await ctx.db.get(NPC, combatant.ref_id)
            if npc:
                npc.hp_current = combatant.hp_current
                if combatant.defeated and delta < 0:
                    npc.status = "dead"

    await ctx.db.commit()
    return result


async def set_condition(
    ctx: ToolContext, target: Resolved, condition: str, op: str
) -> dict[str, Any]:
    row = target.row
    condition = condition.lower().strip()
    if target.kind == "character":
        _record_inverse(
            ctx, "character", row.id, {"conditions_json": list(row.conditions_json)}
        )
    elif target.kind == "npc":
        _record_inverse(ctx, "npc", row.id, {"conditions_json": list(row.conditions_json)})
    else:
        _record_inverse(
            ctx, "combatant", row.id, {"conditions_json": list(row.conditions_json)}
        )

    conditions = set(row.conditions_json)
    if op == "add":
        conditions.add(condition)
    else:
        conditions.discard(condition)
    row.conditions_json = sorted(conditions)
    await ctx.db.commit()
    if target.kind == "character":
        broadcast_character(ctx.campaign.id, row)
    return {"target": target.name, "conditions": row.conditions_json}


async def award_xp(ctx: ToolContext, characters: list[Character], amount_each: int) -> dict[str, Any]:
    leveled: list[str] = []
    for character in characters:
        _record_inverse(ctx, "character", character.id, {"xp": character.xp})
        character.xp += amount_each
        new_level = level_for_xp(character.xp)
        if new_level > character.level:
            leveled.append(f"{character.name} can advance to level {new_level}")
        broadcast_character(ctx.campaign.id, character)
    await ctx.db.commit()
    return {
        "xp_each": amount_each,
        "recipients": [c.name for c in characters],
        "level_ups_available": leveled,
    }


async def use_resource(
    ctx: ToolContext, character: Character, resource: str, level_or_name: str, op: str
) -> dict[str, Any]:
    if resource == "spell_slot":
        slots = dict(character.spell_slots_json)
        slot = slots.get(str(level_or_name))
        if not slot:
            available = [lvl for lvl, s in slots.items() if s["max"] > s["used"]]
            return {
                "error": f"{character.name} has no level-{level_or_name} slots. "
                f"Levels with free slots: {available or 'none'}"
            }
        if op == "spend":
            if slot["used"] >= slot["max"]:
                return {"error": f"No level-{level_or_name} slots remaining"}
            _record_inverse(
                ctx, "character", character.id,
                {"spell_slots_json": {k: dict(v) for k, v in character.spell_slots_json.items()}},
            )
            slot = {**slot, "used": slot["used"] + 1}
        else:
            _record_inverse(
                ctx, "character", character.id,
                {"spell_slots_json": {k: dict(v) for k, v in character.spell_slots_json.items()}},
            )
            slot = {**slot, "used": max(0, slot["used"] - 1)}
        slots[str(level_or_name)] = slot
        character.spell_slots_json = slots
        await ctx.db.commit()
        broadcast_character(ctx.campaign.id, character)
        return {
            "target": character.name,
            "slot_level": str(level_or_name),
            "remaining": slot["max"] - slot["used"],
        }

    # hit dice / feature charges live in resources_json
    resources = {k: dict(v) for k, v in character.resources_json.items()}
    entry = resources.get(level_or_name) or resources.get(resource)
    key = level_or_name if level_or_name in resources else resource
    if not entry:
        return {"error": f"Unknown resource '{level_or_name}' for {character.name}"}
    if op == "spend" and entry["used"] >= entry["max"]:
        return {"error": f"No {key} remaining"}
    _record_inverse(
        ctx, "character", character.id,
        {"resources_json": {k: dict(v) for k, v in character.resources_json.items()}},
    )
    entry["used"] = entry["used"] + 1 if op == "spend" else max(0, entry["used"] - 1)
    resources[key] = entry
    character.resources_json = resources
    await ctx.db.commit()
    broadcast_character(ctx.campaign.id, character)
    return {"target": character.name, "resource": key, "remaining": entry["max"] - entry["used"]}

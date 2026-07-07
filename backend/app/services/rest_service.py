"""Party rests (5E short/long), shared by the AI's rest tool and the DM's
rest button so both paths apply identical rules."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Campaign, Character, Scene
from app.services.messages import create_message


async def apply_rest(
    db: AsyncSession,
    campaign: Campaign,
    scene: Scene,
    kind: str,
    inverse_patches: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Rest the whole active party. Returns a per-character report; appends
    inverse patches (for AI-turn retcon) when a list is supplied."""
    characters = list(
        (
            await db.execute(
                select(Character).where(
                    Character.campaign_id == campaign.id, Character.status == "active"
                )
            )
        ).scalars()
    )
    report: list[str] = []
    for c in characters:
        if inverse_patches is not None:
            inverse_patches.append(
                {
                    "kind": "character",
                    "id": c.id,
                    "patch": {
                        "hp_current": c.hp_current,
                        "spell_slots_json": {k: dict(v) for k, v in c.spell_slots_json.items()},
                        "resources_json": {k: dict(v) for k, v in c.resources_json.items()},
                    },
                }
            )
        if kind == "long":
            c.hp_current = c.hp_max
            c.hp_temp = 0
            c.spell_slots_json = {
                lvl: {**slot, "used": 0} for lvl, slot in c.spell_slots_json.items()
            }
            resources = {k: dict(v) for k, v in c.resources_json.items()}
            hit_dice = resources.get("hit_dice")
            if hit_dice:  # regain half max hit dice (min 1)
                hit_dice["used"] = max(0, hit_dice["used"] - max(1, hit_dice["max"] // 2))
                resources["hit_dice"] = hit_dice
            c.resources_json = resources
            c.death_saves_json = {"successes": 0, "failures": 0}
            conditions = set(c.conditions_json)
            conditions.discard("unconscious")
            c.conditions_json = sorted(conditions)
            report.append(f"{c.name}: full HP, slots restored")
        else:
            report.append(f"{c.name}: may spend hit dice to heal")
        from app.services.bookkeeping import broadcast_character

        broadcast_character(campaign.id, c)
    await db.commit()
    await create_message(
        db, scene, author_type="system", kind="system",
        content=f"🌙 The party takes a {kind} rest.",
    )
    return report

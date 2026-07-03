"""Core AI DM tools: dice, HP, conditions, resources, inventory, awards,
SRD lookup, player prompts, DM escalation. World/combat tools land in Phase 6.
"""

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.ai.entity_resolver import ResolveMiss, resolve_target
from app.ai.tools.registry import ToolContext, ToolResult, tool
from app.models import Character, SrdEntry
from app.realtime import events
from app.realtime.hub import hub
from app.services import bookkeeping, rules_5e
from app.services import dice as dice_service
from app.services.items import change_inventory
from app.services.messages import create_message, create_roll_message

COINS = {"cp", "sp", "ep", "gp", "pp"}


async def _active_characters(ctx: ToolContext) -> list[Character]:
    result = await ctx.db.execute(
        select(Character).where(
            Character.campaign_id == ctx.campaign.id, Character.status == "active"
        )
    )
    return list(result.scalars())


def _sheet_modifier(character: Character, kind: str, ability_or_skill: str | None) -> tuple[int, str]:
    """Compute the correct d20 modifier from the sheet. Returns (mod, explanation)."""
    scores = character.ability_scores_json
    profs = character.proficiencies_json
    prof_bonus = rules_5e.proficiency_bonus(character.level)
    name = (ability_or_skill or "").lower().strip()

    if kind == "initiative":
        mod = rules_5e.ability_modifier(scores.get("dex", 10))
        return mod, f"DEX {mod:+d}"

    if kind == "save":
        ability = name if name in rules_5e.ABILITIES else "con"
        mod = rules_5e.ability_modifier(scores.get(ability, 10))
        note = f"{ability.upper()} {mod:+d}"
        if ability in [s.lower() for s in profs.get("saves", [])]:
            mod += prof_bonus
            note += f", prof {prof_bonus:+d}"
        return mod, note

    # checks: skill or bare ability
    if name in rules_5e.SKILLS:
        ability = rules_5e.SKILLS[name]
        mod = rules_5e.ability_modifier(scores.get(ability, 10))
        note = f"{ability.upper()} {mod:+d}"
        if name in [s.lower() for s in profs.get("skills", [])]:
            bonus = prof_bonus * (2 if name in [e.lower() for e in profs.get("expertise", [])] else 1)
            mod += bonus
            note += f", prof {bonus:+d}"
        return mod, note
    if name in rules_5e.ABILITIES:
        mod = rules_5e.ability_modifier(scores.get(name, 10))
        return mod, f"{name.upper()} {mod:+d}"
    return 0, "no modifier"


class RollDiceArgs(BaseModel):
    kind: Literal["check", "save", "attack", "damage", "initiative", "death_save", "raw"] = "raw"
    expression: str = Field(
        default="", description="Dice expression for damage/raw rolls, e.g. '2d6+3'"
    )
    roller: str = Field(default="", description="Who rolls: character/NPC name or id")
    ability_or_skill: str = Field(
        default="", description="For check/save: e.g. 'stealth', 'dex', 'wisdom'"
    )
    dc: int | None = Field(default=None, description="Difficulty class to compare against")
    advantage: Literal["none", "adv", "dis"] = "none"
    modifier: int | None = Field(
        default=None,
        description="Explicit bonus when the sheet can't provide it (e.g. monster attack +4)",
    )
    reason: str = Field(default="", description="What this roll is for, shown to players")


@tool(
    "roll_dice",
    "Roll dice server-side (NEVER invent results). d20 kinds (check/save/attack/"
    "initiative/death_save) use the roller's real sheet modifiers; damage/raw use "
    "'expression'. Returns total and success vs dc when given.",
    RollDiceArgs,
    mutating=True,
)
async def roll_dice(ctx: ToolContext, args: RollDiceArgs) -> ToolResult:
    detail: dict = {"reason": args.reason}
    roller_name = args.roller or "The DM"
    character: Character | None = None

    if args.roller:
        target = await resolve_target(ctx.db, ctx.campaign.id, args.roller, ctx.scene.id)
        if isinstance(target, ResolveMiss):
            if args.kind in ("check", "save", "death_save"):
                return ToolResult(ok=False, error=target.error())
        else:
            roller_name = target.name
            if isinstance(target.row, Character):
                character = target.row

    if args.kind in ("damage", "raw"):
        if not args.expression:
            return ToolResult(ok=False, error="expression is required for damage/raw rolls")
        try:
            result = dice_service.roll(args.expression)
        except dice_service.DiceError as e:
            return ToolResult(ok=False, error=str(e))
        msg, _ = await create_roll_message(
            ctx.db, ctx.scene, expression=args.expression, purpose=args.kind,
            roller_name=roller_name, author_type="ai", detail=detail, result=result,
        )
        return ToolResult(ok=True, data={"total": result.total, "rolls": result.rolls})

    # --- d20 rolls -------------------------------------------------------------
    face, faces = dice_service.roll_d20(args.advantage)
    if character is not None and args.kind in ("check", "save", "initiative"):
        mod, mod_note = _sheet_modifier(character, args.kind, args.ability_or_skill)
        if args.modifier:
            mod += args.modifier
            mod_note += f", extra {args.modifier:+d}"
    else:
        mod = args.modifier or 0
        mod_note = f"{mod:+d}"
    total = face + mod

    if args.kind == "death_save":
        mod, mod_note, total = 0, "flat", face

    detail.update(
        {
            "advantage": args.advantage,
            "faces": faces,
            "kind": args.kind,
            "skill": args.ability_or_skill,
            "modifier_note": mod_note,
        }
    )
    data: dict = {"total": total, "d20": face, "modifier": mod}
    if args.kind != "death_save" and args.dc is not None:
        outcome = "success" if total >= args.dc else "failure"
        detail["dc"] = args.dc
        detail["outcome"] = outcome
        data["outcome"] = outcome
    if args.kind == "attack":
        detail["crit"] = face == 20
        data["crit"] = face == 20
        if face == 1:
            data["outcome"] = "critical miss"
            detail["outcome"] = "critical miss"

    if args.kind == "death_save" and character is not None:
        saves = dict(character.death_saves_json or {"successes": 0, "failures": 0})
        if face == 20:
            character.hp_current = 1
            character.death_saves_json = {"successes": 0, "failures": 0}
            conditions = set(character.conditions_json)
            conditions.discard("unconscious")
            character.conditions_json = sorted(conditions)
            data["result"] = "natural 20 — regains 1 HP and consciousness!"
        else:
            if face == 1:
                saves["failures"] = saves.get("failures", 0) + 2
            elif face >= 10:
                saves["successes"] = saves.get("successes", 0) + 1
            else:
                saves["failures"] = saves.get("failures", 0) + 1
            if saves.get("failures", 0) >= 3:
                character.status = "dead"
                data["result"] = "three failures — the character dies"
            elif saves.get("successes", 0) >= 3:
                saves = {"successes": 0, "failures": 0}
                data["result"] = "three successes — stable at 0 HP"
            character.death_saves_json = saves
            data["death_saves"] = saves
        await ctx.db.commit()
        bookkeeping.broadcast_character(ctx.campaign.id, character)

    expression = "2d20" + ("kh1" if args.advantage == "adv" else "kl1") if args.advantage != "none" else "1d20"
    synthetic = dice_service.DiceResult(
        expression=expression, rolls=faces, kept=[face], modifier=mod, total=total
    )
    await create_roll_message(
        ctx.db, ctx.scene, expression=expression, purpose=args.kind,
        roller_name=roller_name, author_type="ai",
        character_id=character.id if character else None,
        detail=detail, result=synthetic,
    )
    return ToolResult(ok=True, data=data)


class RequestPlayerRollArgs(BaseModel):
    character: str = Field(description="Character name or id who must roll")
    kind: Literal["check", "save"] = "check"
    ability_or_skill: str = Field(description="e.g. 'perception', 'dex', 'wisdom'")
    dc: int | None = None
    reason: str = ""


@tool(
    "request_player_roll",
    "Ask a player to make a check/save themselves (posts a clickable prompt). "
    "Prefer this over roll_dice for player characters in dramatic moments.",
    RequestPlayerRollArgs,
    mutating=True,
)
async def request_player_roll(ctx: ToolContext, args: RequestPlayerRollArgs) -> ToolResult:
    target = await resolve_target(ctx.db, ctx.campaign.id, args.character, ctx.scene.id)
    if isinstance(target, ResolveMiss):
        return ToolResult(ok=False, error=target.error())
    if not isinstance(target.row, Character):
        return ToolResult(ok=False, error=f"{target.name} is not a player character")

    await create_message(
        ctx.db,
        ctx.scene,
        author_type="ai",
        kind="system",
        content=f"**{target.name}**, make a {args.ability_or_skill} {args.kind}"
        + (f" (DC {args.dc})" if args.dc else "")
        + (f" — {args.reason}" if args.reason else ""),
        payload={
            "roll_request": {
                "character_id": target.row.id,
                "kind": args.kind,
                "ability_or_skill": args.ability_or_skill,
                "dc": args.dc,
            }
        },
    )
    return ToolResult(
        ok=True,
        data={"requested": f"{args.ability_or_skill} {args.kind} from {target.name}"},
    )


class UpdateHpArgs(BaseModel):
    target: str = Field(description="Character/NPC/combatant name or id")
    delta: int = Field(description="Negative = damage, positive = healing")
    reason: str = ""


@tool(
    "update_hp",
    "Apply damage (negative delta) or healing (positive). Handles temp HP, "
    "clamping, unconsciousness and death automatically.",
    UpdateHpArgs,
    mutating=True,
)
async def update_hp(ctx: ToolContext, args: UpdateHpArgs) -> ToolResult:
    target = await resolve_target(ctx.db, ctx.campaign.id, args.target, ctx.scene.id)
    if isinstance(target, ResolveMiss):
        return ToolResult(ok=False, error=target.error())
    result = await bookkeeping.apply_hp_change(ctx, target, args.delta, args.reason)
    verb = "takes" if args.delta < 0 else "recovers"
    note = f"{target.name} {verb} {abs(args.delta)} {'damage' if args.delta < 0 else 'HP'} ({result['hp']})"
    return ToolResult(ok=True, data=result, public_note=note)


class UpdateConditionArgs(BaseModel):
    target: str
    condition: str = Field(description="5E condition, e.g. prone, poisoned, frightened")
    op: Literal["add", "remove"] = "add"


@tool(
    "update_condition",
    "Add or remove a condition (prone, poisoned, restrained, …) on a target.",
    UpdateConditionArgs,
    mutating=True,
)
async def update_condition(ctx: ToolContext, args: UpdateConditionArgs) -> ToolResult:
    target = await resolve_target(ctx.db, ctx.campaign.id, args.target, ctx.scene.id)
    if isinstance(target, ResolveMiss):
        return ToolResult(ok=False, error=target.error())
    result = await bookkeeping.set_condition(ctx, target, args.condition, args.op)
    return ToolResult(ok=True, data=result)


class UseResourceArgs(BaseModel):
    character: str
    resource: Literal["spell_slot", "hit_dice", "feature"] = "spell_slot"
    level_or_name: str = Field(description="Slot level ('1'-'9') or resource name")
    op: Literal["spend", "restore"] = "spend"


@tool(
    "use_resource",
    "Spend or restore a spell slot, hit die, or feature charge. Rejects illegal "
    "spends (no slot available).",
    UseResourceArgs,
    mutating=True,
)
async def use_resource(ctx: ToolContext, args: UseResourceArgs) -> ToolResult:
    target = await resolve_target(ctx.db, ctx.campaign.id, args.character, ctx.scene.id)
    if isinstance(target, ResolveMiss):
        return ToolResult(ok=False, error=target.error())
    if not isinstance(target.row, Character):
        return ToolResult(ok=False, error="Resources are tracked for player characters only")
    result = await bookkeeping.use_resource(
        ctx, target.row, args.resource, args.level_or_name, args.op
    )
    if "error" in result:
        return ToolResult(ok=False, error=result["error"])
    return ToolResult(ok=True, data=result)


class ModifyInventoryArgs(BaseModel):
    target: str = Field(description="Character name or id")
    item: str = Field(description="Item name, or coin type (cp/sp/ep/gp/pp) for money")
    quantity: int = Field(default=1, ge=1)
    op: Literal["add", "remove"] = "add"
    description: str = Field(default="", description="Item description if it's new")


@tool(
    "modify_inventory",
    "Give or take items or coins. item='gp' with quantity=10 handles money.",
    ModifyInventoryArgs,
    mutating=True,
)
async def modify_inventory(ctx: ToolContext, args: ModifyInventoryArgs) -> ToolResult:
    target = await resolve_target(ctx.db, ctx.campaign.id, args.target, ctx.scene.id)
    if isinstance(target, ResolveMiss):
        return ToolResult(ok=False, error=target.error())
    if not isinstance(target.row, Character):
        return ToolResult(ok=False, error="Inventory tools currently target player characters")
    character: Character = target.row
    delta = args.quantity if args.op == "add" else -args.quantity

    if args.item.lower() in COINS:
        coin = args.item.lower()
        currency = dict(character.currency_json)
        current = currency.get(coin, 0)
        if current + delta < 0:
            return ToolResult(ok=False, error=f"{character.name} only has {current} {coin}")
        ctx.inverse_patches.append(
            {"kind": "character", "id": character.id, "patch": {"currency_json": dict(character.currency_json)}}
        )
        currency[coin] = current + delta
        character.currency_json = currency
        await ctx.db.commit()
        bookkeeping.broadcast_character(ctx.campaign.id, character)
        return ToolResult(
            ok=True,
            data={"target": character.name, "coin": coin, "balance": currency[coin]},
            public_note=f"{character.name} {'gains' if delta > 0 else 'spends'} {abs(delta)} {coin}",
        )

    result = await change_inventory(
        ctx.db, ctx.campaign.id, "character", character.id, args.item, delta, args.description
    )
    if "error" in result:
        await ctx.db.rollback()
        return ToolResult(ok=False, error=result["error"])
    ctx.inverse_patches.append(
        {
            "kind": "inventory",
            "id": character.id,
            "patch": {"item": result["item"], "quantity": result["prior_quantity"]},
        }
    )
    await ctx.db.commit()
    hub.broadcast(
        ctx.campaign.id,
        events.make_event(
            events.INVENTORY_UPDATED, ctx.campaign.id, {"character_id": character.id}
        ),
    )
    verb = "receives" if delta > 0 else "loses"
    return ToolResult(
        ok=True,
        data=result,
        public_note=f"{character.name} {verb} {args.quantity}x {result['item']}",
    )


class AwardArgs(BaseModel):
    xp_each: int = Field(default=0, ge=0, description="XP for each recipient")
    recipients: str = Field(
        default="party", description="'party' or comma-separated character names"
    )
    reason: str = ""


@tool(
    "award",
    "Award XP to the party or named characters. Flags available level-ups.",
    AwardArgs,
    mutating=True,
    gated=True,
)
async def award(ctx: ToolContext, args: AwardArgs) -> ToolResult:
    if args.xp_each <= 0:
        return ToolResult(ok=False, error="xp_each must be positive")
    if args.recipients.strip().lower() == "party":
        characters = await _active_characters(ctx)
    else:
        characters = []
        for ref in args.recipients.split(","):
            target = await resolve_target(ctx.db, ctx.campaign.id, ref.strip(), ctx.scene.id)
            if isinstance(target, ResolveMiss):
                return ToolResult(ok=False, error=target.error())
            if isinstance(target.row, Character):
                characters.append(target.row)
    if not characters:
        return ToolResult(ok=False, error="No characters to award XP to")

    result = await bookkeeping.award_xp(ctx, characters, args.xp_each)
    names = ", ".join(c.name for c in characters)
    await create_message(
        ctx.db,
        ctx.scene,
        author_type="system",
        kind="system",
        content=f"✨ {names} gain{'s' if len(characters) == 1 else ''} {args.xp_each} XP"
        + (f" — {args.reason}" if args.reason else ""),
    )
    return ToolResult(ok=True, data=result)


class LookupArgs(BaseModel):
    query: str = Field(description="What to look up")
    kind: Literal["rule", "spell", "monster", "equipment", "magic-item", "condition"] = "rule"


@tool(
    "lookup",
    "Look up official 5E rules, spells, monsters, items, or conditions. Use "
    "before adjudicating anything you're unsure about.",
    LookupArgs,
)
async def lookup(ctx: ToolContext, args: LookupArgs) -> ToolResult:
    query = args.query.strip()
    result = await ctx.db.execute(
        select(SrdEntry)
        .where(SrdEntry.kind == args.kind, SrdEntry.name.ilike(f"%{query}%"))
        .limit(3)
    )
    entries = list(result.scalars())
    if not entries:
        words = [w for w in query.split() if len(w) > 3]
        if words:
            result = await ctx.db.execute(
                select(SrdEntry)
                .where(SrdEntry.kind == args.kind, SrdEntry.name.ilike(f"%{words[0]}%"))
                .limit(3)
            )
            entries = list(result.scalars())
    if not entries and args.kind == "rule":
        # search rule descriptions too
        result = await ctx.db.execute(
            select(SrdEntry)
            .where(SrdEntry.kind == "rule")
            .limit(200)
        )
        lowered = query.lower()
        entries = [
            e
            for e in result.scalars()
            if lowered in str(e.data_json.get("description", "")).lower()
        ][:2]
    if not entries:
        return ToolResult(ok=False, error=f"No SRD {args.kind} matching '{query}'")

    def compact(entry: SrdEntry) -> dict:
        data = dict(entry.data_json)
        # keep payloads small for the model
        for key, value in list(data.items()):
            if isinstance(value, str) and len(value) > 1200:
                data[key] = value[:1200] + "…"
        return {"name": entry.name, **data}

    return ToolResult(ok=True, data={"results": [compact(e) for e in entries]})


class RequestDmArgs(BaseModel):
    question: str = Field(description="What you need the human DM to decide")


@tool(
    "request_dm",
    "Privately ask the human DM a question when a plot or ruling decision "
    "is above your pay grade. Continue narrating around the uncertainty.",
    RequestDmArgs,
    mutating=True,
)
async def request_dm(ctx: ToolContext, args: RequestDmArgs) -> ToolResult:
    await create_message(
        ctx.db,
        ctx.scene,
        author_type="ai",
        kind="whisper",
        content=f"🔮 **AI asks the DM:** {args.question}",
        visibility="dm",
    )
    hub.broadcast(
        ctx.campaign.id,
        events.make_event(
            events.DM_WHISPER,
            ctx.campaign.id,
            {"question": args.question, "scene_id": ctx.scene.id},
            ctx.scene.id,
        ),
        dm_only=True,
    )
    return ToolResult(ok=True, data={"sent": True})


class GetSheetArgs(BaseModel):
    character: str = Field(description="Character name or id")


@tool(
    "get_character_sheet",
    "Read a character's full current sheet (stats, HP, slots, inventory).",
    GetSheetArgs,
)
async def get_character_sheet(ctx: ToolContext, args: GetSheetArgs) -> ToolResult:
    target = await resolve_target(ctx.db, ctx.campaign.id, args.character, ctx.scene.id)
    if isinstance(target, ResolveMiss):
        return ToolResult(ok=False, error=target.error())
    if not isinstance(target.row, Character):
        return ToolResult(ok=False, error=f"{target.name} is not a player character")
    c: Character = target.row
    from app.models import InventoryEntry, Item

    inv = await ctx.db.execute(
        select(Item.name, InventoryEntry.quantity)
        .join(InventoryEntry, InventoryEntry.item_id == Item.id)
        .where(InventoryEntry.owner_type == "character", InventoryEntry.owner_id == c.id)
    )
    return ToolResult(
        ok=True,
        data={
            "name": c.name,
            "race": c.race,
            "class": c.klass,
            "level": c.level,
            "hp": f"{c.hp_current}/{c.hp_max}",
            "ac": c.ac,
            "abilities": c.ability_scores_json,
            "skills": c.proficiencies_json.get("skills", []),
            "saves": c.proficiencies_json.get("saves", []),
            "spell_slots": c.spell_slots_json,
            "conditions": c.conditions_json,
            "currency": c.currency_json,
            "inventory": [{"item": n, "qty": q} for n, q in inv.all()],
            "xp": c.xp,
        },
    )

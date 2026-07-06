"""World, quest, combat, rest, and scene-control tools for the AI DM."""

from typing import Any, Literal

from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process, utils
from sqlalchemy import select, text

from app.ai.tools.registry import ToolContext, ToolResult, tool
from app.models import NPC, Character, Faction, Location, Monster, Quest, SrdEntry, WorldEvent
from app.services import combat as combat_service
from app.services import rules_5e
from app.services.messages import create_message


async def _find_by_name(db, model, campaign_id: str, name: str):
    rows = list(
        (
            await db.execute(select(model).where(model.campaign_id == campaign_id))
        ).scalars()
    )
    lowered = name.lower().strip()
    key = "title" if model is Quest else "name"
    for row in rows:
        if getattr(row, key).lower() == lowered:
            return row
    names = {i: getattr(r, key) for i, r in enumerate(rows)}
    if names:
        best = process.extractOne(
            name, names, scorer=fuzz.WRatio, processor=utils.default_process, score_cutoff=88
        )
        if best:
            return rows[best[2]]
    return None


class UpsertEntityArgs(BaseModel):
    kind: Literal["npc", "monster", "location", "faction"]
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    # npc extras
    role: str = Field(default="", description="NPC occupation/narrative role")
    disposition: str = Field(default="", description="NPC attitude: friendly/neutral/hostile…")
    secrets: str = Field(default="", description="DM-only secret notes, hidden from players")
    srd_monster: str = Field(
        default="", description="For monsters/NPCs with stats: SRD monster to clone (e.g. 'goblin')"
    )
    # location extras
    location_kind: Literal[
        "", "world", "region", "settlement", "dungeon", "building", "room", "wilderness"
    ] = ""
    parent_location: str = Field(default="", description="Name of the parent location")
    # faction extras
    goals: str = ""


@tool(
    "upsert_entity",
    "Create or update a persistent world entity (NPC, monster, location, "
    "faction). Everything you invent that players might meet again MUST be "
    "saved this way. Set srd_monster to give it real combat stats.",
    UpsertEntityArgs,
    mutating=True,
    gated=True,
)
async def upsert_entity(ctx: ToolContext, args: UpsertEntityArgs) -> ToolResult:
    db, campaign_id = ctx.db, ctx.campaign.id

    stat_block: dict[str, Any] | None = None
    if args.srd_monster:
        srd = (
            await db.execute(
                select(SrdEntry).where(
                    SrdEntry.kind == "monster",
                    (SrdEntry.slug == args.srd_monster.lower().replace(" ", "-"))
                    | (SrdEntry.name.ilike(args.srd_monster)),
                )
            )
        ).scalars().first()
        if srd:
            stat_block = dict(srd.data_json)
        else:
            return ToolResult(ok=False, error=f"No SRD monster '{args.srd_monster}'")

    if args.kind == "npc":
        row = await _find_by_name(db, NPC, campaign_id, args.name)
        created = row is None
        if created:
            row = NPC(campaign_id=campaign_id, name=args.name, created_by="ai")
            db.add(row)
        ctx.inverse_patches.append(
            {"kind": "npc", "id": getattr(row, "id", None), "patch": {"_created": created}}
        )
        if args.description:
            row.description = args.description
        if args.role:
            row.role = args.role
        if args.disposition:
            row.disposition = args.disposition
        if args.secrets:
            row.secrets = (row.secrets + "\n" if row.secrets else "") + args.secrets
        if stat_block:
            row.stat_block_json = stat_block
            row.hp_current = int(stat_block.get("hp", 10))
        elif created and not row.stat_block_json:
            # A freshly-invented NPC with no stats still needs a defined HP, or
            # damaging it later reads as "0/?". Seed a modest commoner block;
            # the AI can flesh it out with srd_monster if it becomes a real foe.
            row.stat_block_json = {"hp": 8, "ac": 12, "cr": "0"}
            row.hp_current = 8
        if args.parent_location:
            loc = await _find_by_name(db, Location, campaign_id, args.parent_location)
            if loc:
                row.location_id = loc.id
    elif args.kind == "monster":
        row = await _find_by_name(db, Monster, campaign_id, args.name)
        created = row is None
        if created:
            row = Monster(campaign_id=campaign_id, name=args.name, source="ai")
            db.add(row)
        if args.description:
            row.description = args.description
        if stat_block:
            row.stat_block_json = stat_block
            row.cr = str(stat_block.get("cr", "0"))
    elif args.kind == "location":
        row = await _find_by_name(db, Location, campaign_id, args.name)
        created = row is None
        if created:
            row = Location(campaign_id=campaign_id, name=args.name, created_by="ai")
            db.add(row)
        if args.description:
            row.description = args.description
        if args.location_kind:
            row.kind = args.location_kind
        if args.parent_location:
            parent = await _find_by_name(db, Location, campaign_id, args.parent_location)
            if parent:
                row.parent_id = parent.id
    else:  # faction
        row = await _find_by_name(db, Faction, campaign_id, args.name)
        created = row is None
        if created:
            row = Faction(campaign_id=campaign_id, name=args.name, created_by="ai")
            db.add(row)
        if args.description:
            row.description = args.description
        if args.goals:
            row.goals = args.goals

    await db.commit()
    from app.api.world import broadcast_world_change

    broadcast_world_change(campaign_id, args.kind, row.id)
    return ToolResult(
        ok=True,
        data={"id": row.id, "created": created, "kind": args.kind, "name": args.name},
        public_note=(f"✨ New {args.kind}: {args.name}" if created else ""),
    )


class UpdateQuestArgs(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    op: Literal["create", "advance", "complete", "fail"] = "create"
    summary: str = ""
    objective: str = Field(default="", description="Objective to add (create/advance)")
    complete_objective: str = Field(default="", description="Objective text to mark done")


@tool(
    "update_quest",
    "Create a quest or update its progress. Keeps the party's quest log current.",
    UpdateQuestArgs,
    mutating=True,
    gated=True,
)
async def update_quest(ctx: ToolContext, args: UpdateQuestArgs) -> ToolResult:
    db, campaign_id = ctx.db, ctx.campaign.id
    quest = await _find_by_name(db, Quest, campaign_id, args.title)
    created = False
    if quest is None:
        if args.op != "create":
            return ToolResult(ok=False, error=f"No quest titled '{args.title}' to {args.op}")
        quest = Quest(
            campaign_id=campaign_id, title=args.title, status="active",
            scene_id=ctx.scene.id, created_by="ai",
        )
        db.add(quest)
        created = True

    if args.summary:
        quest.summary = args.summary
    objectives = [dict(o) for o in (quest.objectives_json or [])]
    if args.objective:
        objectives.append({"text": args.objective, "done": False})
    if args.complete_objective:
        matched = False
        for objective in objectives:
            if fuzz.WRatio(objective["text"], args.complete_objective) > 80:
                objective["done"] = True
                matched = True
        if not matched:
            return ToolResult(
                ok=False,
                error=f"No objective like '{args.complete_objective}'. "
                f"Current: {[o['text'] for o in objectives]}",
            )
    quest.objectives_json = objectives
    if args.op == "complete":
        quest.status = "completed"
    elif args.op == "fail":
        quest.status = "failed"
    elif quest.status == "rumored":
        quest.status = "active"
    await db.commit()

    from app.realtime import events
    from app.realtime.hub import hub

    hub.broadcast(
        campaign_id,
        events.make_event(
            events.QUEST_UPDATED, campaign_id,
            {"id": quest.id, "title": quest.title, "status": quest.status},
        ),
    )
    note = f"📜 Quest {'started' if created else args.op}: {quest.title}"
    return ToolResult(
        ok=True,
        data={"id": quest.id, "status": quest.status, "objectives": quest.objectives_json},
        public_note=note if (created or args.op in ("complete", "fail")) else "",
    )


class LogWorldEventArgs(BaseModel):
    description: str = Field(
        min_length=5, description="One or two sentences of what happened, past tense"
    )
    world_relevant: bool = Field(
        default=True, description="False for minor local color other scenes needn't know"
    )


@tool(
    "log_world_event",
    "Record a lasting consequence in the campaign continuity log ('the party "
    "burned the mill'). Other scenes and future sessions will remember it.",
    LogWorldEventArgs,
    mutating=True,
)
async def log_world_event(ctx: ToolContext, args: LogWorldEventArgs) -> ToolResult:
    event = WorldEvent(
        campaign_id=ctx.campaign.id,
        scene_id=ctx.scene.id,
        description=args.description.strip(),
        world_visibility=args.world_relevant,
    )
    ctx.db.add(event)
    await ctx.db.commit()
    return ToolResult(ok=True, data={"logged": True})


class StartCombatArgs(BaseModel):
    participants: list[str] = Field(
        min_length=1,
        description="Character/NPC names and/or SRD monsters, e.g. ['Mira', 'goblin x3']",
    )
    allow_deadly: bool = Field(
        default=False,
        description="Confirm an encounter at/over the party's DEADLY XP budget. "
        "Only when the story truly demands a potentially lethal fight.",
    )


@tool(
    "start_combat",
    "Begin combat: server rolls initiative for everyone and creates the turn "
    "tracker. Monsters get real SRD stats. List ALL combatants in one call. "
    "Encounters at/over the party's deadly XP budget are rejected unless "
    "allow_deadly=true.",
    StartCombatArgs,
    mutating=True,
)
async def start_combat(ctx: ToolContext, args: StartCombatArgs) -> ToolResult:
    try:
        snapshot = await combat_service.start_encounter(
            ctx.db, ctx.scene, args.participants, enforce_budget=not args.allow_deadly
        )
    except combat_service.CombatError as e:
        return ToolResult(ok=False, error=str(e))
    order = [
        f"{c['name']} ({c['initiative']})" for c in snapshot["combatants"]
    ]
    await create_message(
        ctx.db, ctx.scene, author_type="system", kind="system",
        content="⚔️ **Combat begins!** Initiative: " + ", ".join(order),
    )
    return ToolResult(
        ok=True,
        data={
            "order": order,
            "first_up": snapshot["combatants"][0]["name"] if snapshot["combatants"] else None,
        },
    )


class AdvanceCombatArgs(BaseModel):
    op: Literal["next_turn", "end_combat", "remove"] = "next_turn"
    target: str = Field(
        default="",
        description="For op='remove': the combatant who fled, surrendered, or "
        "stood down — they leave the fight without being killed.",
    )


@tool(
    "advance_combat",
    "Move to the next combatant's turn, remove a combatant who fled or "
    "surrendered (op='remove', target=name), or end the encounter. Ending is "
    "refused while foes are still up — defeat or remove them first.",
    AdvanceCombatArgs,
    mutating=True,
)
async def advance_combat(ctx: ToolContext, args: AdvanceCombatArgs) -> ToolResult:
    try:
        if args.op == "end_combat":
            await combat_service.end_encounter(ctx.db, ctx.scene)
            await create_message(
                ctx.db, ctx.scene, author_type="system", kind="system",
                content="🕊️ **Combat ends.**",
            )
            return ToolResult(ok=True, data={"ended": True})
        if args.op == "remove":
            if not args.target:
                return ToolResult(ok=False, error="op='remove' needs target=<combatant name>")
            snapshot = await combat_service.remove_combatant(ctx.db, ctx.scene, args.target)
        else:
            snapshot = await combat_service.advance_turn(ctx.db, ctx.scene)
    except combat_service.CombatError as e:
        return ToolResult(ok=False, error=str(e))
    active = next(
        (
            c
            for c in snapshot["combatants"]
            if c["id"] == snapshot["encounter"]["active_combatant_id"]
        ),
        None,
    )
    return ToolResult(
        ok=True,
        data={
            "round": snapshot["encounter"]["round"],
            "now_up": active["name"] if active else None,
        },
    )


class RestArgs(BaseModel):
    kind: Literal["short", "long"] = "long"


@tool(
    "rest",
    "Apply a short or long rest to the whole party per 5E rules (HP, hit "
    "dice, spell slots).",
    RestArgs,
    mutating=True,
)
async def rest(ctx: ToolContext, args: RestArgs) -> ToolResult:
    characters = list(
        (
            await ctx.db.execute(
                select(Character).where(
                    Character.campaign_id == ctx.campaign.id, Character.status == "active"
                )
            )
        ).scalars()
    )
    report = []
    for c in characters:
        ctx.inverse_patches.append(
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
        if args.kind == "long":
            c.hp_current = c.hp_max
            c.hp_temp = 0
            c.spell_slots_json = {
                lvl: {**slot, "used": 0} for lvl, slot in c.spell_slots_json.items()
            }
            resources = {k: dict(v) for k, v in c.resources_json.items()}
            hd = resources.get("hit_dice")
            if hd:  # regain half max hit dice (min 1)
                hd["used"] = max(0, hd["used"] - max(1, hd["max"] // 2))
                resources["hit_dice"] = hd
            c.resources_json = resources
            c.death_saves_json = {"successes": 0, "failures": 0}
            conditions = set(c.conditions_json)
            conditions.discard("unconscious")
            c.conditions_json = sorted(conditions)
            report.append(f"{c.name}: full HP, slots restored")
        else:
            report.append(f"{c.name}: may spend hit dice to heal")
        from app.services.bookkeeping import broadcast_character

        broadcast_character(ctx.campaign.id, c)
    await ctx.db.commit()
    await create_message(
        ctx.db, ctx.scene, author_type="system", kind="system",
        content=f"🌙 The party takes a {args.kind} rest.",
    )
    return ToolResult(ok=True, data={"kind": args.kind, "party": report})


class SceneControlArgs(BaseModel):
    op: Literal["end_scene", "advance_time", "set_location"]
    time: str = Field(default="", description="e.g. 'next morning', 'Day 12, dusk'")
    location: str = Field(default="", description="Location name for set_location")
    summary_hint: str = Field(default="", description="Key beats to remember from this scene")


@tool(
    "scene_control",
    "End the scene (writes a recap), advance the world clock, or move the "
    "party to a saved location.",
    SceneControlArgs,
    mutating=True,
    gated=True,
)
async def scene_control(ctx: ToolContext, args: SceneControlArgs) -> ToolResult:
    if args.op == "advance_time":
        if not args.time:
            return ToolResult(ok=False, error="time is required for advance_time")
        ctx.campaign.world_clock = args.time
        await ctx.db.commit()
        return ToolResult(ok=True, data={"world_clock": args.time})

    if args.op == "set_location":
        loc = await _find_by_name(ctx.db, Location, ctx.campaign.id, args.location)
        if not loc:
            return ToolResult(
                ok=False,
                error=f"No saved location '{args.location}' — create it with upsert_entity first",
            )
        ctx.scene.location_id = loc.id
        await ctx.db.commit()
        return ToolResult(ok=True, data={"scene_location": loc.name})

    # end_scene
    ctx.scene.status = "idle"
    await ctx.db.commit()
    from app.ai.memory import summarize_scene

    await summarize_scene(ctx.db, ctx.campaign, ctx.scene, hint=args.summary_hint)
    await create_message(
        ctx.db, ctx.scene, author_type="system", kind="system",
        content="🎬 **The scene draws to a close.**",
    )
    return ToolResult(ok=True, data={"scene_ended": True})


class PinFactArgs(BaseModel):
    fact: str = Field(
        min_length=3, max_length=300, description="Short, always-true campaign fact"
    )
    op: Literal["pin", "unpin"] = "pin"


@tool(
    "pin_fact",
    "Pin a permanent campaign fact that must never be forgotten or "
    "contradicted ('The mayor is secretly a dragon'). Pinned facts appear in "
    "every future prompt. Use op=unpin to retire one.",
    PinFactArgs,
    mutating=True,
    gated=True,
)
async def pin_fact(ctx: ToolContext, args: PinFactArgs) -> ToolResult:
    settings = dict(ctx.campaign.settings_json or {})
    facts = [str(f) for f in settings.get("pinned_facts") or []]
    ctx.inverse_patches.append(
        {
            "kind": "campaign",
            "id": ctx.campaign.id,
            "patch": {"settings_json": {**settings, "pinned_facts": list(facts)}},
        }
    )
    fact = args.fact.strip()
    note = ""
    if args.op == "unpin":
        remaining = [f for f in facts if f.lower() != fact.lower()]
        if len(remaining) == len(facts):
            return ToolResult(
                ok=False, error=f"No pinned fact matching '{fact}'. Pinned: {facts}"
            )
        facts = remaining
    else:
        if any(f.lower() == fact.lower() for f in facts):
            return ToolResult(ok=True, data={"pinned_facts": facts, "note": "already pinned"})
        facts.append(fact)
        note = f"📌 Pinned: {fact}"
    settings["pinned_facts"] = facts
    ctx.campaign.settings_json = settings
    await ctx.db.commit()
    return ToolResult(ok=True, data={"pinned_facts": facts}, public_note=note)


class LoreArgs(BaseModel):
    query: str = Field(description="What campaign history/lore to recall")


@tool(
    "recall_lore",
    "Search this campaign's own history: past events, known NPCs, locations, "
    "factions, quests. Use when players reference something from earlier play.",
    LoreArgs,
)
async def recall_lore(ctx: ToolContext, args: LoreArgs) -> ToolResult:
    db, campaign_id = ctx.db, ctx.campaign.id
    results: list[str] = []

    import re

    terms = re.findall(r"[A-Za-z0-9]+", args.query)
    if terms:
        fts = " OR ".join(f'"{t}"' for t in terms[:10])
        rows = await db.execute(
            text(
                "SELECT w.description FROM world_events_fts f "
                "JOIN world_events w ON w.rowid = f.rowid "
                "WHERE world_events_fts MATCH :q AND w.campaign_id = :cid "
                "ORDER BY rank LIMIT 6"
            ),
            {"q": fts, "cid": campaign_id},
        )
        results.extend(f"[event] {r[0]}" for r in rows.fetchall())

    lowered = args.query.lower()
    for model, kind, fields in (
        (NPC, "npc", ("role", "disposition", "description")),
        (Location, "location", ("kind", "description")),
        (Faction, "faction", ("description", "goals")),
        (Quest, "quest", ("status", "summary")),
    ):
        rows = list(
            (await db.execute(select(model).where(model.campaign_id == campaign_id))).scalars()
        )
        for row in rows:
            name = getattr(row, "title", None) or getattr(row, "name", "")
            if name and (
                name.lower() in lowered
                or any(t.lower() in name.lower() for t in terms if len(t) > 3)
            ):
                detail = "; ".join(
                    f"{f}: {getattr(row, f)}" for f in fields if getattr(row, f, "")
                )
                results.append(f"[{kind}] {name} — {detail[:400]}")

    if not results:
        return ToolResult(ok=False, error=f"Nothing in the campaign records about '{args.query}'")
    return ToolResult(ok=True, data={"results": results[:10]})


class SuggestEncounterArgs(BaseModel):
    difficulty: Literal["easy", "medium", "hard", "deadly"] = "medium"
    environment: str = Field(default="", description="Filter by monster type/theme, e.g. 'undead'")


@tool(
    "suggest_encounter",
    "Get a balanced encounter suggestion for the current party using DMG XP "
    "budgets and real SRD monsters. Then use start_combat to run it.",
    SuggestEncounterArgs,
)
async def suggest_encounter(ctx: ToolContext, args: SuggestEncounterArgs) -> ToolResult:
    characters = list(
        (
            await ctx.db.execute(
                select(Character).where(
                    Character.campaign_id == ctx.campaign.id, Character.status == "active"
                )
            )
        ).scalars()
    )
    if not characters:
        return ToolResult(ok=False, error="No active party members")

    budget = sum(
        rules_5e.ENCOUNTER_THRESHOLDS[min(c.level, 20)][args.difficulty] for c in characters
    )
    monsters = list(
        (await ctx.db.execute(select(SrdEntry).where(SrdEntry.kind == "monster"))).scalars()
    )
    if args.environment:
        env = args.environment.lower()
        filtered = [
            m
            for m in monsters
            if env in str(m.data_json.get("type", "")).lower()
            or env in str(m.data_json.get("subtype", "")).lower()
            or env in m.name.lower()
        ]
        monsters = filtered or monsters

    options: list[dict[str, Any]] = []
    for m in monsters:
        xp = rules_5e.CR_TO_XP.get(str(m.data_json.get("cr", "0")), 0)
        if xp == 0:
            continue
        for count in (1, 2, 3, 4, 6, 8):
            adjusted = xp * count * rules_5e.encounter_multiplier(count)
            if 0.75 * budget <= adjusted <= 1.15 * budget:
                options.append(
                    {
                        "monsters": f"{m.name} x{count}",
                        "cr": m.data_json.get("cr"),
                        "adjusted_xp": int(adjusted),
                    }
                )
                break
    import secrets as pysecrets

    picks = [options[pysecrets.randbelow(len(options))] for _ in range(min(5, len(options)))]
    # dedupe
    seen: set[str] = set()
    unique = [p for p in picks if not (p["monsters"] in seen or seen.add(p["monsters"]))]
    if not unique:
        return ToolResult(ok=False, error="No suitable SRD monsters for that budget/filter")
    return ToolResult(
        ok=True,
        data={"xp_budget": budget, "party_size": len(characters), "options": unique},
    )

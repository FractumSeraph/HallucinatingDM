"""World entity, quest, combat, and lore tests (REST + AI tools)."""

from sqlalchemy import select

from app.ai.mock_provider import MockProvider
from app.ai.provider import Done, LLMConfig, TextDelta, ToolCall, set_provider


async def setup_game(client):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "dm@example.com", "password": "longenough", "display_name": "DM"},
    )
    campaign = (await client.post("/api/v1/campaigns", json={"name": "C"})).json()
    scene = (
        await client.post(
            f"/api/v1/campaigns/{campaign['id']}/scenes",
            json={"name": "Ambush", "kind": "main", "dm_mode": "ai"},
        )
    ).json()
    character = (
        await client.post(
            f"/api/v1/campaigns/{campaign['id']}/characters",
            json={
                "name": "Mira",
                "race": "elf",
                "subrace": "High Elf",
                "klass": "wizard",
                "background": "acolyte",
                "method": "standard",
                "base_scores": {"str": 8, "dex": 13, "con": 14, "int": 15, "wis": 12, "cha": 10},
                "skill_choices": ["arcana", "investigation"],
            },
        )
    ).json()
    return campaign, scene, character


def make_mock(script):
    mock = MockProvider(config=LLMConfig(provider="mock", toolcall_mode="native"))
    for turn in script:
        mock.queue_turn(turn)
    set_provider(mock)
    return mock


async def test_world_crud_and_visibility(app_client):
    campaign, scene, character = await setup_game(app_client)
    cid = campaign["id"]

    resp = await app_client.post(
        f"/api/v1/campaigns/{cid}/world/location",
        json={"fields": {"name": "Barrowdown", "kind": "settlement", "dm_notes": "cult HQ"}},
    )
    assert resp.status_code == 200
    loc = resp.json()

    resp = await app_client.post(
        f"/api/v1/campaigns/{cid}/world/npc",
        json={
            "fields": {
                "name": "Mayor Aldric",
                "role": "mayor",
                "secrets": "secretly a cultist",
                "location_id": loc["id"],
            }
        },
    )
    assert resp.status_code == 200

    resp = await app_client.post(
        f"/api/v1/campaigns/{cid}/world/quest",
        json={"fields": {"title": "Cleanse the Mill", "dm_notes": "the miller lies"}},
    )
    assert resp.status_code == 200

    # DM sees secrets
    world = (await app_client.get(f"/api/v1/campaigns/{cid}/world")).json()
    assert world["npcs"][0]["secrets"] == "secretly a cultist"
    assert world["locations"][0]["dm_notes"] == "cult HQ"

    # player does not
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "p@example.com", "password": "longenough", "display_name": "P"},
    )
    await app_client.post(
        "/api/v1/campaigns/join", json={"invite_code": campaign["invite_code"]}
    )
    world = (await app_client.get(f"/api/v1/campaigns/{cid}/world")).json()
    assert "secrets" not in world["npcs"][0]
    assert "dm_notes" not in world["locations"][0]
    assert world["monsters"] == []

    # players cannot create entities
    resp = await app_client.post(
        f"/api/v1/campaigns/{cid}/world/npc", json={"fields": {"name": "Hax"}}
    )
    assert resp.status_code == 403


async def test_combat_rest_flow(app_client):
    campaign, scene, character = await setup_game(app_client)

    resp = await app_client.post(
        f"/api/v1/scenes/{scene['id']}/combat",
        json={"participants": ["Mira", "goblin x2"]},
    )
    assert resp.status_code == 200, resp.text
    snapshot = resp.json()
    assert len(snapshot["combatants"]) == 3
    names = [c["name"] for c in snapshot["combatants"]]
    assert "Mira" in names and "Goblin 1" in names and "Goblin 2" in names
    # sorted by initiative
    inits = [c["initiative"] for c in snapshot["combatants"]]
    assert inits == sorted(inits, reverse=True)
    # goblins have real SRD hp; monster AC hidden in snapshot
    goblin = next(c for c in snapshot["combatants"] if c["name"] == "Goblin 1")
    assert goblin["hp_max"] == 7
    assert goblin["ac"] is None

    # next turn cycles and bumps the round when wrapping
    first_active = snapshot["encounter"]["active_combatant_id"]
    for _ in range(3):
        snapshot = (
            await app_client.post(f"/api/v1/scenes/{scene['id']}/combat/next-turn")
        ).json()
    assert snapshot["encounter"]["round"] == 2
    assert snapshot["encounter"]["active_combatant_id"] == first_active

    # a second encounter can't start while one is active
    resp = await app_client.post(
        f"/api/v1/scenes/{scene['id']}/combat", json={"participants": ["goblin"]}
    )
    assert resp.status_code == 400

    resp = await app_client.post(f"/api/v1/scenes/{scene['id']}/combat/end")
    assert resp.json()["encounter"] is None  # no active encounter remains

    # and a new encounter can start afterwards
    resp = await app_client.post(
        f"/api/v1/scenes/{scene['id']}/combat", json={"participants": ["goblin"]}
    )
    assert resp.status_code == 200


async def test_ai_world_tools(app_client):
    campaign, scene, character = await setup_game(app_client)
    cid = campaign["id"]

    make_mock(
        [
            [
                ToolCall(
                    id="c1",
                    name="upsert_entity",
                    arguments={
                        "kind": "npc",
                        "name": "Grizzelda the Fence",
                        "role": "black market dealer",
                        "disposition": "wary",
                        "description": "A hunched gnome with clever eyes.",
                        "secrets": "works for the Thieves' Guild",
                    },
                ),
                Done(),
            ],
            [
                ToolCall(
                    id="c2",
                    name="update_quest",
                    arguments={
                        "title": "Find the Stolen Idol",
                        "op": "create",
                        "summary": "Recover the jade idol from the docks.",
                        "objective": "Question Grizzelda",
                    },
                ),
                Done(),
            ],
            [
                ToolCall(
                    id="c3",
                    name="log_world_event",
                    arguments={"description": "The party met Grizzelda the Fence."},
                ),
                Done(),
            ],
            [TextDelta("Grizzelda eyes you warily."), Done()],
        ]
    )
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])

    world = (await app_client.get(f"/api/v1/campaigns/{cid}/world")).json()
    npc = next(n for n in world["npcs"] if n["name"] == "Grizzelda the Fence")
    assert npc["created_by"] == "ai"
    assert npc["secrets"] == "works for the Thieves' Guild"
    quest = next(q for q in world["quests"] if q["title"] == "Find the Stolen Idol")
    assert quest["status"] == "active"
    assert quest["objectives_json"] == [{"text": "Question Grizzelda", "done": False}]

    events = (await app_client.get(f"/api/v1/campaigns/{cid}/world-events")).json()
    assert any("Grizzelda" in e["description"] for e in events)
    set_provider(None)


async def test_ai_combat_and_lore_tools(app_client):
    campaign, scene, character = await setup_game(app_client)

    make_mock(
        [
            [
                ToolCall(
                    id="c1",
                    name="start_combat",
                    arguments={"participants": ["Mira", "wolf"]},
                ),
                Done(),
            ],
            [TextDelta("Steel flashes!"), Done()],
        ]
    )
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])

    snapshot = (await app_client.get(f"/api/v1/scenes/{scene['id']}/combat")).json()
    assert snapshot["encounter"]["status"] == "active"
    assert {c["name"] for c in snapshot["combatants"]} == {"Mira", "Wolf"}

    # damage a combatant monster through the shared update_hp tool
    make_mock(
        [
            [ToolCall(id="c2", name="update_hp", arguments={"target": "Wolf", "delta": -100}), Done()],
            [ToolCall(id="c3", name="advance_combat", arguments={"op": "end_combat"}), Done()],
            [TextDelta("The wolf falls."), Done()],
        ]
    )
    await run_turn(scene["id"])
    snapshot = (await app_client.get(f"/api/v1/scenes/{scene['id']}/combat")).json()
    assert snapshot["encounter"] is None or snapshot["encounter"]["status"] == "ended"
    set_provider(None)


async def test_recall_lore_tool(app_client):
    campaign, scene, character = await setup_game(app_client)

    import app.ai.tools.world_tools  # noqa: F401
    from app.ai.tools.registry import ToolContext, registry
    from app.db import get_sessionmaker
    from app.models import Campaign, Scene, WorldEvent

    async with get_sessionmaker()() as db:
        campaign_row = await db.get(Campaign, campaign["id"])
        scene_row = await db.get(Scene, scene["id"])
        db.add(
            WorldEvent(
                campaign_id=campaign["id"],
                scene_id=scene["id"],
                description="The party burned the mill in Barrowdown.",
            )
        )
        await db.commit()

        ctx = ToolContext(db=db, campaign=campaign_row, scene=scene_row)
        result = await registry.dispatch(ctx, "recall_lore", {"query": "what happened at the mill"})
        assert result.ok, result.error
        assert any("burned the mill" in r for r in result.data["results"])


async def test_statless_npc_gets_default_hp(app_client):
    """A freshly-invented NPC with no stat block still has a defined HP, so
    damaging it reads as e.g. '5/8' rather than the old '0/?'."""
    campaign, scene, character = await setup_game(app_client)

    import app.ai.tools.core_tools  # noqa: F401
    import app.ai.tools.world_tools  # noqa: F401
    from app.ai.tools.registry import ToolContext, registry
    from app.db import get_sessionmaker
    from app.models import NPC, Campaign, Scene

    async with get_sessionmaker()() as db:
        campaign_row = await db.get(Campaign, campaign["id"])
        scene_row = await db.get(Scene, scene["id"])
        ctx = ToolContext(db=db, campaign=campaign_row, scene=scene_row)

        created = await registry.dispatch(
            ctx, "upsert_entity", {"kind": "npc", "name": "Masked Robber"}
        )
        assert created.ok, created.error

        npc = (
            await db.execute(select(NPC).where(NPC.name == "Masked Robber"))
        ).scalars().first()
        assert npc.hp_current == 8
        assert (npc.stat_block_json or {}).get("hp") == 8

        hit = await registry.dispatch(
            ctx, "update_hp", {"target": "Masked Robber", "delta": -3}
        )
        assert hit.ok, hit.error
        assert "?" not in hit.public_note  # was "0/?" before the fix
        assert "5/8" in hit.public_note


async def test_suggest_encounter_budget(app_client):
    campaign, scene, character = await setup_game(app_client)

    import app.ai.tools.world_tools  # noqa: F401
    from app.ai.tools.registry import ToolContext, registry
    from app.db import get_sessionmaker
    from app.models import Campaign, Scene
    from app.services.rules_5e import CR_TO_XP, ENCOUNTER_THRESHOLDS, encounter_multiplier

    async with get_sessionmaker()() as db:
        campaign_row = await db.get(Campaign, campaign["id"])
        scene_row = await db.get(Scene, scene["id"])
        ctx = ToolContext(db=db, campaign=campaign_row, scene=scene_row)
        result = await registry.dispatch(
            ctx, "suggest_encounter", {"difficulty": "medium"}
        )
        assert result.ok, result.error
        budget = ENCOUNTER_THRESHOLDS[1]["medium"]  # single level-1 PC
        assert result.data["xp_budget"] == budget
        for option in result.data["options"]:
            name, _, count = option["monsters"].rpartition(" x")
            adjusted = (
                CR_TO_XP[str(option["cr"])] * int(count) * encounter_multiplier(int(count))
            )
            assert 0.75 * budget <= adjusted <= 1.15 * budget

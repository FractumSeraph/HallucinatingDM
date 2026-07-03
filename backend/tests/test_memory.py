"""Memory & context upgrade: campaign rollups, automatic recall, pinned facts,
party inventory in prompts, and summaries for human-run scenes."""

import asyncio

from sqlalchemy import select, text

from app.ai.mock_provider import MockProvider
from app.ai.provider import Done, LLMConfig, TextDelta, set_provider


async def setup_game(client, dm_mode="ai"):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "dm@example.com", "password": "longenough", "display_name": "DM"},
    )
    campaign = (await client.post("/api/v1/campaigns", json={"name": "C"})).json()
    scene = (
        await client.post(
            f"/api/v1/campaigns/{campaign['id']}/scenes",
            json={"name": "Ambush", "kind": "main", "dm_mode": dm_mode},
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


# --- M1: campaign "story so far" rollup --------------------------------------


async def test_campaign_rollup_after_five_scene_recaps(app_client):
    campaign, scene, _ = await setup_game(app_client)
    make_mock([[TextDelta("The heroes secured Barrowdown and owe Elder Rowan a favor."), Done()]])

    from app.ai.memory import maybe_rollup_campaign
    from app.db import get_sessionmaker
    from app.models import Campaign, Summary

    async with get_sessionmaker()() as db:
        for i in range(5):
            db.add(
                Summary(
                    campaign_id=campaign["id"], scope="scene", ref_id=scene["id"],
                    content=f"Recap {i}",
                )
            )
        await db.commit()
        row = await db.get(Campaign, campaign["id"])

        result = await maybe_rollup_campaign(db, row)
        assert result is not None
        assert "Rowan" in row.summary

        rollups = list(
            (
                await db.execute(
                    select(Summary).where(
                        Summary.campaign_id == campaign["id"], Summary.scope == "campaign"
                    )
                )
            ).scalars()
        )
        assert len(rollups) == 1

        # A second call needs five MORE scene recaps first: no-op.
        assert await maybe_rollup_campaign(db, row) is None
    set_provider(None)


async def test_scene_summary_triggers_campaign_rollup(app_client):
    campaign, scene, _ = await setup_game(app_client, dm_mode="human")
    for i in range(4):
        await app_client.post(
            f"/api/v1/scenes/{scene['id']}/messages",
            json={"content": f"We march on the watermill. ({i})"},
        )

    make_mock(
        [
            [TextDelta("The party marched on the watermill."), Done()],
            [TextDelta("Story so far: the watermill campaign."), Done()],
        ]
    )

    from app.ai.memory import summarize_scene
    from app.db import get_sessionmaker
    from app.models import Campaign, Scene, Summary

    async with get_sessionmaker()() as db:
        # 4 prior recaps + the one summarize_scene writes = 5 → rollup fires.
        for i in range(4):
            db.add(Summary(campaign_id=campaign["id"], scope="scene", content=f"Recap {i}"))
        await db.commit()
        c = await db.get(Campaign, campaign["id"])
        s = await db.get(Scene, scene["id"])
        out = await summarize_scene(db, c, s)
        assert out == "The party marched on the watermill."
        assert c.summary == "Story so far: the watermill campaign."
    set_provider(None)


async def test_recaps_endpoint(app_client):
    campaign, scene, _ = await setup_game(app_client)

    from app.db import get_sessionmaker
    from app.models import Campaign, Summary

    async with get_sessionmaker()() as db:
        c = await db.get(Campaign, campaign["id"])
        c.summary = "The story so far."
        for i in range(7):
            db.add(
                Summary(
                    campaign_id=campaign["id"], scope="scene", ref_id=scene["id"],
                    content=f"Recap {i}",
                )
            )
        await db.commit()

    resp = await app_client.get(f"/api/v1/campaigns/{campaign['id']}/recaps")
    assert resp.status_code == 200
    body = resp.json()
    assert body["campaign_summary"] == "The story so far."
    assert len(body["recaps"]) == 5
    assert all(r["scene_id"] == scene["id"] for r in body["recaps"])


# --- M2: automatic retrieval ---------------------------------------------------


async def test_auto_recall_and_prompt_injection(app_client):
    campaign, scene, _ = await setup_game(app_client)

    from app.ai.retrieval import auto_recall
    from app.db import get_sessionmaker
    from app.models import NPC, Scene, WorldEvent
    from app.services.messages import create_message

    async with get_sessionmaker()() as db:
        db.add(
            WorldEvent(
                campaign_id=campaign["id"],
                description="The party burned the watermill in Barrowdown.",
            )
        )
        db.add(
            NPC(
                campaign_id=campaign["id"], name="Elder Rowan", role="village elder",
                description="Keeper of Barrowdown's secrets.", created_by="dm",
            )
        )
        old_scene = Scene(
            campaign_id=campaign["id"], name="Prologue", status="idle", dm_mode="human"
        )
        db.add(old_scene)
        await db.commit()
        await create_message(
            db, old_scene, author_type="player",
            content="Elder Rowan promised us fifty gold for clearing the watermill.",
            broadcast=False,
        )

        hits = await auto_recall(
            db, campaign["id"], scene["id"],
            "what did Elder Rowan promise about the watermill?",
        )
        assert any(h.startswith("[event]") for h in hits)
        assert any(h.startswith("[said earlier]") for h in hits)
        assert any(h.startswith("[npc] Elder Rowan") for h in hits)

        # Retrieval happens automatically: a player message referencing old lore
        # puts a "Recalled" section into the very next turn's system prompt.
        current = await db.get(Scene, scene["id"])
        await create_message(
            db, current, author_type="player",
            content="I ask around town about the watermill.", broadcast=False,
        )

    mock = make_mock([[TextDelta("You recall the mill."), Done()]])
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])
    system = mock.calls[0].messages[0]["content"]
    assert "Recalled from earlier in the campaign" in system
    assert "burned the watermill" in system
    set_provider(None)


async def test_messages_fts_stays_in_sync(app_client):
    campaign, scene, _ = await setup_game(app_client, dm_mode="human")
    await app_client.post(
        f"/api/v1/scenes/{scene['id']}/messages",
        json={"content": "The gnome vanished behind the waterfall."},
    )

    from app.db import get_sessionmaker

    async with get_sessionmaker()() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT m.content FROM messages_fts f JOIN messages m ON m.rowid = f.rowid "
                    "WHERE messages_fts MATCH '\"waterfall\"'"
                )
            )
        ).fetchall()
        assert len(rows) == 1

        rowid = (
            await db.execute(
                text("SELECT rowid FROM messages WHERE content LIKE '%waterfall%'")
            )
        ).scalar_one()
        await db.execute(
            text("UPDATE messages SET content = 'The gnome reappeared.' WHERE rowid = :r"),
            {"r": rowid},
        )
        await db.commit()
        rows = (
            await db.execute(
                text("SELECT rowid FROM messages_fts WHERE messages_fts MATCH '\"waterfall\"'")
            )
        ).fetchall()
        assert rows == []


# --- M3: pinned facts ------------------------------------------------------------


async def test_pinned_facts_in_prompt_and_pin_tool(app_client):
    campaign, scene, _ = await setup_game(app_client)
    resp = await app_client.patch(
        f"/api/v1/campaigns/{campaign['id']}",
        json={"settings": {"pinned_facts": ["The moon over Barrowdown is always red."]}},
    )
    assert resp.status_code == 200

    mock = make_mock([[TextDelta("Noted."), Done()]])
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])
    system = mock.calls[0].messages[0]["content"]
    assert "Pinned facts (always true" in system
    assert "The moon over Barrowdown is always red." in system

    # pin_fact is registered and gated → copilot mode holds it for DM approval.
    from app.ai.tools.registry import ToolContext, registry

    spec = registry.get("pin_fact")
    assert spec is not None and spec.gated and spec.mutating

    from app.db import get_sessionmaker
    from app.models import Campaign, Scene

    async with get_sessionmaker()() as db:
        c = await db.get(Campaign, campaign["id"])
        s = await db.get(Scene, scene["id"])
        ctx = ToolContext(db=db, campaign=c, scene=s)

        result = await registry.dispatch(ctx, "pin_fact", {"fact": "Rowan owes the party 50gp"})
        assert result.ok
        assert ctx.inverse_patches  # retcon can restore the previous list

        # case-insensitive dedupe
        result = await registry.dispatch(ctx, "pin_fact", {"fact": "rowan owes the party 50gp"})
        assert result.ok and result.data.get("note") == "already pinned"
        assert c.settings_json["pinned_facts"] == [
            "The moon over Barrowdown is always red.",
            "Rowan owes the party 50gp",
        ]

        result = await registry.dispatch(
            ctx, "pin_fact", {"fact": "Rowan owes the party 50gp", "op": "unpin"}
        )
        assert result.ok
        assert c.settings_json["pinned_facts"] == ["The moon over Barrowdown is always red."]
    set_provider(None)


# --- M4: party inventory in the prompt -------------------------------------------


async def test_party_inventory_in_prompt(app_client):
    campaign, scene, character = await setup_game(app_client)

    from app.db import get_sessionmaker
    from app.models import Character, InventoryEntry, Item

    async with get_sessionmaker()() as db:
        torch = Item(campaign_id=campaign["id"], name="Torch")
        rope = Item(campaign_id=campaign["id"], name="Hempen Rope")
        db.add_all([torch, rope])
        await db.flush()
        db.add(
            InventoryEntry(
                item_id=torch.id, owner_type="character", owner_id=character["id"], quantity=5
            )
        )
        db.add(
            InventoryEntry(
                item_id=rope.id, owner_type="character", owner_id=character["id"], quantity=1
            )
        )
        c = await db.get(Character, character["id"])
        c.currency_json = {"gp": 34, "sp": 0}
        await db.commit()

    mock = make_mock([[TextDelta("Onward."), Done()]])
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])
    system = mock.calls[0].messages[0]["content"]
    assert "Carrying:" in system
    assert "Torch x5" in system
    assert "Hempen Rope" in system
    assert "34gp" in system
    assert "0sp" not in system  # zero balances are omitted
    set_provider(None)


# --- M5: summaries without AI turns ------------------------------------------------


async def test_human_scene_backlog_summarizes(app_client, monkeypatch):
    from app.ai import memory

    monkeypatch.setattr(memory, "SUMMARIZE_EVERY", 5)

    campaign, scene, _ = await setup_game(app_client, dm_mode="human")
    make_mock([[TextDelta("The tavern brawl recap."), Done()]])
    for i in range(5):
        await app_client.post(
            f"/api/v1/scenes/{scene['id']}/messages", json={"content": f"Bar brawl beat {i}"}
        )

    from app.db import get_sessionmaker
    from app.models import Scene

    s = None
    for _ in range(100):
        await asyncio.sleep(0.02)
        async with get_sessionmaker()() as db:
            s = await db.get(Scene, scene["id"])
            if s.summary:
                break
    assert s is not None
    assert s.summary == "The tavern brawl recap."
    assert s.summary_upto_seq == 5
    set_provider(None)


async def test_dm_ending_scene_writes_recap(app_client):
    campaign, scene, _ = await setup_game(app_client, dm_mode="human")
    for i in range(4):
        await app_client.post(
            f"/api/v1/scenes/{scene['id']}/messages", json={"content": f"Fireside beat {i}"}
        )

    make_mock([[TextDelta("A quiet scene by the fire."), Done()]])
    resp = await app_client.patch(f"/api/v1/scenes/{scene['id']}", json={"status": "idle"})
    assert resp.status_code == 200

    from app.db import get_sessionmaker
    from app.models import Scene, Summary

    s = None
    for _ in range(100):
        await asyncio.sleep(0.02)
        async with get_sessionmaker()() as db:
            s = await db.get(Scene, scene["id"])
            if s.summary:
                break
    assert s is not None
    assert s.summary == "A quiet scene by the fire."

    async with get_sessionmaker()() as db:
        recaps = list(
            (
                await db.execute(
                    select(Summary).where(
                        Summary.campaign_id == campaign["id"], Summary.scope == "scene"
                    )
                )
            ).scalars()
        )
        assert len(recaps) == 1
    set_provider(None)

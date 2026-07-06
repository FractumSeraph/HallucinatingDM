"""Hard deletion: campaigns, scenes, and characters purge cleanly despite
SQLite's enforced foreign keys (no ON DELETE CASCADE in the schema)."""

from app.ai.mock_provider import MockProvider
from app.ai.provider import Done, LLMConfig, TextDelta, ToolCall, set_provider

from .test_memory import setup_game


def make_mock(script):
    mock = MockProvider(config=LLMConfig(provider="mock", toolcall_mode="native"))
    for turn in script:
        mock.queue_turn(turn)
    set_provider(mock)
    return mock


async def _populate(app_client, campaign, scene, character):
    """Give the campaign a bit of everything: messages, rolls, an NPC, a
    quest, combat history, and inventory (characters get a starting kit)."""
    await app_client.post(
        f"/api/v1/scenes/{scene['id']}/messages",
        json={"content": "I look around.", "character_id": character["id"]},
    )
    await app_client.post(
        f"/api/v1/scenes/{scene['id']}/roll", json={"expression": "1d20", "purpose": "check"}
    )
    make_mock(
        [
            [
                ToolCall(
                    id="c1", name="upsert_entity",
                    arguments={"kind": "npc", "name": "Grim", "role": "guard"},
                ),
                Done(),
            ],
            [
                ToolCall(
                    id="c2", name="update_quest",
                    arguments={"title": "Find the idol", "op": "create", "summary": "…"},
                ),
                Done(),
            ],
            [
                ToolCall(id="c3", name="start_combat",
                         arguments={"participants": [character["name"], "wolf"]}),
                Done(),
            ],
            [TextDelta("A wolf lunges!"), Done()],
        ]
    )
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])
    set_provider(None)


async def test_delete_campaign_purges_everything(app_client):
    campaign, scene, character = await setup_game(app_client)
    await _populate(app_client, campaign, scene, character)

    resp = await app_client.delete(f"/api/v1/campaigns/{campaign['id']}")
    assert resp.status_code == 200, resp.text

    assert (await app_client.get(f"/api/v1/campaigns/{campaign['id']}")).status_code == 404
    assert (
        await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")
    ).status_code == 404
    assert (
        await app_client.get(f"/api/v1/characters/{character['id']}")
    ).status_code == 404

    # No orphans left behind in any campaign-scoped table.
    from sqlalchemy import func, select

    from app.db import get_sessionmaker
    from app.models import (
        NPC,
        Character,
        InventoryEntry,
        Item,
        Message,
        Quest,
        Scene,
        Summary,
    )

    async with get_sessionmaker()() as db:
        for model in (Scene, Character, NPC, Quest, Item, Summary):
            count = (
                await db.execute(
                    select(func.count()).select_from(model).where(
                        model.campaign_id == campaign["id"]
                    )
                )
            ).scalar_one()
            assert count == 0, f"{model.__name__} left orphans"
        assert (
            await db.execute(select(func.count()).select_from(Message))
        ).scalar_one() == 0
        assert (
            await db.execute(select(func.count()).select_from(InventoryEntry))
        ).scalar_one() == 0


async def test_only_the_owner_deletes_a_campaign(app_client):
    campaign, _scene, _character = await setup_game(app_client)
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "p9@example.com", "password": "longenough", "display_name": "P"},
    )
    await app_client.post(
        "/api/v1/campaigns/join", json={"invite_code": campaign["invite_code"]}
    )
    resp = await app_client.delete(f"/api/v1/campaigns/{campaign['id']}")
    assert resp.status_code == 403


async def test_delete_scene_keeps_the_campaign_world(app_client):
    campaign, scene, character = await setup_game(app_client)
    await _populate(app_client, campaign, scene, character)

    resp = await app_client.delete(f"/api/v1/scenes/{scene['id']}")
    assert resp.status_code == 200, resp.text
    assert (
        await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")
    ).status_code == 404

    # The world survives: NPC, quest, and the character are untouched.
    world = (await app_client.get(f"/api/v1/campaigns/{campaign['id']}/world")).json()
    assert any(n["name"] == "Grim" for n in world["npcs"])
    assert any(q["title"] == "Find the idol" for q in world["quests"])
    assert (
        await app_client.get(f"/api/v1/characters/{character['id']}")
    ).status_code == 200


async def test_players_cannot_delete_scenes(app_client):
    campaign, scene, _character = await setup_game(app_client)
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "p10@example.com", "password": "longenough", "display_name": "P"},
    )
    await app_client.post(
        "/api/v1/campaigns/join", json={"invite_code": campaign["invite_code"]}
    )
    assert (await app_client.delete(f"/api/v1/scenes/{scene['id']}")).status_code == 403


async def test_delete_character_unlinks_history(app_client):
    campaign, scene, character = await setup_game(app_client)
    await app_client.post(
        f"/api/v1/scenes/{scene['id']}/messages",
        json={"content": "For glory!", "character_id": character["id"]},
    )

    resp = await app_client.delete(f"/api/v1/characters/{character['id']}")
    assert resp.status_code == 200, resp.text
    assert (
        await app_client.get(f"/api/v1/characters/{character['id']}")
    ).status_code == 404

    # The chat line survives, just no longer linked to the character.
    msgs = (await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")).json()
    line = next(m for m in msgs if m["content"] == "For glory!")
    assert line["character_id"] is None

    # And the scene roster forgot them.
    from app.db import get_sessionmaker
    from app.models import Scene

    async with get_sessionmaker()() as db:
        s = await db.get(Scene, scene["id"])
        assert character["id"] not in (s.party_json or [])


async def test_players_cannot_delete_others_characters(app_client):
    campaign, _scene, character = await setup_game(app_client)
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "p11@example.com", "password": "longenough", "display_name": "P"},
    )
    await app_client.post(
        "/api/v1/campaigns/join", json={"invite_code": campaign["invite_code"]}
    )
    assert (
        await app_client.delete(f"/api/v1/characters/{character['id']}")
    ).status_code == 403

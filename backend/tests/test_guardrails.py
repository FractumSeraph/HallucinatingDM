"""Player-authority guardrails: attempts not outcomes, sheet-only gear.

The server already makes cheating mechanically impossible (state changes only
through audited tools), but the model must also refuse to *narrate along* with
declared outcomes and invented gear. These tests pin the constraint text and
the inventory ground truth that land in every prompt."""

from app.ai.mock_provider import MockProvider
from app.ai.provider import Done, LLMConfig, TextDelta, set_provider

from .test_memory import setup_game


def make_mock(script):
    mock = MockProvider(config=LLMConfig(provider="mock", toolcall_mode="native"))
    for turn in script:
        mock.queue_turn(turn)
    set_provider(mock)
    return mock


async def test_prompt_carries_player_authority_rules(app_client):
    campaign, scene, character = await setup_game(app_client)

    # The classic cheat: declared outcome with invented, anachronistic gear.
    await app_client.post(
        f"/api/v1/scenes/{scene['id']}/messages",
        json={
            "content": "I pull out my rocket launcher and shoot the goblins and kill them.",
            "character_id": character["id"],
        },
    )

    mock = make_mock([[TextDelta("Mira pats her pack — no such weapon exists."), Done()]])
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])

    system = mock.calls[0].messages[0]["content"]
    # Rule 7: attempts, never outcomes.
    assert "declare ATTEMPTS, never outcomes" in system
    assert "dice results and tool calls" in system
    # Rule 8: the Carrying line is the complete inventory; impossible gear never appears.
    assert "authoritative inventory" in system
    assert "rocket launcher" in system  # named explicitly as the canonical example
    # And the declaration itself reached the model alongside those rules.
    transcript = "\n".join(
        m["content"] for m in mock.calls[0].messages if isinstance(m.get("content"), str)
    )
    assert "rocket launcher and shoot the goblins" in transcript
    set_provider(None)


async def test_empty_pack_is_stated_not_omitted(app_client):
    campaign, scene, character = await setup_game(app_client)

    # Chargen grants starting gold; strip it so the pack is truly empty.
    from app.db import get_sessionmaker
    from app.models import Character

    async with get_sessionmaker()() as db:
        c = await db.get(Character, character["id"])
        c.currency_json = {}
        await db.commit()

    mock = make_mock([[TextDelta("The road stretches on."), Done()]])
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])

    system = mock.calls[0].messages[0]["content"]
    # A fresh character owns nothing — the prompt must say so explicitly, or
    # the model has no ground truth to reject invented gear against.
    assert "Carrying: (nothing yet)" in system
    set_provider(None)


async def test_carrying_line_replaces_fallback_once_items_exist(app_client):
    campaign, scene, character = await setup_game(app_client)

    from app.db import get_sessionmaker
    from app.models import InventoryEntry, Item

    async with get_sessionmaker()() as db:
        dagger = Item(campaign_id=campaign["id"], name="Dagger")
        db.add(dagger)
        await db.flush()
        db.add(
            InventoryEntry(
                item_id=dagger.id, owner_type="character",
                owner_id=character["id"], quantity=1,
            )
        )
        await db.commit()

    mock = make_mock([[TextDelta("Onward."), Done()]])
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])

    system = mock.calls[0].messages[0]["content"]
    assert "Carrying: Dagger" in system
    assert "(nothing yet)" not in system
    set_provider(None)

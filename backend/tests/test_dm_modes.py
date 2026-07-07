"""Copilot/assist approvals, whispers, retcon, level-up, roll responses."""

from app.ai.mock_provider import MockProvider
from app.ai.provider import Done, LLMConfig, TextDelta, ToolCall, set_provider

BUILD = {
    "name": "Mira",
    "race": "elf",
    "subrace": "High Elf",
    "klass": "wizard",
    "background": "acolyte",
    "method": "standard",
    "base_scores": {"str": 8, "dex": 13, "con": 14, "int": 15, "wis": 12, "cha": 10},
    "skill_choices": ["arcana", "investigation"],
}


async def setup_game(client, dm_mode="ai"):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "dm@example.com", "password": "longenough", "display_name": "DM"},
    )
    campaign = (await client.post("/api/v1/campaigns", json={"name": "C"})).json()
    scene = (
        await client.post(
            f"/api/v1/campaigns/{campaign['id']}/scenes",
            json={"name": "S", "kind": "main", "dm_mode": dm_mode},
        )
    ).json()
    character = (
        await client.post(f"/api/v1/campaigns/{campaign['id']}/characters", json=BUILD)
    ).json()
    return campaign, scene, character


def make_mock(script):
    mock = MockProvider(config=LLMConfig(provider="mock", toolcall_mode="native"))
    for turn in script:
        mock.queue_turn(turn)
    set_provider(mock)
    return mock


async def test_copilot_gates_award_until_approval(app_client):
    campaign, scene, character = await setup_game(app_client, dm_mode="copilot")

    make_mock(
        [
            [
                ToolCall(id="c1", name="award", arguments={"xp_each": 100, "recipients": "party"}),
                Done(),
            ],
            [TextDelta("Victory!"), Done()],
        ]
    )
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])

    # XP not applied yet
    resp = await app_client.get(f"/api/v1/characters/{character['id']}")
    assert resp.json()["xp"] == 0

    approvals = (
        await app_client.get(f"/api/v1/campaigns/{campaign['id']}/approvals")
    ).json()
    assert len(approvals) == 1
    assert approvals[0]["kind"] == "tool_call"
    assert approvals[0]["payload_json"]["tool"] == "award"

    # DM approves → XP lands
    resp = await app_client.post(f"/api/v1/approvals/{approvals[0]['id']}/approve", json={})
    assert resp.status_code == 200
    resp = await app_client.get(f"/api/v1/characters/{character['id']}")
    assert resp.json()["xp"] == 100

    # queue is now empty
    approvals = (
        await app_client.get(f"/api/v1/campaigns/{campaign['id']}/approvals")
    ).json()
    assert approvals == []
    set_provider(None)


async def test_copilot_rolls_execute_immediately(app_client):
    campaign, scene, character = await setup_game(app_client, dm_mode="copilot")
    make_mock(
        [
            [ToolCall(id="c1", name="update_hp", arguments={"target": "Mira", "delta": -2}), Done()],
            [TextDelta("Ouch."), Done()],
        ]
    )
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])
    # update_hp is not gated → applies without approval
    resp = await app_client.get(f"/api/v1/characters/{character['id']}")
    assert resp.json()["hp_current"] == character["hp_max"] - 2
    set_provider(None)


async def test_assist_mode_drafts_narration(app_client):
    campaign, scene, character = await setup_game(app_client, dm_mode="assist")
    make_mock([[TextDelta("A dragon descends upon the village!"), Done()]])
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])

    # players don't see the draft
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "p@example.com", "password": "longenough", "display_name": "P"},
    )
    await app_client.post(
        "/api/v1/campaigns/join", json={"invite_code": campaign["invite_code"]}
    )
    msgs = (await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")).json()
    assert not any("dragon" in m["content"] for m in msgs)

    # DM approves with an edit → players see the edited version
    await app_client.post(
        "/api/v1/auth/login", json={"email": "dm@example.com", "password": "longenough"}
    )
    approvals = (
        await app_client.get(f"/api/v1/campaigns/{campaign['id']}/approvals")
    ).json()
    assert approvals[0]["kind"] == "draft_turn"
    await app_client.post(
        f"/api/v1/approvals/{approvals[0]['id']}/approve",
        json={"content": "A wyvern circles the village!"},
    )
    await app_client.post(
        "/api/v1/auth/login", json={"email": "p@example.com", "password": "longenough"}
    )
    msgs = (await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")).json()
    assert any("wyvern" in m["content"] for m in msgs)
    set_provider(None)


async def test_whisper_hidden_and_reaches_ai(app_client):
    campaign, scene, character = await setup_game(app_client, dm_mode="ai")

    mock = make_mock([[TextDelta("The innkeeper eyes you nervously."), Done()]])
    resp = await app_client.post(
        f"/api/v1/scenes/{scene['id']}/whisper",
        json={"content": "The innkeeper is the murderer; drop subtle hints."},
    )
    assert resp.status_code == 200

    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])

    # whisper reached the model as a private instruction
    sent = "\n".join(
        m["content"] for m in mock.calls[0].messages if isinstance(m.get("content"), str)
    )
    assert "innkeeper is the murderer" in sent
    assert "PRIVATE DM INSTRUCTION" in sent

    # players never see it
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "p@example.com", "password": "longenough", "display_name": "P"},
    )
    await app_client.post(
        "/api/v1/campaigns/join", json={"invite_code": campaign["invite_code"]}
    )
    msgs = (await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")).json()
    assert not any("murderer" in m["content"] for m in msgs)
    set_provider(None)


async def test_retcon_reverts_hp_and_strikes_messages(app_client):
    campaign, scene, character = await setup_game(app_client, dm_mode="ai")

    make_mock(
        [
            [
                TextDelta("A trap springs! "),
                ToolCall(id="c1", name="update_hp", arguments={"target": "Mira", "delta": -5}),
                Done(),
            ],
            [TextDelta("You barely survive."), Done()],
        ]
    )
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])
    resp = await app_client.get(f"/api/v1/characters/{character['id']}")
    assert resp.json()["hp_current"] == character["hp_max"] - 5

    resp = await app_client.post(f"/api/v1/scenes/{scene['id']}/retcon-last-turn")
    assert resp.status_code == 200
    body = resp.json()
    assert body["reverted_tool_calls"] >= 1
    assert body["struck_messages"] >= 1

    # damage undone
    resp = await app_client.get(f"/api/v1/characters/{character['id']}")
    assert resp.json()["hp_current"] == character["hp_max"]

    # struck messages excluded from player view context: they remain but flagged
    msgs = (await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")).json()
    ai_msgs = [m for m in msgs if m["author_type"] == "ai"]
    assert all(m["struck"] for m in ai_msgs)
    set_provider(None)


async def test_level_up_flow(app_client):
    campaign, scene, character = await setup_game(app_client)

    # not enough XP
    resp = await app_client.post(f"/api/v1/characters/{character['id']}/level-up")
    assert resp.status_code == 400

    # grant XP through the ai award tool path (direct dispatch)
    import app.ai.dm_agent  # noqa: F401
    from app.ai.tools.registry import ToolContext, registry
    from app.db import get_sessionmaker
    from app.models import Campaign, Scene

    async with get_sessionmaker()() as db:
        campaign_row = await db.get(Campaign, campaign["id"])
        scene_row = await db.get(Scene, scene["id"])
        ctx = ToolContext(db=db, campaign=campaign_row, scene=scene_row)
        result = await registry.dispatch(
            ctx, "award", {"xp_each": 300, "recipients": "party"}
        )
        assert result.ok
        assert result.data["level_ups_available"]

    resp = await app_client.post(f"/api/v1/characters/{character['id']}/level-up")
    assert resp.status_code == 200
    c = resp.json()
    assert c["level"] == 2
    assert c["hp_max"] > character["hp_max"]
    assert c["spell_slots_json"]["1"]["max"] == 3  # wizard L2
    assert c["resources_json"]["hit_dice"]["max"] == 2


async def test_roll_request_response(app_client):
    campaign, scene, character = await setup_game(app_client, dm_mode="ai")

    make_mock(
        [
            [
                ToolCall(
                    id="c1",
                    name="request_player_roll",
                    arguments={
                        "character": "Mira",
                        "kind": "check",
                        "ability_or_skill": "arcana",
                        "dc": 10,
                    },
                ),
                Done(),
            ],
            [TextDelta("Make the check!"), Done()],
            # the AI responds again after the player rolls
            [TextDelta("Interesting result…"), Done()],
        ]
    )
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])
    msgs = (await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")).json()
    prompt = next(m for m in msgs if m["payload_json"].get("roll_request"))

    resp = await app_client.post(
        f"/api/v1/scenes/{scene['id']}/respond-roll", json={"message_id": prompt["id"]}
    )
    assert resp.status_code == 200
    roll = resp.json()["payload_json"]["roll"]
    # Mira is proficient in arcana: INT +3, prof +2
    assert roll["modifier"] == 5
    assert roll["dc"] == 10

    # answering twice is rejected
    resp = await app_client.post(
        f"/api/v1/scenes/{scene['id']}/respond-roll", json={"message_id": prompt["id"]}
    )
    assert resp.status_code == 400
    set_provider(None)


async def test_chargen_suggest_with_mock(app_client):
    campaign, scene, character = await setup_game(app_client)

    good_build = (
        '{"name": "Borin", "race": "dwarf", "subrace": "Hill Dwarf", "klass": "cleric",'
        '"background": "acolyte", "alignment": "Lawful Good", "method": "standard",'
        '"base_scores": {"str": 13, "dex": 8, "con": 14, "int": 10, "wis": 15, "cha": 12},'
        '"skill_choices": ["insight", "medicine"], "personality": "Gruff but kind.",'
        '"backstory": "Exiled temple guard seeking redemption."}'
    )
    # first answer invalid (bad race), then corrected — exercises the repair loop
    make_mock(
        [
            [TextDelta(good_build.replace('"dwarf"', '"astral-dwarf"')), Done()],
            [TextDelta(good_build), Done()],
        ]
    )
    resp = await app_client.post(
        f"/api/v1/campaigns/{campaign['id']}/chargen-suggest",
        json={"concept": "a gruff dwarven healer"},
    )
    assert resp.status_code == 200, resp.text
    build = resp.json()
    assert build["race"] == "dwarf"
    assert build["klass"] == "cleric"

    # the suggested build actually creates a character
    resp = await app_client.post(f"/api/v1/campaigns/{campaign['id']}/characters", json=build)
    assert resp.status_code == 200
    set_provider(None)


async def test_player_cannot_roll_as_anothers_character(app_client):
    """Dice rolls attribute to a character — only its owner (or the DM) may
    roll as it, otherwise a player could fake another PC's rolls in the log."""
    campaign, scene, character = await setup_game(app_client, dm_mode="human")

    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "rogue@example.com", "password": "longenough", "display_name": "R"},
    )
    await app_client.post(
        "/api/v1/campaigns/join", json={"invite_code": campaign["invite_code"]}
    )

    # The second player tries to roll as the DM-owned first character.
    resp = await app_client.post(
        f"/api/v1/scenes/{scene['id']}/roll",
        json={"expression": "1d20", "purpose": "death_save", "character_id": character["id"]},
    )
    assert resp.status_code == 403

    # Rolling as themselves (no character) still works.
    resp = await app_client.post(
        f"/api/v1/scenes/{scene['id']}/roll", json={"expression": "1d20", "purpose": "check"}
    )
    assert resp.status_code == 200


async def test_assist_tool_chips_stay_dm_only(app_client):
    """In assist mode the WHOLE draft is private — tool chips (like the
    'waiting on approval' note for a held mutation) must not reach players."""
    campaign, scene, character = await setup_game(app_client, dm_mode="assist")
    make_mock(
        [
            [
                ToolCall(
                    id="h1", name="update_hp",
                    arguments={"target": character["name"], "delta": -3, "reason": "trap"},
                ),
                Done(),
            ],
            [TextDelta("The lock resists your pick."), Done()],
        ]
    )
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])

    # The DM sees the tool chip…
    msgs = (await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")).json()
    assert any(m["kind"] == "tool_result" for m in msgs)

    # …players do not.
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "p2@example.com", "password": "longenough", "display_name": "P2"},
    )
    await app_client.post(
        "/api/v1/campaigns/join", json={"invite_code": campaign["invite_code"]}
    )
    msgs = (await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")).json()
    assert not any(m["kind"] == "tool_result" for m in msgs)
    assert not any("lock resists" in m["content"] for m in msgs)
    set_provider(None)


async def test_retcon_revives_instant_death(app_client):
    """A retconned overkill blow restores status, not just HP."""
    campaign, scene, character = await setup_game(app_client, dm_mode="ai")
    make_mock(
        [
            [
                ToolCall(id="k1", name="update_hp", arguments={"target": "Mira", "delta": -100}),
                Done(),
            ],
            [TextDelta("The blow is fatal."), Done()],
        ]
    )
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])
    body = (await app_client.get(f"/api/v1/characters/{character['id']}")).json()
    assert body["status"] == "dead"  # overkill ≥ max HP = instant death

    await app_client.post(f"/api/v1/scenes/{scene['id']}/retcon-last-turn")
    body = (await app_client.get(f"/api/v1/characters/{character['id']}")).json()
    assert body["status"] == "active"  # revived, not just healed
    assert body["hp_current"] == character["hp_max"]
    set_provider(None)


async def test_retcon_unstarts_combat(app_client):
    """Retconning the turn that started a fight deletes the encounter."""
    campaign, scene, character = await setup_game(app_client, dm_mode="ai")
    make_mock(
        [
            [
                ToolCall(
                    id="s1", name="start_combat",
                    arguments={"participants": ["Mira", "wolf"]},
                ),
                Done(),
            ],
            [TextDelta("A wolf lunges from the brush!"), Done()],
        ]
    )
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])
    combat = (await app_client.get(f"/api/v1/scenes/{scene['id']}/combat")).json()
    assert combat["encounter"] is not None

    await app_client.post(f"/api/v1/scenes/{scene['id']}/retcon-last-turn")
    combat = (await app_client.get(f"/api/v1/scenes/{scene['id']}/combat")).json()
    assert combat["encounter"] is None  # the fight never happened

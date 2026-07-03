"""End-to-end agent loop tests with a scripted MockProvider."""

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


async def test_agent_turn_with_tools(app_client):
    campaign, scene, character = await setup_game(app_client)

    mock = make_mock(
        [
            # Round 1: narrate + roll a stealth check for Mira
            [
                TextDelta("A goblin leaps from the shadows! "),
                ToolCall(
                    id="c1",
                    name="roll_dice",
                    arguments={
                        "kind": "check",
                        "roller": "Mira",
                        "ability_or_skill": "stealth",
                        "dc": 12,
                        "reason": "Ducking behind the cart",
                    },
                ),
                Done(),
            ],
            # Round 2: deal damage to Mira
            [
                ToolCall(
                    id="c2",
                    name="update_hp",
                    arguments={"target": "Mira", "delta": -3, "reason": "goblin arrow"},
                ),
                Done(),
            ],
            # Round 3: text-only wrap-up ends the turn
            [TextDelta("The arrow grazes your shoulder. What do you do?"), Done()],
        ]
    )

    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])

    # three LLM rounds happened
    assert len(mock.calls) == 3
    # native tools were offered
    assert mock.calls[0].tools is not None
    tool_names = {t["function"]["name"] for t in mock.calls[0].tools}
    assert {"roll_dice", "update_hp", "lookup", "award"} <= tool_names

    # tool results were fed back as tool-role messages
    round2 = mock.calls[1].messages
    assert any(m.get("role") == "tool" for m in round2)

    # damage really landed
    resp = await app_client.get(f"/api/v1/characters/{character['id']}")
    assert resp.json()["hp_current"] == character["hp_max"] - 3

    # transcript contains: narration rounds, a roll card, and the tool note
    resp = await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")
    kinds = [m["kind"] for m in resp.json()]
    assert "narration" in kinds
    assert "roll" in kinds
    assert "tool_result" in kinds

    # the roll message carries verifiable dice + DC outcome
    roll_msgs = [m for m in resp.json() if m["kind"] == "roll"]
    roll = roll_msgs[0]["payload_json"]["roll"]
    assert roll["dc"] == 12
    assert roll["outcome"] in ("success", "failure")

    # turn trace persisted
    from sqlalchemy import select

    from app.db import get_sessionmaker
    from app.models import AiTurn

    async with get_sessionmaker()() as db:
        turn = (await db.execute(select(AiTurn))).scalars().first()
        assert turn is not None
        assert turn.status == "done"
        assert len(turn.steps_json) == 3

    set_provider(None)


async def test_agent_recovers_from_bad_tool_args(app_client):
    campaign, scene, character = await setup_game(app_client)

    make_mock(
        [
            # invalid args (missing target) → error result → model retries correctly
            [ToolCall(id="c1", name="update_hp", arguments={"delta": "not-an-int"}), Done()],
            [
                ToolCall(
                    id="c2", name="update_hp", arguments={"target": "Mira", "delta": -1}
                ),
                Done(),
            ],
            [TextDelta("Ouch."), Done()],
        ]
    )
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])

    resp = await app_client.get(f"/api/v1/characters/{character['id']}")
    assert resp.json()["hp_current"] == character["hp_max"] - 1
    set_provider(None)


async def test_agent_resolver_fuzzy_and_suggestions(app_client):
    campaign, scene, character = await setup_game(app_client)

    mock = make_mock(
        [
            # close typo resolves automatically…
            [ToolCall(id="c1", name="update_hp", arguments={"target": "Mirra", "delta": -2}), Done()],
            # …a far-off name gets an error with suggestions, and the model retries
            [ToolCall(id="c2", name="update_hp", arguments={"target": "Meera", "delta": -1}), Done()],
            [ToolCall(id="c3", name="update_hp", arguments={"target": "Mira", "delta": -1}), Done()],
            [TextDelta("Hmm."), Done()],
        ]
    )
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])

    resp = await app_client.get(f"/api/v1/characters/{character['id']}")
    assert resp.json()["hp_current"] == character["hp_max"] - 3  # -2 and -1; miss did nothing

    # the miss produced a tool-role error message containing a suggestion
    tool_messages = [
        m for call in mock.calls for m in call.messages if m.get("role") == "tool"
    ]
    assert any("Mira" in m["content"] and '"ok": false' in m["content"] for m in tool_messages)
    set_provider(None)


async def test_unconsciousness_and_death(app_client):
    campaign, scene, character = await setup_game(app_client)

    make_mock(
        [
            [
                ToolCall(
                    id="c1",
                    name="update_hp",
                    arguments={"target": "Mira", "delta": -character["hp_max"]},
                ),
                Done(),
            ],
            [TextDelta("Mira crumples."), Done()],
        ]
    )
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])

    resp = await app_client.get(f"/api/v1/characters/{character['id']}")
    c = resp.json()
    assert c["hp_current"] == 0
    assert "unconscious" in c["conditions_json"]
    assert c["status"] == "active"  # down, not dead
    set_provider(None)

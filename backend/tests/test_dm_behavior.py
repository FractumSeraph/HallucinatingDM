"""DM behavioral guidance in the system prompt.

These pin the fixes for the most-reported AI-DM failure modes (railroading over
player intent, consequence-free "yes-man" play, and repetitive verbal tics) so
they can't silently regress out of the prompt.
"""

from app.ai.mock_provider import MockProvider
from app.ai.provider import Done, LLMConfig, TextDelta, set_provider

from .test_memory import setup_game


def make_mock(script):
    mock = MockProvider(config=LLMConfig(provider="mock", toolcall_mode="native"))
    for turn in script:
        mock.queue_turn(turn)
    set_provider(mock)
    return mock


async def test_prompt_carries_behavioral_guidance(app_client):
    campaign, scene, character = await setup_game(app_client)
    await app_client.post(
        f"/api/v1/scenes/{scene['id']}/messages",
        json={"content": "I collect the reward the mayor promised us.", "character_id": character["id"]},
    )

    mock = make_mock([[TextDelta("The mayor counts out your coin."), Done()]])
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])
    system = mock.calls[0].messages[0]["content"]

    # Anti-railroading: pursue the player's stated goal, don't hijack the scene.
    assert "do NOT railroad" in system
    assert "hijack the scene" in system
    # Consequences / not a yes-man.
    assert "Let choices carry weight" in system
    assert "pushover" in system
    # Anti-repetition / verbal tics.
    assert "Vary your prose" in system
    assert "verbal tic" in system
    # Narration must honor the die — no success on a failed roll.
    assert "Honor the die" in system
    assert "NEVER narrate a success on a failed check" in system
    # Never voice or act for a player character.
    assert "Do NOT invent their dialogue" in system
    # Attacks roll to-hit vs AC before damage.
    assert "Resolve attacks honestly" in system
    assert 'roll_dice with kind="attack"' in system
    # Action economy + turn discipline: no impossible/off-turn prompts.
    assert "Respect the action economy" in system
    assert "ONLY on their own turn" in system
    set_provider(None)

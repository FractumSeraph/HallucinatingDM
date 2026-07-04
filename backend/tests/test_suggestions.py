"""Action suggestions for stuck players: parsing, prompting, and fallback."""

from app.ai.mock_provider import MockProvider
from app.ai.provider import Done, LLMConfig, TextDelta, set_provider

from .test_memory import setup_game


def make_mock(script):
    mock = MockProvider(config=LLMConfig(provider="mock", toolcall_mode="native"))
    for turn in script:
        mock.queue_turn(turn)
    set_provider(mock)
    return mock


async def test_suggest_actions_parses_model_output(app_client):
    campaign, scene, character = await setup_game(app_client, dm_mode="human")
    await app_client.post(
        f"/api/v1/scenes/{scene['id']}/messages",
        json={"content": "The innkeeper eyes you nervously.", "character_id": character["id"]},
    )

    mock = make_mock(
        [
            [
                TextDelta(
                    "1. I ask the innkeeper what has him so rattled.\n"
                    "2. I scan the common room for anyone watching us.\n"
                    "3. I quietly ready my staff under the table.\n"
                ),
                Done(),
            ]
        ]
    )

    resp = await app_client.post(f"/api/v1/scenes/{scene['id']}/suggest-actions")
    assert resp.status_code == 200
    suggestions = resp.json()["suggestions"]
    assert suggestions == [
        "I ask the innkeeper what has him so rattled.",
        "I scan the common room for anyone watching us.",
        "I quietly ready my staff under the table.",
    ]

    # The prompt grounded the model in the character and the live scene.
    prompt = mock.calls[0].messages[0]["content"]
    assert "Mira" in prompt
    assert "innkeeper eyes you nervously" in prompt
    set_provider(None)


async def test_suggest_actions_falls_back_when_unparseable(app_client):
    campaign, scene, _ = await setup_game(app_client, dm_mode="human")
    # Unscripted mock emits prose with no numbered lines → generic fallback.
    make_mock([])

    resp = await app_client.post(f"/api/v1/scenes/{scene['id']}/suggest-actions")
    assert resp.status_code == 200
    suggestions = resp.json()["suggestions"]
    assert len(suggestions) >= 3
    assert all(isinstance(s, str) and s for s in suggestions)
    set_provider(None)


async def test_suggest_actions_requires_membership(app_client):
    campaign, scene, _ = await setup_game(app_client)
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "rando@example.com", "password": "longenough", "display_name": "Rando"},
    )
    resp = await app_client.post(f"/api/v1/scenes/{scene['id']}/suggest-actions")
    assert resp.status_code in (401, 403)

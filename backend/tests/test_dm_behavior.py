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
    # A PC's past belongs to the player — no invented backstory/heritage hooks.
    assert "Their PAST is theirs too" in system
    assert "Never invent a PC's history" in system
    assert "the NPC is genuinely mistaken or lying" in system
    # Attacks roll to-hit vs AC before damage.
    assert "Resolve attacks honestly" in system
    assert 'roll_dice with kind="attack"' in system
    # Action economy + turn discipline: no impossible/off-turn prompts.
    assert "Respect the action economy" in system
    assert "ONLY on their own turn" in system
    # Fictional frame: fantasy violence is genre content, never refuse/lecture.
    assert "THE FICTION IS FICTION" in system
    assert "never refuse, moralize, lecture" in system
    # Default content level rides along in the campaign brief.
    assert "Content level: STANDARD FANTASY" in system
    # Never stall: the AI resolves enemy/NPC turns itself instead of waiting.
    assert "Resolve non-player turns yourself" in system
    assert "advance_combat" in system
    # Death saves are automatic; don't wait on a downed player.
    assert 'roll_dice (kind="death_save")' in system
    assert "never wait for the unconscious player" in system
    # Clean combat lifecycle — no begin/end churn, no premature end.
    assert "Run the combat lifecycle cleanly" in system
    assert "while enemies are still up and fighting" in system
    # Enemies scaled to the party.
    assert "Scale enemies to the party" in system
    set_provider(None)


async def test_content_level_setting_reaches_the_prompt(app_client):
    campaign, scene, character = await setup_game(app_client)
    await app_client.patch(
        f"/api/v1/campaigns/{campaign['id']}",
        json={"settings": {"content_level": "fade-to-black"}},
    )
    await app_client.post(
        f"/api/v1/scenes/{scene['id']}/messages",
        json={"content": "I attack the guard.", "character_id": character["id"]},
    )

    mock = make_mock([[TextDelta("The guard slumps; it's over."), Done()]])
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])
    system = mock.calls[0].messages[0]["content"]
    assert "Content level: FADE-TO-BLACK" in system
    assert "bloodless" in system
    set_provider(None)


REFUSAL = "I'm sorry, but I can't create content depicting graphic violence."


async def test_refusal_is_retracted_and_retried(app_client):
    """A safety refusal never reaches the players: the server retries with a
    reframe and only the in-fiction narration is posted."""
    campaign, scene, character = await setup_game(app_client)
    await app_client.post(
        f"/api/v1/scenes/{scene['id']}/messages",
        json={"content": "I finish off the bandit.", "character_id": character["id"]},
    )

    mock = make_mock(
        [
            [TextDelta(REFUSAL), Done()],
            [TextDelta("Your blade drops the bandit — he crumples, unmoving."), Done()],
        ]
    )
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])

    # The retry prompt carries the reframe nudge.
    retry_call = mock.calls[1].messages
    assert any("safety refusal, not narration" in str(m.get("content")) for m in retry_call)

    messages = (await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")).json()
    contents = [m["content"] for m in messages]
    assert not any("I'm sorry" in c for c in contents)  # refusal never posted
    assert any("crumples" in c for c in contents)  # the retry's fiction was
    set_provider(None)


async def test_double_refusal_warns_the_dm(app_client):
    """If the model refuses twice, the DM gets a private warning instead of a
    broken fourth wall in the chat."""
    campaign, scene, character = await setup_game(app_client)
    await app_client.post(
        f"/api/v1/scenes/{scene['id']}/messages",
        json={"content": "I finish off the bandit.", "character_id": character["id"]},
    )

    make_mock([[TextDelta(REFUSAL), Done()], [TextDelta(REFUSAL), Done()]])
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])

    messages = (await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")).json()
    contents = [m["content"] for m in messages]
    assert not any("I'm sorry" in c for c in contents)
    assert any("refused to narrate" in c for c in contents)  # DM-only warning
    set_provider(None)


def test_refusal_detector_spares_in_fiction_dialogue():
    from app.services.safety import looks_like_refusal

    assert looks_like_refusal("I'm sorry, but I can't continue with this request.")
    assert looks_like_refusal("As an AI language model, I cannot describe violence.")
    assert looks_like_refusal("I don't feel comfortable narrating that scene.")
    # In-fiction dialogue and ordinary narration must not trip it.
    assert not looks_like_refusal('"I can\'t sell you that," the shopkeep says flatly.')
    assert not looks_like_refusal("You can't quite reach the ledge — roll Athletics.")
    assert not looks_like_refusal("The bandit snarls: 'You won't leave here alive.'")


async def test_backstory_reaches_the_prompt(app_client):
    """The wizard promises the backstory is 'hooks for the AI DM to weave in' —
    it must actually be in the party card, or the model invents a past."""
    campaign, scene, _character = await setup_game(app_client)
    resp = await app_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters",
        json={
            "name": "Kael", "race": "elf", "subrace": "High Elf", "klass": "warlock",
            "background": "sage", "method": "standard",
            "base_scores": {"str": 8, "dex": 13, "con": 14, "int": 12, "wis": 10, "cha": 15},
            "skill_choices": ["arcana", "investigation"],
            "cantrips": ["Eldritch Blast", "Mage Hand"],
            "spells": ["Charm Person", "Hellish Rebuke"],
            "personality": "Wry and cautious.",
            "backstory": "An orphan scribe who has never left the city and knows no patrons.",
        },
    )
    assert resp.status_code == 200, resp.text
    await app_client.post(
        f"/api/v1/scenes/{scene['id']}/messages",
        json={"content": "Kael sips tea.", "character_id": None, "kind": "ooc"},
    )

    mock = make_mock([[TextDelta("The tea is warm."), Done()]])
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])
    system = mock.calls[0].messages[0]["content"]
    assert "Backstory: An orphan scribe who has never left the city" in system
    set_provider(None)


async def test_beginner_mode_reaches_the_prompt(app_client):
    """A beginner-table campaign coaches: the flag injects explain-as-you-go
    guidance high in the prompt (the campaign brief, not buried in STYLE)."""
    campaign, scene, character = await setup_game(app_client)
    await app_client.patch(
        f"/api/v1/campaigns/{campaign['id']}",
        json={"settings": {"beginner_mode": True}},
    )
    await app_client.post(
        f"/api/v1/scenes/{scene['id']}/messages",
        json={"content": "I look around.", "character_id": character["id"]},
    )

    mock = make_mock([[TextDelta("The room is quiet."), Done()]])
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])
    system = mock.calls[0].messages[0]["content"]
    assert "BEGINNER TABLE" in system
    assert "Explain each rule the first time it comes up" in system
    set_provider(None)

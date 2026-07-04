"""Character creation now produces a playable sheet: starting equipment,
armor-derived AC, and known spells the AI can see."""

from .test_memory import setup_game


async def _make_character(client, cid, **overrides):
    body = {
        "name": "Test", "race": "human", "klass": "fighter", "background": "soldier",
        "method": "standard",
        "base_scores": {"str": 15, "dex": 13, "con": 14, "int": 10, "wis": 12, "cha": 8},
        "skill_choices": ["athletics", "intimidation"],
    }
    body.update(overrides)
    return await client.post(f"/api/v1/campaigns/{cid}/characters", json=body)


async def test_fighter_gets_kit_and_armored_ac(app_client):
    campaign, _scene, _ = await setup_game(app_client)
    cid = campaign["id"]
    resp = await _make_character(app_client, cid)
    assert resp.status_code == 200
    char = resp.json()

    # Chain mail (16) + shield (2) = 18, not the old unarmored 10+DEX.
    assert char["ac"] == 18

    inv = (await app_client.get(f"/api/v1/characters/{char['id']}/inventory")).json()
    names = {i["name"].lower() for i in inv}
    assert "chain mail" in names
    assert "longsword" in names
    assert "shield" in names
    # Ammo granted with quantity.
    bolts = next((i for i in inv if i["name"].lower() == "crossbow bolt"), None)
    assert bolts and bolts["quantity"] == 20


async def test_sorcerer_spell_selection(app_client):
    campaign, _scene, _ = await setup_game(app_client)
    cid = campaign["id"]

    opts = (await app_client.get(f"/api/v1/campaigns/{cid}/class-spells/sorcerer")).json()
    assert opts["is_caster"] is True
    assert opts["cantrips_known"] == 4 and opts["spells_known"] == 2
    assert "Fire Bolt" in opts["cantrips"]
    assert "Magic Missile" in opts["level1"]

    resp = await _make_character(
        app_client, cid, name="Vesper", klass="sorcerer",
        base_scores={"str": 8, "dex": 14, "con": 13, "int": 10, "wis": 12, "cha": 15},
        skill_choices=["arcana", "deception"],
        cantrips=["Fire Bolt", "Ray of Frost"],
        spells=["Magic Missile", "Sleep"],
    )
    assert resp.status_code == 200
    sheet = resp.json()["sheet_json"]
    assert sheet["spells"]["cantrips"] == ["Fire Bolt", "Ray of Frost"]
    assert sheet["spells"]["known"] == ["Magic Missile", "Sleep"]

    # Sorcerer AC is unarmored (no armor in kit): 10 + DEX(+2) = 12.
    assert resp.json()["ac"] == 12


async def test_spell_choices_are_validated(app_client):
    campaign, _scene, _ = await setup_game(app_client)
    cid = campaign["id"]
    # Too many cantrips (sorcerer max 4)…
    resp = await _make_character(
        app_client, cid, klass="sorcerer",
        base_scores={"str": 8, "dex": 14, "con": 13, "int": 10, "wis": 12, "cha": 15},
        skill_choices=["arcana", "deception"],
        cantrips=["Fire Bolt", "Ray of Frost", "Light", "Mage Hand", "Prestidigitation"],
    )
    assert resp.status_code == 400
    # …and a spell not on the class list.
    resp = await _make_character(
        app_client, cid, klass="sorcerer",
        base_scores={"str": 8, "dex": 14, "con": 13, "int": 10, "wis": 12, "cha": 15},
        skill_choices=["arcana", "deception"],
        spells=["Cure Wounds"],  # cleric/bard/etc, not sorcerer
    )
    assert resp.status_code == 400


async def test_known_spells_reach_the_prompt(app_client):
    from app.ai.mock_provider import MockProvider
    from app.ai.provider import Done, LLMConfig, TextDelta, set_provider

    campaign, scene, _ = await setup_game(app_client)
    cid = campaign["id"]
    await _make_character(
        app_client, cid, name="Vesper", klass="sorcerer",
        base_scores={"str": 8, "dex": 14, "con": 13, "int": 10, "wis": 12, "cha": 15},
        skill_choices=["arcana", "deception"],
        cantrips=["Fire Bolt"], spells=["Magic Missile"],
    )

    mock = MockProvider(config=LLMConfig(provider="mock", toolcall_mode="native"))
    mock.queue_turn([TextDelta("The shop is quiet."), Done()])
    set_provider(mock)
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])
    system = mock.calls[0].messages[0]["content"]
    # The AI is told the caster's spells up front — no need to ask the player.
    assert "Knows:" in system
    assert "Fire Bolt" in system and "Magic Missile" in system
    set_provider(None)

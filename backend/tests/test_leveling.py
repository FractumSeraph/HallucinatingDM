"""Real leveling: spell progression, new features, ASI with retroactive CON."""

from .test_dm_modes import BUILD, setup_game


async def _give_xp(app_client, campaign_id, scene_id, amount):
    await app_client.post(
        f"/api/v1/campaigns/{campaign_id}/award",
        json={"xp_each": amount, "scene_id": scene_id},
    )


async def test_wizard_learns_spells_on_level_up(app_client):
    campaign, scene, character = await setup_game(app_client, dm_mode="human")
    # Mira the wizard starts with no chosen spells in BUILD — options reflect that.
    await _give_xp(app_client, campaign["id"], scene["id"], 300)  # level 2

    opts = (
        await app_client.get(f"/api/v1/characters/{character['id']}/level-up-options")
    ).json()
    assert opts["new_level"] == 2
    assert opts["asi"] is False
    assert opts["spell_picks"] >= 2  # wizard spellbook grows
    assert "Magic Missile" in opts["available"]["1"]
    assert opts["max_spell_level"] == 1  # no level-2 spells yet
    assert any(f["name"] == "Arcane Tradition" for f in opts["features"])

    resp = await app_client.post(
        f"/api/v1/characters/{character['id']}/level-up",
        json={"cantrips": ["Fire Bolt"], "spells": ["Magic Missile", "Shield"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["level"] == 2
    assert "Magic Missile" in body["sheet_json"]["spells"]["known"]
    assert "Fire Bolt" in body["sheet_json"]["spells"]["cantrips"]
    assert any(f["name"] == "Arcane Tradition" for f in body["sheet_json"]["features"])

    # Level 3 unlocks level-2 spells in the pick list.
    await _give_xp(app_client, campaign["id"], scene["id"], 600)  # 900 total = L3
    opts = (
        await app_client.get(f"/api/v1/characters/{character['id']}/level-up-options")
    ).json()
    assert opts["max_spell_level"] == 2
    assert "2" in opts["available"]
    # Already-known spells never reappear as picks.
    assert "Magic Missile" not in opts["available"]["1"]


async def test_invalid_picks_are_rejected(app_client):
    campaign, scene, character = await setup_game(app_client, dm_mode="human")
    await _give_xp(app_client, campaign["id"], scene["id"], 300)

    # A spell that isn't on the wizard list (or any list).
    resp = await app_client.post(
        f"/api/v1/characters/{character['id']}/level-up",
        json={"spells": ["Cure Wounds"]},
    )
    assert resp.status_code == 400
    # ASI at a non-ASI level.
    resp = await app_client.post(
        f"/api/v1/characters/{character['id']}/level-up", json={"asi": {"con": 2}}
    )
    assert resp.status_code == 400
    # Level-up still works with an empty body (choices skipped).
    resp = await app_client.post(f"/api/v1/characters/{character['id']}/level-up")
    assert resp.status_code == 200


async def test_asi_applies_with_retroactive_con_hp(app_client):
    campaign, scene, _mira = await setup_game(app_client, dm_mode="human")
    # A fighter with CON 15 (+2 mod): d10 → 10+2 = 12 HP at level 1.
    fighter = (
        await app_client.post(
            f"/api/v1/campaigns/{campaign['id']}/characters",
            json={
                **BUILD,
                "name": "Bron",
                "klass": "fighter",
                "base_scores": {"str": 14, "dex": 13, "con": 15, "int": 8, "wis": 12, "cha": 10},
                "skill_choices": ["athletics", "intimidation"],
            },
        )
    ).json()
    assert fighter["hp_max"] == 12

    # Walk to level 4 (2700 XP) taking default level-ups.
    await _give_xp(app_client, campaign["id"], scene["id"], 2700)
    for _ in range(2):
        resp = await app_client.post(f"/api/v1/characters/{fighter['id']}/level-up")
        assert resp.status_code == 200
    before = (await app_client.get(f"/api/v1/characters/{fighter['id']}")).json()
    assert before["level"] == 3

    # Level 4 is an ASI level: +1 CON (15→16 = +3 mod) and +1 STR.
    opts = (
        await app_client.get(f"/api/v1/characters/{fighter['id']}/level-up-options")
    ).json()
    assert opts["asi"] is True
    resp = await app_client.post(
        f"/api/v1/characters/{fighter['id']}/level-up",
        json={"asi": {"con": 1, "str": 1}},
    )
    assert resp.status_code == 200, resp.text
    after = resp.json()
    assert after["ability_scores_json"]["con"] == 16
    assert after["ability_scores_json"]["str"] == 15
    # HP: this level gains 6+3=9, plus retroactive +1 × 3 prior levels.
    assert after["hp_max"] == before["hp_max"] + 9 + 3

    # Can't push past 20.
    await _give_xp(app_client, campaign["id"], scene["id"], 20000)
    for _ in range(2):
        await app_client.post(f"/api/v1/characters/{fighter['id']}/level-up")
    resp = await app_client.post(
        f"/api/v1/characters/{fighter['id']}/level-up", json={"asi": {"str": 2, "con": 2}}
    )
    assert resp.status_code == 400  # +4 total is illegal


async def test_prepared_caster_and_warlock_capacities():
    from app.services.leveling import cantrips_known, max_spell_level, spells_known_cap

    # Warlock knows 2 at L1, 10 at L9; pact slots reach level-5 spells at L9.
    assert spells_known_cap("warlock", 1, {}) == 2
    assert spells_known_cap("warlock", 9, {}) == 10
    assert max_spell_level("warlock", 9) == 5
    # Cleric prepared cap = WIS mod + level.
    assert spells_known_cap("cleric", 4, {"wis": 16}) == 7
    # Paladin: nothing at 1, mod + half level after.
    assert spells_known_cap("paladin", 1, {"cha": 14}) == 0
    assert spells_known_cap("paladin", 5, {"cha": 14}) == 4
    # Cantrip growth breakpoints.
    assert cantrips_known("wizard", 3) == 3
    assert cantrips_known("wizard", 4) == 4
    assert cantrips_known("fighter", 4) == 0

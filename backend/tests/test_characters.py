WIZARD_BUILD = {
    "name": "Zanzibar the Confused",
    "race": "elf",
    "subrace": "High Elf",
    "klass": "wizard",
    "background": "acolyte",
    "method": "standard",
    "base_scores": {"str": 8, "dex": 13, "con": 14, "int": 15, "wis": 12, "cha": 10},
    "skill_choices": ["arcana", "investigation"],
}


async def make_campaign(client):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "dm@example.com", "password": "longenough", "display_name": "DM"},
    )
    resp = await client.post("/api/v1/campaigns", json={"name": "C"})
    return resp.json()


async def test_srd_endpoints(app_client):
    await make_campaign(app_client)

    resp = await app_client.get("/api/v1/srd/race")
    races = resp.json()
    assert any(r["slug"] == "dwarf" for r in races)

    resp = await app_client.get("/api/v1/srd/class/wizard")
    wizard = resp.json()
    assert wizard["data"]["hit_die"] == 6
    assert wizard["data"]["spellcasting_ability"] == "INT"

    resp = await app_client.get("/api/v1/srd/monster?q=goblin")
    assert any(m["slug"] == "goblin" for m in resp.json())

    resp = await app_client.get("/api/v1/srd/nonsense")
    assert resp.status_code == 400


async def test_character_creation_standard_array(app_client):
    campaign = await make_campaign(app_client)

    resp = await app_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters", json=WIZARD_BUILD
    )
    assert resp.status_code == 200, resp.text
    c = resp.json()
    # High elf gets +2 dex +1 int (SRD): base dex 13 -> 15, int 15 -> 16
    assert c["ability_scores_json"]["dex"] == 15
    assert c["ability_scores_json"]["int"] == 16
    # hp = 6 (d6 max) + con mod (14 -> +2)
    assert c["hp_max"] == 8
    assert c["hp_current"] == 8
    # ac = 10 + dex mod (+2)
    assert c["ac"] == 12
    # wizard slots at level 1
    assert c["spell_slots_json"]["1"] == {"max": 2, "used": 0}
    # class skills + background skills merged
    assert set(c["proficiencies_json"]["skills"]) == {
        "arcana",
        "investigation",
        "insight",
        "religion",
    }
    assert c["proficiencies_json"]["saves"] == ["int", "wis"]
    assert c["status"] == "active"


async def test_character_creation_validation(app_client):
    campaign = await make_campaign(app_client)
    cid = campaign["id"]

    # bad standard array
    bad = dict(WIZARD_BUILD, base_scores={**WIZARD_BUILD["base_scores"], "str": 18})
    resp = await app_client.post(f"/api/v1/campaigns/{cid}/characters", json=bad)
    assert resp.status_code == 400

    # wrong number of skills
    bad = dict(WIZARD_BUILD, skill_choices=["arcana"])
    resp = await app_client.post(f"/api/v1/campaigns/{cid}/characters", json=bad)
    assert resp.status_code == 400

    # non-class skill
    bad = dict(WIZARD_BUILD, skill_choices=["arcana", "athletics"])
    resp = await app_client.post(f"/api/v1/campaigns/{cid}/characters", json=bad)
    assert resp.status_code == 400

    # unknown race
    bad = dict(WIZARD_BUILD, race="astral-elf")
    resp = await app_client.post(f"/api/v1/campaigns/{cid}/characters", json=bad)
    assert resp.status_code == 400

    # rolled scores are server-generated and legal
    rolled = dict(WIZARD_BUILD, method="roll", base_scores={})
    resp = await app_client.post(f"/api/v1/campaigns/{cid}/characters", json=rolled)
    assert resp.status_code == 200
    scores = resp.json()["sheet_json"]["base_scores"]
    assert all(3 <= v <= 18 for v in scores.values())


async def test_inventory_flow(app_client):
    campaign = await make_campaign(app_client)
    resp = await app_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters", json=WIZARD_BUILD
    )
    char_id = resp.json()["id"]

    resp = await app_client.post(
        f"/api/v1/characters/{char_id}/inventory",
        json={"name": "Torch", "quantity": 5},
    )
    assert resp.status_code == 200
    entry = resp.json()
    assert entry["quantity"] == 5

    # adding the same item stacks
    resp = await app_client.post(
        f"/api/v1/characters/{char_id}/inventory", json={"name": "torch", "quantity": 2}
    )
    assert resp.json()["quantity"] == 7

    # set quantity to zero deletes
    resp = await app_client.patch(
        f"/api/v1/inventory/{entry['entry_id']}", json={"quantity": 0}
    )
    assert resp.json() == {"deleted": True, "entry_id": entry["entry_id"]}

    # the Torch is gone (the character still has its class starting kit)
    resp = await app_client.get(f"/api/v1/characters/{char_id}/inventory")
    assert not any(i["name"].lower() == "torch" for i in resp.json())


async def test_hp_patch_clamps(app_client):
    campaign = await make_campaign(app_client)
    resp = await app_client.post(
        f"/api/v1/campaigns/{campaign['id']}/characters", json=WIZARD_BUILD
    )
    c = resp.json()

    resp = await app_client.patch(
        f"/api/v1/characters/{c['id']}", json={"hp_current": 999}
    )
    assert resp.json()["hp_current"] == c["hp_max"]
    resp = await app_client.patch(
        f"/api/v1/characters/{c['id']}", json={"hp_current": -5}
    )
    assert resp.json()["hp_current"] == 0

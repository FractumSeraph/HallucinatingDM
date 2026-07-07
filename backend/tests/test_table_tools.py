"""DM table tools: rest button, secret rolls, combatant HP nudge, remove player."""

from .test_dm_modes import setup_game


async def test_dm_rest_endpoint_restores_the_party(app_client):
    campaign, scene, character = await setup_game(app_client, dm_mode="human")

    # Wound Mira first.
    await app_client.patch(f"/api/v1/characters/{character['id']}", json={"hp_current": 3})

    resp = await app_client.post(f"/api/v1/scenes/{scene['id']}/rest", json={"kind": "long"})
    assert resp.status_code == 200, resp.text
    assert any("full HP" in line for line in resp.json()["party"])

    body = (await app_client.get(f"/api/v1/characters/{character['id']}")).json()
    assert body["hp_current"] == body["hp_max"]

    messages = (await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")).json()
    assert any("long rest" in m["content"] for m in messages)


async def test_players_cannot_call_rests(app_client):
    campaign, scene, _character = await setup_game(app_client, dm_mode="human")
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "p20@example.com", "password": "longenough", "display_name": "P"},
    )
    await app_client.post(
        "/api/v1/campaigns/join", json={"invite_code": campaign["invite_code"]}
    )
    resp = await app_client.post(f"/api/v1/scenes/{scene['id']}/rest", json={"kind": "long"})
    assert resp.status_code == 403


async def test_secret_dm_rolls_are_hidden_from_players(app_client):
    campaign, scene, _character = await setup_game(app_client, dm_mode="human")

    resp = await app_client.post(
        f"/api/v1/scenes/{scene['id']}/roll",
        json={"expression": "1d20", "purpose": "secret check", "secret": True},
    )
    assert resp.status_code == 200

    # The DM sees the roll…
    messages = (await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")).json()
    assert any(m["kind"] == "roll" for m in messages)

    # …a player does not, and can't roll in secret themselves.
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "p21@example.com", "password": "longenough", "display_name": "P"},
    )
    await app_client.post(
        "/api/v1/campaigns/join", json={"invite_code": campaign["invite_code"]}
    )
    messages = (await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")).json()
    assert not any(m["kind"] == "roll" for m in messages)
    resp = await app_client.post(
        f"/api/v1/scenes/{scene['id']}/roll", json={"expression": "1d20", "secret": True}
    )
    assert resp.status_code == 403


async def test_dm_nudges_combatant_hp_from_the_tracker(app_client):
    campaign, scene, character = await setup_game(app_client, dm_mode="human")
    resp = await app_client.post(
        f"/api/v1/scenes/{scene['id']}/combat",
        json={"participants": [character["name"], "wolf"]},
    )
    assert resp.status_code == 200
    combatants = resp.json()["combatants"]
    wolf = next(c for c in combatants if c["name"] == "Wolf")

    # Damage the wolf by 5 (11 hp → 6).
    resp = await app_client.patch(f"/api/v1/combatants/{wolf['id']}", json={"delta": -5})
    assert resp.status_code == 200
    updated = next(c for c in resp.json()["combatants"] if c["id"] == wolf["id"])
    assert updated["hp_current"] == wolf["hp_current"] - 5

    # Overkill marks it down; healing brings it back up.
    resp = await app_client.patch(f"/api/v1/combatants/{wolf['id']}", json={"delta": -999})
    updated = next(c for c in resp.json()["combatants"] if c["id"] == wolf["id"])
    assert updated["defeated"] is True
    resp = await app_client.patch(f"/api/v1/combatants/{wolf['id']}", json={"delta": 3})
    updated = next(c for c in resp.json()["combatants"] if c["id"] == wolf["id"])
    assert updated["defeated"] is False and updated["hp_current"] == 3

    # Character rows route to the sheet (clamped to max).
    mira = next(c for c in combatants if c["name"] == character["name"])
    resp = await app_client.patch(f"/api/v1/combatants/{mira['id']}", json={"delta": -4})
    assert resp.status_code == 200
    body = (await app_client.get(f"/api/v1/characters/{character['id']}")).json()
    assert body["hp_current"] == character["hp_max"] - 4


async def test_dm_removes_a_player(app_client):
    campaign, scene, _character = await setup_game(app_client, dm_mode="human")

    # A player joins and makes a character that enters the scene roster.
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "leaver@example.com", "password": "longenough", "display_name": "Leaver"},
    )
    await app_client.post(
        "/api/v1/campaigns/join", json={"invite_code": campaign["invite_code"]}
    )
    from .test_dm_modes import BUILD

    pc = (
        await app_client.post(
            f"/api/v1/campaigns/{campaign['id']}/characters",
            json={**BUILD, "name": "Wanderer"},
        )
    ).json()
    members = (await app_client.get(f"/api/v1/campaigns/{campaign['id']}/members")).json()
    leaver_id = next(m["user_id"] for m in members if m["display_name"] == "Leaver")

    # A player can't remove anyone.
    resp = await app_client.delete(f"/api/v1/campaigns/{campaign['id']}/members/{leaver_id}")
    assert resp.status_code == 403

    # The DM can.
    await app_client.post(
        "/api/v1/auth/login", json={"email": "dm@example.com", "password": "longenough"}
    )
    resp = await app_client.delete(f"/api/v1/campaigns/{campaign['id']}/members/{leaver_id}")
    assert resp.status_code == 200

    members = (await app_client.get(f"/api/v1/campaigns/{campaign['id']}/members")).json()
    assert not any(m["display_name"] == "Leaver" for m in members)
    # Their character is retired, not deleted.
    body = (await app_client.get(f"/api/v1/characters/{pc['id']}")).json()
    assert body["status"] == "retired"

    # The owner can't be removed, nor can the DM remove themself.
    dm_id = next(m["user_id"] for m in members if m["role"] == "dm")
    resp = await app_client.delete(f"/api/v1/campaigns/{campaign['id']}/members/{dm_id}")
    assert resp.status_code == 400

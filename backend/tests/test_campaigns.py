async def register(client, email: str, name: str):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "longenough", "display_name": name},
    )
    assert resp.status_code == 200
    return resp.json()


async def login(client, email: str):
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "longenough"}
    )
    assert resp.status_code == 200


async def test_campaign_create_join_members(app_client):
    await register(app_client, "dm@example.com", "The DM")
    resp = await app_client.post(
        "/api/v1/campaigns", json={"name": "Curse of the Hallucinated Keep"}
    )
    assert resp.status_code == 200
    campaign = resp.json()
    assert campaign["my_role"] == "dm"
    invite = campaign["invite_code"]
    assert invite

    # player joins by invite code
    await register(app_client, "p1@example.com", "P1")
    resp = await app_client.post("/api/v1/campaigns/join", json={"invite_code": invite})
    assert resp.status_code == 200
    assert resp.json()["my_role"] == "player"
    assert resp.json()["invite_code"] == ""  # players don't see the code

    # bad code
    resp = await app_client.post("/api/v1/campaigns/join", json={"invite_code": "nope"})
    assert resp.status_code == 400

    resp = await app_client.get(f"/api/v1/campaigns/{campaign['id']}/members")
    roles = {m["display_name"]: m["role"] for m in resp.json()}
    assert roles == {"The DM": "dm", "P1": "player"}

    # players cannot patch the campaign
    resp = await app_client.patch(
        f"/api/v1/campaigns/{campaign['id']}", json={"name": "Renamed"}
    )
    assert resp.status_code == 403

    # non-members cannot view
    await register(app_client, "outsider@example.com", "Out")
    resp = await app_client.get(f"/api/v1/campaigns/{campaign['id']}")
    assert resp.status_code == 403

    # DM can patch
    await login(app_client, "dm@example.com")
    resp = await app_client.patch(
        f"/api/v1/campaigns/{campaign['id']}", json={"name": "Renamed"}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"

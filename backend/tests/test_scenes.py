async def setup_campaign(client):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "dm@example.com", "password": "longenough", "display_name": "DM"},
    )
    resp = await client.post("/api/v1/campaigns", json={"name": "Test Campaign"})
    return resp.json()


async def add_player(client, campaign, email="p1@example.com", name="P1"):
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "longenough", "display_name": name},
    )
    await client.post("/api/v1/campaigns/join", json={"invite_code": campaign["invite_code"]})


async def login(client, email):
    await client.post("/api/v1/auth/login", json={"email": email, "password": "longenough"})


async def test_scene_lifecycle_and_messages(app_client):
    campaign = await setup_campaign(app_client)
    cid = campaign["id"]

    resp = await app_client.post(
        f"/api/v1/campaigns/{cid}/scenes",
        json={"name": "The Main Table", "kind": "main", "dm_mode": "human"},
    )
    assert resp.status_code == 200
    scene = resp.json()

    # post + list messages with seq ordering
    for i in range(3):
        resp = await app_client.post(
            f"/api/v1/scenes/{scene['id']}/messages", json={"content": f"msg {i}"}
        )
        assert resp.status_code == 200
    resp = await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")
    msgs = resp.json()
    assert [m["seq"] for m in msgs] == [1, 2, 3]
    assert msgs[0]["author_type"] == "dm"

    # resync from a seq
    resp = await app_client.get(f"/api/v1/scenes/{scene['id']}/messages?after_seq=2")
    assert [m["seq"] for m in resp.json()] == [3]

    # dice roll becomes a message with verifiable faces
    resp = await app_client.post(
        f"/api/v1/scenes/{scene['id']}/roll",
        json={"expression": "2d6+3", "purpose": "check"},
    )
    assert resp.status_code == 200
    payload = resp.json()["payload_json"]["roll"]
    assert len(payload["rolls"]) == 2
    assert payload["total"] == sum(payload["rolls"]) + 3

    # invalid dice expression is a 400
    resp = await app_client.post(
        f"/api/v1/scenes/{scene['id']}/roll", json={"expression": "banana"}
    )
    assert resp.status_code == 400


async def test_player_scene_permissions(app_client):
    campaign = await setup_campaign(app_client)
    cid = campaign["id"]
    await add_player(app_client, campaign)

    # players cannot create main scenes…
    resp = await app_client.post(
        f"/api/v1/campaigns/{cid}/scenes", json={"name": "Nope", "kind": "main"}
    )
    assert resp.status_code == 403

    # …but can create solo AI adventures
    resp = await app_client.post(
        f"/api/v1/campaigns/{cid}/scenes",
        json={"name": "Midnight Heist", "kind": "solo", "dm_mode": "ai"},
    )
    assert resp.status_code == 200
    scene = resp.json()

    # players cannot patch scenes
    resp = await app_client.patch(f"/api/v1/scenes/{scene['id']}", json={"name": "X"})
    assert resp.status_code == 403

    # DM can
    await login(app_client, "dm@example.com")
    resp = await app_client.patch(
        f"/api/v1/scenes/{scene['id']}", json={"dm_mode": "assist"}
    )
    assert resp.status_code == 200
    assert resp.json()["dm_mode"] == "assist"


async def test_dm_only_message_visibility(app_client):
    campaign = await setup_campaign(app_client)
    cid = campaign["id"]
    resp = await app_client.post(
        f"/api/v1/campaigns/{cid}/scenes", json={"name": "Table", "dm_mode": "human"}
    )
    scene = resp.json()

    # DM-only whisper via the message service directly (API for this lands later)
    from app.db import get_sessionmaker
    from app.models import Scene
    from app.services.messages import create_message

    async with get_sessionmaker()() as db:
        scene_row = await db.get(Scene, scene["id"])
        await create_message(
            db,
            scene_row,
            author_type="system",
            content="secret plot info",
            visibility="dm",
            broadcast=False,
        )

    resp = await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")
    assert any(m["content"] == "secret plot info" for m in resp.json())

    await add_player(app_client, campaign)
    resp = await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")
    assert not any(m["content"] == "secret plot info" for m in resp.json())

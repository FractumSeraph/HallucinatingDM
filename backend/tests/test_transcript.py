"""Scene transcript export + tail message loading."""

from app.ai.provider import Done, TextDelta, set_provider

from .test_dm_agent import make_mock, setup_game


async def _seed_chatter(client, scene_id, character_id, n):
    for i in range(n):
        await client.post(
            f"/api/v1/scenes/{scene_id}/messages",
            json={"content": f"Line {i}", "character_id": character_id},
        )


async def test_transcript_is_readable_and_complete(app_client):
    campaign, scene, character = await setup_game(app_client)

    # A player line, a roll, a DM whisper, and an AI narration turn.
    await app_client.post(
        f"/api/v1/scenes/{scene['id']}/messages",
        json={"content": "I kick open the door.", "character_id": character["id"]},
    )
    await app_client.post(
        f"/api/v1/scenes/{scene['id']}/roll",
        json={"expression": "1d20+3", "purpose": "check", "character_id": character["id"]},
    )
    await app_client.post(
        f"/api/v1/scenes/{scene['id']}/whisper",
        json={"content": "The room is trapped."},
    )
    make_mock([[TextDelta("The door bursts inward."), Done()]])
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])

    resp = await app_client.get(f"/api/v1/scenes/{scene['id']}/transcript")
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    assert "attachment" in resp.headers["content-disposition"]
    body = resp.text

    # DM (session owner) sees everything, attributed and readable.
    assert "# C — Ambush" in body
    assert "**Mira**: I kick open the door." in body
    assert "🎲 Mira rolled 1d20+3" in body
    assert "**DM**: The door bursts inward." in body
    assert "whisper" in body.lower() and "The room is trapped." in body
    set_provider(None)


async def test_tool_result_chips_are_not_labeled_as_players(app_client):
    campaign, scene, character = await setup_game(app_client)

    from app.db import get_sessionmaker
    from app.models import Scene
    from app.services.messages import create_message

    async with get_sessionmaker()() as db:
        s = await db.get(Scene, scene["id"])
        await create_message(
            db, s, author_type="tool", kind="tool_result",
            content="📜 Quest started: Deliver the tube", broadcast=False,
        )

    body = (await app_client.get(f"/api/v1/scenes/{scene['id']}/transcript")).text
    # Rendered as an italic mechanics note, never attributed to a "Player".
    assert "_📜 Quest started: Deliver the tube_" in body
    assert "Player**: 📜" not in body


async def test_transcript_hides_dm_content_from_players(app_client):
    campaign, scene, character = await setup_game(app_client)
    await app_client.post(
        f"/api/v1/scenes/{scene['id']}/messages",
        json={"content": "Public line.", "character_id": character["id"]},
    )
    await app_client.post(
        f"/api/v1/scenes/{scene['id']}/whisper", json={"content": "Secret: the vault code is 421."}
    )

    invite = campaign["invite_code"]
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "pl@example.com", "password": "longenough", "display_name": "PL"},
    )
    await app_client.post("/api/v1/campaigns/join", json={"invite_code": invite})

    resp = await app_client.get(f"/api/v1/scenes/{scene['id']}/transcript")
    assert resp.status_code == 200
    assert "Public line." in resp.text
    assert "vault code" not in resp.text  # whisper is DM-only


async def test_tail_returns_most_recent_window(app_client):
    campaign, scene, character = await setup_game(app_client)
    await _seed_chatter(app_client, scene["id"], character["id"], 12)

    # Oldest-first (default) starts at the beginning.
    head = (await app_client.get(f"/api/v1/scenes/{scene['id']}/messages?limit=5")).json()
    assert [m["content"] for m in head] == ["Line 0", "Line 1", "Line 2", "Line 3", "Line 4"]

    # tail=true returns the newest window, still in chronological order.
    tail = (
        await app_client.get(f"/api/v1/scenes/{scene['id']}/messages?tail=true&limit=5")
    ).json()
    assert [m["content"] for m in tail] == ["Line 7", "Line 8", "Line 9", "Line 10", "Line 11"]
    assert tail[0]["seq"] < tail[-1]["seq"]
